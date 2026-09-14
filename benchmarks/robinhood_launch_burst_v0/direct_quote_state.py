"""Causal read-only state adapter for Pons V2 direct curve quotes.

All state is pinned to one explicit block tag. The adapter re-reads the block
header after the eth_calls and rejects a hash change, so a reorg cannot silently
mix reserve/tax/graduation state from different canonical histories.
"""
from __future__ import annotations

from dataclasses import asdict
import time
from typing import Any, Mapping

from src.pons_v2_curve_quote_v0 import (
    PonsCurveQuoteStateV0,
    SNIPE_MODE_LIVE_VIEW,
    SNIPE_MODE_PROVEN_ABSENT,
)


PASS_SNIPE = "PASS_PONS_PROTOCOL_CAPABILITIES_V0_SNIPE_VIEW"
PASS_NO_SNIPE = "PASS_PONS_PROTOCOL_CAPABILITIES_V0_BASE_CURVE_NO_SNIPE_VIEW"


def _address(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip().lower()
    if not normalized.startswith("0x") or len(normalized) != 42:
        raise ValueError(f"invalid {name}: {value!r}")
    int(normalized[2:], 16)
    return normalized


def _selector(client, signature: str) -> str:
    value = client.sha3_text(signature)
    if not isinstance(value, str) or not value.startswith("0x") or len(value) < 10:
        raise ValueError(f"invalid selector hash for {signature}")
    return value[:10]


def _call(client, *, curve: str, data: str, block_tag: str) -> str:
    value = client.call("eth_call", [{"to": curve, "data": data}, block_tag])
    if not isinstance(value, str) or not value.startswith("0x"):
        raise RuntimeError("invalid eth_call response")
    return value


def _decode_words(value: str, count: int) -> tuple[int, ...]:
    body = value[2:]
    if len(body) != 64 * count:
        raise ValueError(f"expected {count} ABI words, got {len(body) // 64}")
    return tuple(int(body[index : index + 64], 16) for index in range(0, len(body), 64))


def _uint_view(client, *, curve: str, signature: str, block_tag: str) -> tuple[int, str]:
    raw = _call(client, curve=curve, data=_selector(client, signature), block_tag=block_tag)
    return _decode_words(raw, 1)[0], raw


def _bool_view(client, *, curve: str, signature: str, block_tag: str) -> tuple[bool, str]:
    raw = _call(client, curve=curve, data=_selector(client, signature), block_tag=block_tag)
    word = _decode_words(raw, 1)[0]
    if word not in (0, 1):
        raise ValueError(f"{signature} returned non-bool ABI word: {word}")
    return bool(word), raw


def _reserves_view(client, *, curve: str, block_tag: str) -> tuple[tuple[int, int], str]:
    raw = _call(client, curve=curve, data=_selector(client, "getReserves()"), block_tag=block_tag)
    values = _decode_words(raw, 2)
    return (values[0], values[1]), raw


def _address_uint_view(
    client,
    *,
    curve: str,
    signature: str,
    address: str,
    block_tag: str,
) -> tuple[int, str]:
    encoded = _address(address, "address")[2:].rjust(64, "0")
    raw = _call(
        client,
        curve=curve,
        data=_selector(client, signature) + encoded,
        block_tag=block_tag,
    )
    return _decode_words(raw, 1)[0], raw


def _block_identity(client, block_tag: str) -> dict[str, Any]:
    row = client.call("eth_getBlockByNumber", [block_tag, False])
    if not isinstance(row, dict):
        raise RuntimeError("eth_getBlockByNumber returned no block")
    block_hash = str(row.get("hash") or "").lower()
    if not block_hash.startswith("0x") or len(block_hash) != 66:
        raise RuntimeError("block hash unavailable for pinned quote state")
    return {
        "number": int(str(row.get("number") or block_tag), 16),
        "hash": block_hash,
        "timestamp_s": int(str(row.get("timestamp") or "0x0"), 16),
    }


def read_curve_quote_state_v0(
    client,
    *,
    curve: str,
    recipient: str,
    capability_report: Mapping[str, Any],
) -> tuple[PonsCurveQuoteStateV0, dict[str, Any]]:
    """Read one internally consistent Pons quote state at a pinned block.

    ``capability_report`` must come from ``probe_protocol_capabilities_v0``.
    A snipe-enabled generation requires a recipient-specific live snipe read;
    a proven no-snipe generation never silently attempts to infer one.
    """
    curve = _address(curve, "curve")
    recipient = _address(recipient, "recipient")
    classification = str(capability_report.get("classification") or "")
    generation_key = str(capability_report.get("generation_key") or "").strip()
    factory = str(capability_report.get("factory") or "").strip().lower()
    if classification not in {PASS_SNIPE, PASS_NO_SNIPE}:
        raise ValueError("capability_report is not quote-ready")
    if not generation_key:
        raise ValueError("capability_report has no generation_key")
    if not factory:
        raise ValueError("capability_report has no factory provenance")

    block_number = int(client.block_number())
    if block_number < 0:
        raise ValueError("negative block number")
    block_tag = hex(block_number)
    before = _block_identity(client, block_tag)

    code = client.call("eth_getCode", [curve, block_tag])
    if not isinstance(code, str) or code in {"0x", "0x0", ""}:
        raise RuntimeError("target curve has no bytecode at pinned block")

    raw_calls: dict[str, str] = {}
    fee_bps, raw_calls["feeBps"] = _uint_view(
        client, curve=curve, signature="feeBps()", block_tag=block_tag
    )
    creator_tax_bps, raw_calls["creatorTaxBps"] = _uint_view(
        client, curve=curve, signature="creatorTaxBps()", block_tag=block_tag
    )
    reserves, raw_calls["getReserves"] = _reserves_view(client, curve=curve, block_tag=block_tag)
    sellable, raw_calls["sellableTokens"] = _uint_view(
        client, curve=curve, signature="sellableTokens()", block_tag=block_tag
    )
    ready, raw_calls["readyToGraduate"] = _bool_view(
        client, curve=curve, signature="readyToGraduate()", block_tag=block_tag
    )
    graduated, raw_calls["graduated"] = _bool_view(
        client, curve=curve, signature="graduated()", block_tag=block_tag
    )

    if classification == PASS_SNIPE:
        snipe_mode = SNIPE_MODE_LIVE_VIEW
        current_snipe, raw_calls["currentSnipeTaxBps"] = _address_uint_view(
            client,
            curve=curve,
            signature="currentSnipeTaxBps(address)",
            address=recipient,
            block_tag=block_tag,
        )
    else:
        snipe_mode = SNIPE_MODE_PROVEN_ABSENT
        current_snipe = 0

    after = _block_identity(client, block_tag)
    if before["hash"] != after["hash"]:
        raise RuntimeError("pinned block hash changed during quote state read")
    if before["number"] != after["number"]:
        raise RuntimeError("pinned block number changed during quote state read")

    observed_at_ns = time.time_ns()
    provenance = (
        f"factory={factory}",
        f"curve={curve}",
        f"recipient={recipient}",
        f"block_number={block_number}",
        f"block_hash={before['hash']}",
        f"capability_classification={classification}",
    )
    state = PonsCurveQuoteStateV0(
        quote_reserve_raw=reserves[0],
        token_reserve_raw=reserves[1],
        sellable_tokens_raw=sellable,
        fee_bps=fee_bps,
        creator_tax_bps=creator_tax_bps,
        snipe_mode=snipe_mode,
        current_snipe_tax_bps=current_snipe,
        ready_to_graduate=ready,
        graduated=graduated,
        observed_at_ns=observed_at_ns,
        protocol_generation_key=generation_key,
        provenance=provenance,
    )
    evidence = {
        "method_version": "pons_v2_curve_quote_state_v0",
        "curve": curve,
        "recipient": recipient,
        "factory": factory,
        "block": before,
        "observed_at_ns": observed_at_ns,
        "capability_classification": classification,
        "protocol_generation_key": generation_key,
        "snipe_mode": snipe_mode,
        "raw_calls": raw_calls,
        "bytecode_observed": True,
        "reorg_guard_passed": True,
        "state": asdict(state),
        "economic_outcomes_opened": False,
        "fill_claimed": False,
    }
    return state, evidence
