"""Read-only deployed-capability probe for Pons V2 curve generations.

The public Pons source/docs can move at different speeds. V0 therefore records
what a real recently launched curve exposes through eth_call instead of assigning
fee/snipe semantics from repository text alone.
"""
from __future__ import annotations


def _topic_address(topic: str) -> str:
    body = str(topic).lower().removeprefix("0x").rjust(64, "0")
    if len(body) != 64:
        raise ValueError("invalid indexed address topic")
    return "0x" + body[-40:]


def _selector(client, signature: str) -> str:
    return client.sha3_text(signature)[:10]


def _eth_call(client, address: str, data: str) -> tuple[bool, str | None, str | None]:
    try:
        value = client.call("eth_call", [{"to": address, "data": data}, "latest"])
        if not isinstance(value, str) or not value.startswith("0x"):
            return False, None, "INVALID_ETH_CALL_RESULT"
        return True, value, None
    except Exception as exc:
        return False, None, f"{type(exc).__name__}:{exc}"


def _recent_curve(client, *, factory: str, token_launched_topic0: str, latest_block: int, lookback_blocks: int):
    start = max(0, latest_block - lookback_blocks + 1)
    rows = client.call(
        "eth_getLogs",
        [{
            "fromBlock": hex(start),
            "toBlock": hex(latest_block),
            "address": factory,
            "topics": [token_launched_topic0],
        }],
    )
    if not isinstance(rows, list) or not rows:
        return None
    rows = [row for row in rows if isinstance(row, dict)]
    rows.sort(
        key=lambda row: (
            int(str(row.get("blockNumber") or "0x0"), 16),
            int(str(row.get("transactionIndex") or "0x0"), 16),
            int(str(row.get("logIndex") or "0x0"), 16),
        )
    )
    row = rows[-1]
    topics = list(row.get("topics") or [])
    if len(topics) < 4:
        raise ValueError("recent TokenLaunched log lacks indexed curve/deployer")
    return {
        "curve": _topic_address(topics[2]),
        "deployer": _topic_address(topics[3]),
        "block_number": int(str(row.get("blockNumber") or "0x0"), 16),
        "transaction_hash": str(row.get("transactionHash") or ""),
    }


def probe_protocol_capabilities_v0(
    client,
    *,
    factory: str,
    token_launched_topic0: str,
    lookback_blocks: int = 5_000,
) -> dict:
    latest = client.block_number()
    recent = _recent_curve(
        client,
        factory=factory,
        token_launched_topic0=token_launched_topic0,
        latest_block=latest,
        lookback_blocks=lookback_blocks,
    )
    if recent is None:
        return {
            "classification": "HOLD_PONS_PROTOCOL_CAPABILITIES_V0_NO_RECENT_CURVE",
            "factory": factory,
            "generation_key": f"pons_v2:{factory.lower()}:unknown_capabilities",
            "recent_curve": None,
            "capabilities": {},
        }

    curve = recent["curve"]
    probes = {}
    simple = {
        "feeBps": "feeBps()",
        "creatorTaxBps": "creatorTaxBps()",
        "getReserves": "getReserves()",
        "sellableTokens": "sellableTokens()",
        "readyToGraduate": "readyToGraduate()",
        "graduated": "graduated()",
    }
    for name, signature in simple.items():
        ok, value, error = _eth_call(client, curve, _selector(client, signature))
        probes[name] = {"supported": ok, "result": value, "error": error}

    recipient = recent["deployer"].lower().removeprefix("0x")
    snipe_data = _selector(client, "currentSnipeTaxBps(address)") + recipient.rjust(64, "0")
    ok, value, error = _eth_call(client, curve, snipe_data)
    probes["currentSnipeTaxBps"] = {"supported": ok, "result": value, "error": error}

    quote_required_views = (
        "feeBps",
        "creatorTaxBps",
        "getReserves",
        "sellableTokens",
        "readyToGraduate",
        "graduated",
    )
    base_ok = all(probes[name]["supported"] for name in quote_required_views)
    snipe_ok = probes["currentSnipeTaxBps"]["supported"]
    if not base_ok:
        classification = "FAIL_PONS_PROTOCOL_CAPABILITIES_V0_CORE_VIEW_MISSING"
        suffix = "core_view_missing"
    elif snipe_ok:
        classification = "PASS_PONS_PROTOCOL_CAPABILITIES_V0_SNIPE_VIEW"
        suffix = "snipe_view"
    else:
        classification = "PASS_PONS_PROTOCOL_CAPABILITIES_V0_BASE_CURVE_NO_SNIPE_VIEW"
        suffix = "base_curve_no_snipe_view"

    return {
        "classification": classification,
        "factory": factory,
        "generation_key": f"pons_v2:{factory.lower()}:{suffix}",
        "recent_curve": recent,
        "capabilities": probes,
        "quote_required_views": list(quote_required_views),
        "quote_state_readable": base_ok,
        "notes": [
            "capability_semantics_are_bound_to_deployed_bytecode_not_repo_assumptions",
            "successful_currentSnipeTaxBps_call_proves_interface_presence_not_nonzero_tax_at_probe_time",
            "readyToGraduate_and_graduated_are_required_for_honest_sell_quotability",
            "exact_fee_model_still_requires_causal_per_launch_state",
        ],
    }
