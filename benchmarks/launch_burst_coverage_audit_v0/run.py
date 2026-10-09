from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Iterable

from benchmarks.launch_burst_replay_v0.run import run_replay
from benchmarks.launch_burst_run_inventory_v0.run import (
    select_latest_closed_launch_run_key,
)


COVERAGE_AUDIT_VERSION = "launch_burst_coverage_audit_v0_outcome_blind"


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return 100.0 * numerator / denominator


def _percentile(values: Iterable[int | float], fraction: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be between 0 and 1")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _distribution(values: Iterable[int | float]) -> dict:
    ordered = [float(value) for value in values]
    return {
        "count": len(ordered),
        "min": min(ordered) if ordered else None,
        "p50": _percentile(ordered, 0.50),
        "p90": _percentile(ordered, 0.90),
        "p95": _percentile(ordered, 0.95),
        "max": max(ordered) if ordered else None,
    }


def _coverage_dimension(snapshots: list[dict], field: str) -> dict:
    nonempty = [item for item in snapshots if int(item["event_count"]) > 0]
    values = [item.get(field) for item in nonempty]
    any_known = sum(value is not None and float(value) > 0.0 for value in values)
    complete = sum(value is not None and float(value) == 100.0 for value in values)
    absent = sum(value is None or float(value) == 0.0 for value in values)
    return {
        "nonempty_snapshot_count": len(nonempty),
        "any_known_count": any_known,
        "any_known_pct": _pct(any_known, len(nonempty)),
        "complete_count": complete,
        "complete_pct": _pct(complete, len(nonempty)),
        "absent_count": absent,
        "absent_pct": _pct(absent, len(nonempty)),
    }


def _readiness(dimension: dict) -> str:
    total = int(dimension["nonempty_snapshot_count"])
    if total == 0:
        return "NO_NONEMPTY_SAMPLE"
    if int(dimension["any_known_count"]) == 0:
        return "ABSENT_IN_AUDITED_SAMPLE"
    if int(dimension["complete_count"]) == total:
        return "COMPLETE_IN_AUDITED_SAMPLE"
    return "PARTIAL_IN_AUDITED_SAMPLE"


def _group_summary(snapshots: list[dict]) -> dict:
    nonempty = [item for item in snapshots if int(item["event_count"]) > 0]
    return {
        "snapshot_count": len(snapshots),
        "nonempty_snapshot_count": len(nonempty),
        "nonempty_snapshot_pct": _pct(len(nonempty), len(snapshots)),
        "zero_event_snapshot_count": len(snapshots) - len(nonempty),
        "event_count_distribution": _distribution(
            int(item["event_count"]) for item in snapshots
        ),
        "first_trade_chain_delay_seconds": _distribution(
            item["first_trade_chain_delay_seconds"]
            for item in nonempty
            if item.get("first_trade_chain_delay_seconds") is not None
        ),
        "first_trade_observed_delay_seconds": _distribution(
            item["first_trade_observed_delay_seconds"]
            for item in nonempty
            if item.get("first_trade_observed_delay_seconds") is not None
        ),
    }


def run_coverage_audit(*, acquisition_run_key: str, window_seconds: int = 30) -> dict:
    """Measure Launch Burst input availability without reporting economic outcomes.

    The underlying replay builds causal feature snapshots, but this audit deliberately does
    not expose price returns, notional magnitudes, buy-share values, or any future outcome.
    It reports only sample/censoring counts, timing availability, identity coverage, and
    whether feature families are present enough to justify a later preregistration step.
    """

    replay = run_replay(
        acquisition_run_key=acquisition_run_key,
        window_seconds=window_seconds,
    )
    snapshots = list(replay["snapshots"])
    nonempty = [item for item in snapshots if int(item["event_count"]) > 0]

    wallet = _coverage_dimension(snapshots, "wallet_identity_coverage_pct")
    transactions = _coverage_dimension(snapshots, "transaction_identity_coverage_pct")
    notional = _coverage_dimension(snapshots, "notional_coverage_pct")
    price = _coverage_dimension(snapshots, "price_coverage_pct")

    quality_flags = Counter(
        flag
        for item in snapshots
        for flag in item.get("data_quality_flags", ())
    )
    strata = {
        stratum: _group_summary(
            [item for item in snapshots if item["stratum"] == stratum]
        )
        for stratum in sorted({str(item["stratum"]) for item in snapshots})
    }

    return {
        "type": "launch_burst_coverage_audit",
        "version": COVERAGE_AUDIT_VERSION,
        "acquisition_run_key": acquisition_run_key,
        "observation_window_seconds": window_seconds,
        "sample": {
            "causal_anchor_count": int(replay["causal_anchor_count"]),
            "complete_snapshot_count": len(snapshots),
            "right_censored_count": int(replay["right_censored_count"]),
            "unsupported_venue_count": int(replay["unsupported_venue_count"]),
            "late_earlier_lifecycle_audit_count": int(
                replay["late_earlier_lifecycle_audit_count"]
            ),
            "nonempty_snapshot_count": len(nonempty),
            "nonempty_snapshot_pct": _pct(len(nonempty), len(snapshots)),
            "zero_event_snapshot_count": len(snapshots) - len(nonempty),
        },
        "strata": strata,
        "event_count_distribution": _distribution(
            int(item["event_count"]) for item in snapshots
        ),
        "first_trade_chain_delay_seconds": _distribution(
            item["first_trade_chain_delay_seconds"]
            for item in nonempty
            if item.get("first_trade_chain_delay_seconds") is not None
        ),
        "first_trade_observed_delay_seconds": _distribution(
            item["first_trade_observed_delay_seconds"]
            for item in nonempty
            if item.get("first_trade_observed_delay_seconds") is not None
        ),
        "feature_coverage": {
            "wallet_identity": wallet,
            "transaction_identity": transactions,
            "notional": notional,
            "price": price,
        },
        "feature_readiness": {
            "event_count": "MEASURABLE",
            "buy_sell_count": "MEASURABLE_WHEN_NONEMPTY",
            "wallet_breadth": _readiness(wallet),
            "transaction_breadth": _readiness(transactions),
            "notional": _readiness(notional),
            "price": _readiness(price),
        },
        "data_quality_flag_counts": dict(sorted(quality_flags.items())),
        "scientific_lock": {
            "feature_window_seconds": window_seconds,
            "candidate_filters": [],
            "economic_thresholds_defined": False,
            "outcome_horizons_frozen": False,
            "future_outcomes_loaded": False,
            "future_outcome_values_reported": False,
            "within_window_return_values_reported": False,
            "notional_magnitudes_reported": False,
            "buy_share_values_reported": False,
            "coverage_only": True,
        },
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Outcome-blind Launch Burst feature coverage audit v0"
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--run-key")
    selection.add_argument(
        "--latest-closed",
        action="store_true",
        help=(
            "Use only the newest authoritative CLOSED Market Activity Discovery run "
            "that has persisted lifecycle evidence."
        ),
    )
    parser.add_argument("--window-seconds", type=int, default=30)
    parser.add_argument(
        "--output",
        default="artifacts/launch_burst_coverage_audit_v0/report.json",
    )
    args = parser.parse_args()
    if args.window_seconds <= 0:
        parser.error("--window-seconds must be positive")

    run_key = (
        select_latest_closed_launch_run_key()
        if args.latest_closed
        else str(args.run_key)
    )
    report = run_coverage_audit(
        acquisition_run_key=run_key,
        window_seconds=args.window_seconds,
    )
    output = Path(args.output)
    _write_json(output, report)
    print(
        "Launch Burst Coverage Audit V0 "
        f"run={run_key} complete={report['sample']['complete_snapshot_count']} "
        f"nonempty={report['sample']['nonempty_snapshot_count']} "
        f"censored={report['sample']['right_censored_count']}"
    )
    print(f"feature_readiness={report['feature_readiness']}")
    print(f"output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
