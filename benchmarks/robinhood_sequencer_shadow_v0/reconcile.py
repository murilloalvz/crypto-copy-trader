"""Post-observation reconciliation for Robinhood Nitro feed intents.

Canonical Ethereum transaction hashes are resolved *after* feed observation with
RPC ``web3_sha3(raw_signed_tx)``. That later identity step receives its own
clock and never moves the original feed availability time earlier.

RPC launch/trade events remain execution evidence. A feed intent without a
matched tracked event is UNKNOWN, not a failed trade or zero-return outcome.
"""
from __future__ import annotations

import time
from typing import Any, Iterable, Mapping

from src.robinhood_nitro_feed_v0 import (
    NitroSignedTxIntentV0,
    classify_pons_intent_v0,
)


RESOLUTION_SCOPE = "POST_OBSERVATION_IDENTITY_ONLY"


def _tx_hash(value: Any, name: str = "transaction_hash") -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip().lower()
    if not normalized.startswith("0x") or len(normalized) != 66:
        raise ValueError(f"invalid {name}: {value!r}")
    int(normalized[2:], 16)
    return normalized


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    return {
        "n": len(values),
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "mean": (sum(values) / len(values)) if values else None,
    }


def resolve_chain_tx_hash_v0(client, intent: NitroSignedTxIntentV0) -> dict[str, Any]:
    """Resolve canonical Ethereum tx identity without changing feed-time evidence."""
    raw_hex = "0x" + intent.raw_tx.hex()
    started_ns = time.time_ns()
    value = client.call("web3_sha3", [raw_hex])
    resolved_ns = time.time_ns()
    chain_tx_hash = _tx_hash(value, "web3_sha3 result")
    return {
        "sequence_number": intent.sequence_number,
        "batch_path": list(intent.batch_path),
        "to": intent.to,
        "value_raw": intent.value_raw,
        "calldata_selector": intent.calldata_selector,
        "raw_tx_sha256": intent.raw_tx_sha256,
        "chain_tx_hash": chain_tx_hash,
        "feed_observed_at_ns": intent.observed_at_ns,
        "hash_resolution_started_at_ns": started_ns,
        "hash_resolved_at_ns": resolved_ns,
        "hash_resolution_lag_ms": (resolved_ns - intent.observed_at_ns) / 1_000_000.0,
        "resolution_service_ms": (resolved_ns - started_ns) / 1_000_000.0,
        "resolution_scope": RESOLUTION_SCOPE,
        "execution_confirmed": False,
        "economic_outcomes_opened": False,
    }


def resolve_pons_intent_v0(
    client,
    intent: NitroSignedTxIntentV0,
    *,
    factory_address: str,
    known_curve_addresses: Iterable[str] = (),
    buy_selector: str | None = None,
    sell_selector: str | None = None,
) -> dict[str, Any] | None:
    classified = classify_pons_intent_v0(
        intent,
        factory_address=factory_address,
        known_curve_addresses=known_curve_addresses,
        buy_selector=buy_selector,
        sell_selector=sell_selector,
    )
    if classified is None:
        return None
    resolved = resolve_chain_tx_hash_v0(client, intent)
    resolved.update(
        {
            "intent_kind": classified.intent_kind,
            "target": classified.target,
            "evidence_scope": classified.evidence_scope,
        }
    )
    return resolved


def _rpc_events_by_tx(rpc_events: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for index, source in enumerate(rpc_events):
        row = dict(source)
        tx = row.get("transaction_hash")
        if tx is None:
            continue
        tx_hash = _tx_hash(tx, f"rpc_events[{index}].transaction_hash")
        observed = row.get("observed_at_ns")
        if not isinstance(observed, int) or isinstance(observed, bool) or observed < 0:
            raise ValueError(f"rpc_events[{index}] has invalid observed_at_ns")
        output.setdefault(tx_hash, []).append(row)
    for rows in output.values():
        rows.sort(key=lambda row: (int(row["observed_at_ns"]), str(row.get("kind") or "")))
    return output


def _semantic_match(intent: Mapping[str, Any], event: Mapping[str, Any]) -> bool:
    kind = str(intent.get("intent_kind") or "")
    target = str(intent.get("target") or "").lower()
    event_kind = str(event.get("kind") or "").lower()
    if kind == "PONS_CURVE_BUY_INTENT":
        return (
            event_kind == "trade"
            and str(event.get("side") or "").upper() == "BUY"
            and str(event.get("curve") or "").lower() == target
        )
    if kind == "PONS_CURVE_SELL_INTENT":
        return (
            event_kind == "trade"
            and str(event.get("side") or "").upper() == "SELL"
            and str(event.get("curve") or "").lower() == target
        )
    if kind == "PONS_FACTORY_TARGET_INTENT":
        return event_kind == "launch"
    if kind == "PONS_CURVE_OTHER_INTENT":
        return str(event.get("curve") or "").lower() == target
    return False


def reconcile_pons_intents_to_rpc_events_v0(
    resolved_pons_intents: Iterable[Mapping[str, Any]],
    rpc_events: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Match feed Pons intents to tracked executed Pons events by canonical tx hash."""
    executed = _rpc_events_by_tx(rpc_events)
    rows = []
    exact_latencies_ms: list[float] = []
    tx_hash_match_count = 0
    semantic_match_count = 0
    unresolved_count = 0

    for index, source in enumerate(resolved_pons_intents):
        intent = dict(source)
        chain_tx_hash = _tx_hash(intent.get("chain_tx_hash"), f"intents[{index}].chain_tx_hash")
        feed_ns = intent.get("feed_observed_at_ns")
        if not isinstance(feed_ns, int) or isinstance(feed_ns, bool) or feed_ns < 0:
            raise ValueError(f"intents[{index}] has invalid feed_observed_at_ns")
        matches = executed.get(chain_tx_hash, [])
        tx_hash_matched = bool(matches)
        if tx_hash_matched:
            tx_hash_match_count += 1
        semantic = [event for event in matches if _semantic_match(intent, event)]
        semantic_matched = bool(semantic)
        if semantic_matched:
            semantic_match_count += 1
            first_event_ns = min(int(event["observed_at_ns"]) for event in semantic)
            latency_ms = (first_event_ns - feed_ns) / 1_000_000.0
            exact_latencies_ms.append(latency_ms)
            status = "MATCHED_EXECUTED_PONS_EVENT"
        elif tx_hash_matched:
            first_event_ns = min(int(event["observed_at_ns"]) for event in matches)
            latency_ms = (first_event_ns - feed_ns) / 1_000_000.0
            status = "TX_HASH_MATCH_SEMANTIC_EVENT_NOT_MATCHED"
        else:
            first_event_ns = None
            latency_ms = None
            status = "NO_TRACKED_RPC_EVENT_OBSERVED"
            unresolved_count += 1

        rows.append(
            {
                "sequence_number": intent.get("sequence_number"),
                "batch_path": intent.get("batch_path"),
                "chain_tx_hash": chain_tx_hash,
                "intent_kind": intent.get("intent_kind"),
                "target": intent.get("target"),
                "feed_observed_at_ns": feed_ns,
                "status": status,
                "tx_hash_matched": tx_hash_matched,
                "semantic_event_matched": semantic_matched,
                "matched_event_count": len(matches),
                "semantic_event_count": len(semantic),
                "first_rpc_observed_at_ns": first_event_ns,
                "feed_to_rpc_observation_delta_ms": latency_ms,
            }
        )

    total = len(rows)
    return {
        "method_version": "robinhood_sequencer_rpc_reconciliation_v0",
        "intent_count": total,
        "tx_hash_match_count": tx_hash_match_count,
        "semantic_match_count": semantic_match_count,
        "unresolved_count": unresolved_count,
        "tx_hash_match_pct": (100.0 * tx_hash_match_count / total) if total else None,
        "semantic_match_pct": (100.0 * semantic_match_count / total) if total else None,
        "matched_feed_to_rpc_delta_ms": _distribution(exact_latencies_ms),
        "rows": rows,
        "feed_evidence_scope": "INTENT_ONLY_NOT_EXECUTION_PROOF",
        "rpc_evidence_scope": "EXECUTED_EVENT_OBSERVATION",
        "economic_outcomes_opened": False,
        "trade_returns_computed": False,
        "notes": [
            "no_tracked_rpc_event_is_unknown_not_failed_execution",
            "negative_feed_to_rpc_delta_is_retained_and_can_indicate_feed_backfill_or_clock_ordering",
            "hash_resolution_occurs_after_feed_observation_and_does_not_change_feed_clock",
        ],
    }
