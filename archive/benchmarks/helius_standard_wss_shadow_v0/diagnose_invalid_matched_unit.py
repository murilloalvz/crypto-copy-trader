from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

VERSION = "helius_standard_wss_shadow_invalid_matched_unit_diagnostic_v0"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive_int(value: Any) -> bool:
    return _nonnegative_int(value) and value > 0


def _reasons(event: dict[str, Any], result: dict[str, Any]) -> list[str]:
    event_type = event.get("event_type")
    observed_at = result.get("observed_at")
    reasons: list[str] = []

    if not _text(event.get("event_key")):
        reasons.append("event_key_missing")
    if event_type == "pump_trade":
        if not _text(event.get("mint")):
            reasons.append("mint_missing")
        if event.get("side") not in {"buy", "sell"}:
            reasons.append("side_invalid")
        if not _text(event.get("quote_mint")):
            reasons.append("quote_mint_missing")
        if not _positive_int(event.get("quote_amount_raw")):
            reasons.append("quote_amount_nonpositive_or_invalid")
        if not _positive_int(event.get("virtual_quote_reserves_raw")):
            reasons.append("quote_reserve_nonpositive_or_invalid")
    elif event_type in {"pumpswap_buy", "pumpswap_sell"}:
        if not _text(event.get("pool")):
            reasons.append("pool_missing")
        if event.get("side") not in {"buy", "sell"}:
            reasons.append("side_invalid")
        if not _positive_int(event.get("quote_amount_raw")):
            reasons.append("quote_amount_nonpositive_or_invalid")
        if not _positive_int(event.get("pool_quote_token_reserves_raw")):
            reasons.append("quote_reserve_nonpositive_or_invalid")
    else:
        reasons.append("unexpected_event_type")

    timestamp = event.get("timestamp")
    if not _nonnegative_int(timestamp):
        reasons.append("timestamp_invalid")
    elif not _nonnegative_int(observed_at):
        reasons.append("observed_at_invalid")
    elif observed_at < timestamp:
        reasons.append("observed_before_chain_time")

    return reasons or ["unexplained_by_current_adapter_contract"]


def diagnose(*, carbon_output: Path, adapter_output: Path) -> dict[str, Any]:
    events = {
        row["event_key"]: row
        for row in _jsonl(carbon_output)
        if row.get("type") == "carbon_canonical_event" and isinstance(row.get("event_key"), str)
    }
    invalid_rows = [
        row for row in _jsonl(adapter_output)
        if row.get("type") == "helius_standard_wss_shadow_adapter_result"
        and row.get("stage") == "matched_unit_flow"
        and row.get("status") == "INVALID_EVENT"
    ]

    reason_counts: Counter[str] = Counter()
    by_event_type: dict[str, Counter[str]] = defaultdict(Counter)
    examples: list[dict[str, Any]] = []
    missing_carbon = 0
    clock_deltas: list[int] = []

    for result in invalid_rows:
        key = result.get("event_key")
        event = events.get(key)
        if event is None:
            missing_carbon += 1
            continue
        reasons = _reasons(event, result)
        event_type = str(event.get("event_type", "UNKNOWN"))
        for reason in reasons:
            reason_counts[reason] += 1
            by_event_type[event_type][reason] += 1
        timestamp = event.get("timestamp")
        observed_at = result.get("observed_at")
        if _nonnegative_int(timestamp) and _nonnegative_int(observed_at):
            clock_deltas.append(int(observed_at) - int(timestamp))
        if len(examples) < 20:
            examples.append({
                "event_key": key,
                "event_type": event_type,
                "reasons": reasons,
                "timestamp": timestamp,
                "observed_at": observed_at,
                "observed_minus_chain_seconds": (
                    int(observed_at) - int(timestamp)
                    if _nonnegative_int(timestamp) and _nonnegative_int(observed_at)
                    else None
                ),
                "side": event.get("side"),
                "mint": event.get("mint"),
                "pool": event.get("pool"),
                "quote_mint": event.get("quote_mint"),
                "quote_amount_raw": event.get("quote_amount_raw"),
                "virtual_quote_reserves_raw": event.get("virtual_quote_reserves_raw"),
                "pool_quote_token_reserves_raw": event.get("pool_quote_token_reserves_raw"),
            })

    return {
        "type": "helius_standard_wss_shadow_invalid_matched_unit_diagnostic",
        "version": VERSION,
        "invalid_events": len(invalid_rows),
        "missing_carbon_events": missing_carbon,
        "reason_counts": dict(sorted(reason_counts.items())),
        "reason_counts_by_event_type": {
            event_type: dict(sorted(counts.items()))
            for event_type, counts in sorted(by_event_type.items())
        },
        "clock_delta_seconds": {
            "min": min(clock_deltas) if clock_deltas else None,
            "max": max(clock_deltas) if clock_deltas else None,
        },
        "examples": examples,
        "valid_diagnostic": len(invalid_rows) > 0 and missing_carbon == 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose matched-unit INVALID_EVENT rows")
    parser.add_argument("--carbon-output", type=Path, required=True)
    parser.add_argument("--adapter-output", type=Path, required=True)
    args = parser.parse_args()
    report = diagnose(carbon_output=args.carbon_output, adapter_output=args.adapter_output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid_diagnostic"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
