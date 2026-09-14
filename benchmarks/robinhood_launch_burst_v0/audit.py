"""Post-capture integrity audit for Robinhood/Pons Launch Burst V0.

This audit is intentionally outcome-blind.  It replays every frozen feature
snapshot from normalized raw launch/trade observations and checks causal clocks,
identity consistency, duplicate snapshots and maturity completeness.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from src.robinhood_pons_launch_burst_v0 import (
    WINDOWS_SECONDS,
    PonsLaunchObservationV0,
    PonsTradeObservationV0,
    build_snapshot_v0,
)


def _json_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path.name}:{number} is not an object")
        rows.append(row)
    return rows


def _normalize_json(value):
    return json.loads(json.dumps(value, sort_keys=True))


def audit_run(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    report_path = run_dir / "report.json"
    if not report_path.exists():
        raise FileNotFoundError(report_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    events = _json_lines(run_dir / "events.jsonl")
    snapshots = _json_lines(run_dir / "snapshots.jsonl")

    launches: dict[str, PonsLaunchObservationV0] = {}
    trades_by_curve: dict[str, list[PonsTradeObservationV0]] = defaultdict(list)
    event_identity: dict[tuple[str, int], str] = {}
    exact_event_duplicates = 0
    block_hash_conflicts = []
    invalid_event_rows = []

    for index, row in enumerate(events):
        try:
            kind = row.get("kind")
            data = {key: value for key, value in row.items() if key != "kind"}
            if kind == "launch":
                observation = PonsLaunchObservationV0(**data)
                launches[observation.curve] = observation
            elif kind == "trade":
                observation = PonsTradeObservationV0(**data)
                trades_by_curve[observation.curve].append(observation)
            else:
                raise ValueError(f"unsupported kind {kind!r}")

            identity = (observation.transaction_hash, observation.log_index)
            previous_hash = event_identity.get(identity)
            if previous_hash is None:
                event_identity[identity] = observation.block_hash
            elif previous_hash == observation.block_hash:
                exact_event_duplicates += 1
            else:
                block_hash_conflicts.append(
                    {
                        "transaction_hash": observation.transaction_hash,
                        "log_index": observation.log_index,
                        "first_block_hash": previous_hash,
                        "conflicting_block_hash": observation.block_hash,
                    }
                )
        except Exception as exc:
            invalid_event_rows.append({"index": index, "error": f"{type(exc).__name__}:{exc}"})

    snapshot_keys = []
    duplicate_snapshot_keys = []
    seen_snapshot_keys = set()
    replay_mismatches = []
    causal_clock_violations = []

    for index, row in enumerate(snapshots):
        key = (str(row.get("curve", "")).lower(), int(row.get("horizon_seconds", -1)))
        snapshot_keys.append(key)
        if key in seen_snapshot_keys:
            duplicate_snapshot_keys.append(key)
        seen_snapshot_keys.add(key)

        launch = launches.get(key[0])
        if launch is None:
            replay_mismatches.append({"index": index, "key": key, "reason": "MISSING_LAUNCH"})
            continue
        cutoff = launch.observed_at_ns + key[1] * 1_000_000_000
        snapshot_clock = int(row.get("snapshot_observed_at_ns", -1))
        if snapshot_clock < cutoff:
            causal_clock_violations.append(
                {"index": index, "key": key, "snapshot_observed_at_ns": snapshot_clock, "cutoff": cutoff}
            )
            continue
        try:
            expected = build_snapshot_v0(
                launch=launch,
                trades=trades_by_curve.get(launch.curve, ()),
                horizon_seconds=key[1],
                snapshot_observed_at_ns=snapshot_clock,
            ).to_dict()
            if _normalize_json(expected) != _normalize_json(row):
                differing = sorted(
                    field
                    for field in set(expected) | set(row)
                    if _normalize_json(expected.get(field)) != _normalize_json(row.get(field))
                )
                replay_mismatches.append(
                    {"index": index, "key": key, "reason": "FEATURE_REPLAY_MISMATCH", "fields": differing}
                )
        except Exception as exc:
            replay_mismatches.append(
                {"index": index, "key": key, "reason": f"{type(exc).__name__}:{exc}"}
            )

    finished_ns = int(report.get("finished_wall_ns") or 0)
    expected_matured = set()
    for launch in launches.values():
        for horizon in WINDOWS_SECONDS:
            if launch.observed_at_ns + horizon * 1_000_000_000 <= finished_ns:
                expected_matured.add((launch.curve, horizon))
    actual = set(snapshot_keys)
    missing_matured = sorted(expected_matured - actual)
    unexpected = sorted(actual - expected_matured)

    discovery = report.get("factory_discovery") or {}
    gates = {
        "feature_only": report.get("feature_only") is True,
        "economic_outcomes_closed": report.get("economic_outcomes_opened") is False,
        "selector_unfrozen": report.get("selector_frozen") is False,
        "transport_errors_zero": not report.get("transport_errors"),
        "factory_discovery_pass": str(discovery.get("classification", "")).startswith("PASS"),
        "invalid_event_rows_zero": not invalid_event_rows,
        "block_hash_conflicts_zero": not block_hash_conflicts,
        "duplicate_snapshot_keys_zero": not duplicate_snapshot_keys,
        "matured_snapshots_complete": not missing_matured,
        "feature_replay_exact": not replay_mismatches,
        "snapshot_clocks_causal": not causal_clock_violations,
    }
    native_count = sum(launch.is_native_eth_quote for launch in launches.values())
    if all(gates.values()) and native_count > 0:
        classification = "PASS_ROBINHOOD_LAUNCH_BURST_CAPTURE_AUDIT_V0"
    elif all(gates.values()):
        classification = "HOLD_ROBINHOOD_LAUNCH_BURST_CAPTURE_AUDIT_V0_NO_NATIVE_DATA"
    else:
        classification = "FAIL_ROBINHOOD_LAUNCH_BURST_CAPTURE_AUDIT_V0"

    return {
        "type": "robinhood_pons_launch_burst_capture_audit_v0",
        "classification": classification,
        "run_dir": str(run_dir),
        "feature_only": True,
        "economic_outcomes_opened": False,
        "launches": len(launches),
        "native_eth_launches": native_count,
        "trades": sum(len(rows) for rows in trades_by_curve.values()),
        "snapshots": len(snapshots),
        "expected_matured_snapshots": len(expected_matured),
        "exact_event_duplicates": exact_event_duplicates,
        "block_hash_conflicts": block_hash_conflicts,
        "invalid_event_rows": invalid_event_rows,
        "duplicate_snapshot_keys": duplicate_snapshot_keys,
        "missing_matured_snapshots": missing_matured,
        "unexpected_snapshots": unexpected,
        "replay_mismatches": replay_mismatches,
        "causal_clock_violations": causal_clock_violations,
        "gates": gates,
        "notes": [
            "no_economic_outcomes_read_or_opened",
            "feature_snapshots_rebuilt_from_normalized_events",
            "trailing_unmatured_launches_are_not_counted_as_missing_snapshots",
            "block_hash_conflict_is_treated_as_reorg_or_provider_identity_failure",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = audit_run(Path(args.run_dir))
    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
