"""Compact report summarizer for Robinhood Launch Burst V0."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarks.robinhood_launch_burst_v0.audit import audit_run
from benchmarks.robinhood_launch_burst_v0.fee_dynamics import build_fee_report_v0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="artifacts/robinhood_launch_burst_v0")
    args = parser.parse_args()
    root = Path(args.root)
    runs = sorted(
        (directory for directory in root.iterdir() if directory.is_dir()),
        key=lambda directory: directory.stat().st_mtime,
        reverse=True,
    )
    if not runs:
        raise SystemExit("no Robinhood Launch Burst V0 runs found")

    run = runs[0]
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    audit = audit_run(run)
    fee_report = build_fee_report_v0(run)
    discovery = report.get("factory_discovery") or {}

    output = {
        "run": run.name,
        "classification": report.get("classification"),
        "stop_reason": report.get("stop_reason"),
        "chain_id": report.get("chain_id"),
        "factory": report.get("factory"),
        "factory_selection_reason": discovery.get("selection_reason"),
        "factory_probes": discovery.get("probes"),
        "counts": report.get("counts"),
        "poll_latency_ms": report.get("poll_latency_ms"),
        "feature_report_native_eth": report.get("feature_report_native_eth"),
        "opening_fee_dynamics_native_eth": fee_report.get("feature_report_native_eth"),
        "capture_audit": {
            "classification": audit.get("classification"),
            "launches": audit.get("launches"),
            "native_eth_launches": audit.get("native_eth_launches"),
            "trades": audit.get("trades"),
            "snapshots": audit.get("snapshots"),
            "expected_matured_snapshots": audit.get("expected_matured_snapshots"),
            "exact_event_duplicates": audit.get("exact_event_duplicates"),
            "block_hash_conflicts": len(audit.get("block_hash_conflicts") or []),
            "missing_matured_snapshots": len(audit.get("missing_matured_snapshots") or []),
            "replay_mismatches": len(audit.get("replay_mismatches") or []),
            "causal_clock_violations": len(audit.get("causal_clock_violations") or []),
            "gates": audit.get("gates"),
        },
        "transport_errors": report.get("transport_errors"),
        "gates": report.get("gates"),
        "economic_outcomes_opened": report.get("economic_outcomes_opened"),
        "selector_frozen": report.get("selector_frozen"),
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
