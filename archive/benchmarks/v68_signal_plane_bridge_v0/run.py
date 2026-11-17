from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import tempfile

from benchmarks.commodity_signal_plane_v0.benchmark import (
    generate_synthetic_trace,
    load_trace,
)
from benchmarks.integrated_market_signal_plane_v1.indexed_kernel import (
    IndexedWindowRadarState,
)
from benchmarks.integrated_market_signal_plane_v1.rust_suite import (
    _json_equivalent,
    _run_rust,
)
from benchmarks.integrated_market_signal_plane_v1.suite import _trigger_snapshot
from src.signal_plane_episode_bridge_v0 import (
    SIGNAL_PLANE_EPISODE_BRIDGE_VERSION,
    build_signal_plane_episode_assignment,
    market_movement_trigger_from_snapshot,
)


VERSION = "v68_signal_plane_bridge_v0"
PASS_CLASSIFICATION = "PASS_V68_SIGNAL_PLANE_BRIDGE_V0"
FAIL_CLASSIFICATION = "FAIL_V68_SIGNAL_PLANE_BRIDGE_V0"


def run_bridge_audit(
    *,
    events: int,
    seed: int,
    cargo: str = "cargo",
) -> dict:
    if events <= 0:
        raise ValueError("events must be positive")

    rust_manifest = (
        Path("benchmarks")
        / "integrated_market_signal_plane_v1"
        / "rust_runner"
        / "Cargo.toml"
    )

    with tempfile.TemporaryDirectory(prefix="v68-signal-bridge-v0-") as directory:
        root = Path(directory)
        trace_path = root / "trace.jsonl"
        rust_output = root / "rust-report.json"

        generate_synthetic_trace(
            out=trace_path,
            events=events,
            seed=seed,
        )
        _, records = load_trace(trace_path)
        rust_report = _run_rust(
            cargo=cargo,
            manifest=rust_manifest,
            trace=trace_path,
            output=rust_output,
        )

    rust_decisions = {
        int(item["sequence"]): item.get("trigger")
        for item in rust_report.get("decisions", [])
    }

    python = IndexedWindowRadarState()
    parity_mismatches: list[dict] = []
    bridge_failures: list[dict] = []
    bridged = 0
    bridged_pump = 0
    bridged_pumpswap = 0
    trigger_count = 0

    for record in records:
        py_trigger = python.ingest(record)
        if record.kind != "trade":
            continue

        expected = _trigger_snapshot(py_trigger)
        actual = rust_decisions.get(record.sequence)
        if not _json_equivalent(expected, actual):
            if len(parity_mismatches) < 20:
                parity_mismatches.append(
                    {
                        "sequence": record.sequence,
                        "python": expected,
                        "rust": actual,
                    }
                )
            continue

        if actual is None:
            continue
        trigger_count += 1
        if record.trade is None:
            bridge_failures.append(
                {
                    "sequence": record.sequence,
                    "error": "trigger_without_trade_record",
                }
            )
            continue

        try:
            trigger = market_movement_trigger_from_snapshot(actual)
            assignment = build_signal_plane_episode_assignment(
                trigger=trigger,
                observation=record.trade,
            )
        except Exception as exc:
            if len(bridge_failures) < 20:
                bridge_failures.append(
                    {
                        "sequence": record.sequence,
                        "error": f"{type(exc).__name__}:{exc}",
                        "trade": asdict(record.trade),
                        "trigger": actual,
                    }
                )
            continue

        if assignment.observed_at != record.trade.observed_at:
            bridge_failures.append(
                {
                    "sequence": record.sequence,
                    "error": "observed_at_changed",
                }
            )
            continue
        if assignment.chain_time != record.trade.chain_time:
            bridge_failures.append(
                {
                    "sequence": record.sequence,
                    "error": "chain_time_changed",
                }
            )
            continue
        if assignment.trigger_kind != trigger.trigger_kind:
            bridge_failures.append(
                {
                    "sequence": record.sequence,
                    "error": "trigger_kind_changed",
                }
            )
            continue
        if assignment.direction != trigger.direction:
            bridge_failures.append(
                {
                    "sequence": record.sequence,
                    "error": "direction_changed",
                }
            )
            continue

        bridged += 1
        if assignment.venue == "pump_bonding_curve":
            bridged_pump += 1
            expected_key = (
                f"market-radar:pump:{record.trade.transaction_key}:"
                f"{record.trade.token_mint}"
            )
        elif assignment.venue == "pump_swap":
            bridged_pumpswap += 1
            expected_key = (
                f"market-radar:pumpswap-v3:{record.trade.transaction_key}:"
                f"{record.trade.token_mint}"
            )
        else:
            bridge_failures.append(
                {
                    "sequence": record.sequence,
                    "error": f"unexpected_venue:{assignment.venue}",
                }
            )
            continue
        if assignment.trigger_key != expected_key:
            bridge_failures.append(
                {
                    "sequence": record.sequence,
                    "error": "historical_trigger_key_changed",
                    "expected": expected_key,
                    "actual": assignment.trigger_key,
                }
            )

    rust_trade_points = len(rust_decisions)
    parity_exact = rust_trade_points - len(parity_mismatches)
    parity_pct = (
        100.0
        if rust_trade_points == 0
        else 100.0 * parity_exact / rust_trade_points
    )

    checks = {
        "rust_python_trigger_parity_100": (
            rust_trade_points > 0
            and not parity_mismatches
            and parity_pct == 100.0
        ),
        "at_least_one_trigger_exercised": trigger_count > 0,
        "all_triggered_trades_bridge": bridged == trigger_count,
        "pump_bridge_exercised": bridged_pump > 0,
        "pumpswap_bridge_exercised": bridged_pumpswap > 0,
        "bridge_failures_zero": not bridge_failures,
        "bridge_version_frozen": (
            SIGNAL_PLANE_EPISODE_BRIDGE_VERSION
            == "signal_plane_episode_bridge_v0"
        ),
    }

    classification = (
        PASS_CLASSIFICATION if all(checks.values()) else FAIL_CLASSIFICATION
    )
    return {
        "type": "v68_signal_plane_bridge_report",
        "version": VERSION,
        "classification": classification,
        "authorization": "systems_bridge_only_no_v68_fresh_no_economic_verdict",
        "events_requested": events,
        "seed": seed,
        "record_count": len(records),
        "rust_trade_decision_points": rust_trade_points,
        "rust_python_parity": {
            "exact_matches": parity_exact,
            "mismatches": len(parity_mismatches),
            "parity_pct": parity_pct,
            "first_mismatches": parity_mismatches,
        },
        "episode_bridge": {
            "trigger_count": trigger_count,
            "bridged": bridged,
            "pump": bridged_pump,
            "pumpswap": bridged_pumpswap,
            "failures": len(bridge_failures),
            "first_failures": bridge_failures,
            "bridge_version": SIGNAL_PLANE_EPISODE_BRIDGE_VERSION,
        },
        "checks": checks,
        "scientific_thresholds_modified": False,
        "economic_hypothesis_modified": False,
        "interpretation": (
            "PASS proves offline that Rust trigger semantics map into the same durable "
            "Pump/PumpSwap episode identity contract used by the frozen historical bridges. "
            "It does not prove live sustained capacity and does not authorize V68."
            if classification == PASS_CLASSIFICATION
            else "Bridge promotion is blocked until every offline semantic check passes."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Offline Rust -> frozen episode-identity bridge audit for the V68 migration seam."
        )
    )
    parser.add_argument("--events", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=68)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "artifacts/v68_signal_plane_bridge_v0/report.json"
        ),
    )
    args = parser.parse_args()

    report = run_bridge_audit(
        events=args.events,
        seed=args.seed,
        cargo=args.cargo,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["classification"] == PASS_CLASSIFICATION else 1


if __name__ == "__main__":
    raise SystemExit(main())
