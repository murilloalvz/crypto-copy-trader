"""Outcome-blind acquisition parity for Robinhood Launch Burst V0.

Compares two normalized ``events.jsonl`` captures (for example JSON-RPC polling
versus a future WebSocket/sequencer adapter).  Local availability clocks are
allowed to differ; chain identity and decoded payload must not.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


_IGNORE_FOR_CHAIN_PAYLOAD = {"observed_at_ns"}


def _load(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _key(row: dict) -> tuple[str, str, int]:
    return (
        str(row.get("kind")),
        str(row.get("transaction_hash") or ""),
        int(row.get("log_index", -1)),
    )


def _chain_payload(row: dict) -> dict:
    return {
        key: value
        for key, value in row.items()
        if key not in _IGNORE_FOR_CHAIN_PAYLOAD
    }


def _percentile(values, q):
    values = sorted(values)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * q
    low = int(pos)
    high = min(low + 1, len(values) - 1)
    fraction = pos - low
    return values[low] * (1 - fraction) + values[high] * fraction


def _summary(values):
    values = [float(value) for value in values]
    return {
        "n": len(values),
        "p50": _percentile(values, 0.5),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "mean": sum(values) / len(values) if values else None,
    }


def compare_event_captures_v0(left_path: Path, right_path: Path) -> dict:
    left_rows = _load(left_path)
    right_rows = _load(right_path)
    left = {_key(row): row for row in left_rows}
    right = {_key(row): row for row in right_rows}
    left_keys = set(left)
    right_keys = set(right)
    common = sorted(left_keys & right_keys)
    only_left = sorted(left_keys - right_keys)
    only_right = sorted(right_keys - left_keys)

    payload_conflicts = []
    latency_delta_ms = []
    for key in common:
        left_row = left[key]
        right_row = right[key]
        if _chain_payload(left_row) != _chain_payload(right_row):
            differing = sorted(
                field
                for field in set(left_row) | set(right_row)
                if field not in _IGNORE_FOR_CHAIN_PAYLOAD
                and left_row.get(field) != right_row.get(field)
            )
            payload_conflicts.append({"key": key, "fields": differing})
        left_clock = int(left_row.get("observed_at_ns") or 0)
        right_clock = int(right_row.get("observed_at_ns") or 0)
        if left_clock > 0 and right_clock > 0:
            latency_delta_ms.append((right_clock - left_clock) / 1_000_000.0)

    union_count = len(left_keys | right_keys)
    common_coverage_pct = 100.0 * len(common) / union_count if union_count else 100.0
    gates = {
        "chain_payload_conflicts_zero": not payload_conflicts,
        "duplicate_keys_left_zero": len(left_rows) == len(left),
        "duplicate_keys_right_zero": len(right_rows) == len(right),
    }
    classification = (
        "PASS_ROBINHOOD_ACQUISITION_CHAIN_PARITY_V0"
        if all(gates.values())
        else "FAIL_ROBINHOOD_ACQUISITION_CHAIN_PARITY_V0"
    )
    return {
        "type": "robinhood_launch_burst_acquisition_parity_v0",
        "classification": classification,
        "feature_only": True,
        "economic_outcomes_opened": False,
        "left_events": len(left_rows),
        "right_events": len(right_rows),
        "common_events": len(common),
        "only_left_count": len(only_left),
        "only_right_count": len(only_right),
        "common_coverage_pct": common_coverage_pct,
        "only_left_sample": only_left[:20],
        "only_right_sample": only_right[:20],
        "payload_conflicts": payload_conflicts[:50],
        "right_minus_left_observed_at_ms": _summary(latency_delta_ms),
        "gates": gates,
        "notes": [
            "positive_latency_delta_means_right_acquisition_observed_the_same_log_later",
            "observed_at_ns_is_intentionally_excluded_from_chain_payload_equality",
            "coverage_is_reported_separately_from_payload_parity",
            "replacement_requires_aligned_shadow_windows_and_explicit_coverage_gate_later",
            "no_economic_outcomes_are_read",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--left-events", required=True)
    parser.add_argument("--right-events", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = compare_event_captures_v0(Path(args.left_events), Path(args.right_events))
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
