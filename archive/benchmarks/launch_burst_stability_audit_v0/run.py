from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from benchmarks.launch_burst_replay_v0.run import run_replay


STABILITY_AUDIT_VERSION = "launch_burst_stability_audit_v0_outcome_blind"
DEFAULT_WINDOWS_SECONDS = (5, 10, 30, 60)
FEATURES = (
    "event_count",
    "buy_count",
    "sell_count",
    "count_buy_share_pct",
    "unique_wallet_count",
    "unique_transaction_count",
    "event_rate_per_second",
    "net_buy_imbalance_pct",
    "wallets_per_event",
    "transactions_per_event",
)


def _pct(numerator: int | float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return 100.0 * float(numerator) / float(denominator)


def _percentile(values: Iterable[float], fraction: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _distribution(values: Iterable[float | int | None]) -> dict[str, float | int | None]:
    numeric = [float(value) for value in values if value is not None]
    return {
        "count": len(numeric),
        "min": min(numeric) if numeric else None,
        "p25": _percentile(numeric, 0.25),
        "p50": _percentile(numeric, 0.50),
        "p75": _percentile(numeric, 0.75),
        "p90": _percentile(numeric, 0.90),
        "max": max(numeric) if numeric else None,
    }


def _feature_value(snapshot: dict[str, Any], feature: str, *, window_seconds: int) -> float | int | None:
    events = int(snapshot.get("event_count") or 0)
    buys = int(snapshot.get("buy_count") or 0)
    sells = int(snapshot.get("sell_count") or 0)
    if feature in {
        "event_count",
        "buy_count",
        "sell_count",
        "count_buy_share_pct",
        "unique_wallet_count",
        "unique_transaction_count",
    }:
        return snapshot.get(feature)
    if feature == "event_rate_per_second":
        return events / float(window_seconds)
    if feature == "net_buy_imbalance_pct":
        return 100.0 * (buys - sells) / events if events > 0 else None
    if feature == "wallets_per_event":
        return float(snapshot.get("unique_wallet_count") or 0) / events if events > 0 else None
    if feature == "transactions_per_event":
        return float(snapshot.get("unique_transaction_count") or 0) / events if events > 0 else None
    raise KeyError(feature)


def _stratum_summary(snapshots: list[dict[str, Any]], *, window_seconds: int) -> dict[str, Any]:
    nonempty = [item for item in snapshots if int(item.get("event_count") or 0) > 0]
    return {
        "snapshot_count": len(snapshots),
        "nonempty_snapshot_count": len(nonempty),
        "nonempty_snapshot_pct": _pct(len(nonempty), len(snapshots)),
        "features": {
            feature: _distribution(
                _feature_value(item, feature, window_seconds=window_seconds)
                for item in nonempty
            )
            for feature in FEATURES
        },
    }


def _comparison(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    p50_a = a.get("p50")
    p50_b = b.get("p50")
    if p50_a is None or p50_b is None:
        return {
            "p50_a": p50_a,
            "p50_b": p50_b,
            "absolute_gap": None,
            "b_over_a_ratio": None,
        }
    denom = abs(float(p50_a))
    return {
        "p50_a": float(p50_a),
        "p50_b": float(p50_b),
        "absolute_gap": abs(float(p50_b) - float(p50_a)),
        "b_over_a_ratio": (float(p50_b) / float(p50_a)) if denom > 1e-12 else None,
    }


def run_stability_audit(*, run_a: str, run_b: str, windows_seconds: tuple[int, ...]) -> dict[str, Any]:
    if not run_a.strip() or not run_b.strip():
        raise ValueError("run_a and run_b are required")
    if not windows_seconds or any(int(item) <= 0 for item in windows_seconds):
        raise ValueError("windows_seconds must contain positive values")

    cohorts: dict[str, dict[str, Any]] = {}
    for label, run_key in (("A", run_a), ("B", run_b)):
        cohort_windows: dict[str, Any] = {}
        for window in windows_seconds:
            replay = run_replay(acquisition_run_key=run_key, window_seconds=int(window))
            snapshots = list(replay["snapshots"])
            strata = sorted({str(item["stratum"]) for item in snapshots})
            anchors = int(replay["causal_anchor_count"])
            censored = int(replay["right_censored_count"])
            cohort_windows[str(window)] = {
                "sample": {
                    "causal_anchor_count": anchors,
                    "complete_snapshot_count": int(replay["snapshot_count"]),
                    "right_censored_count": censored,
                    "censoring_pct": _pct(censored, anchors),
                    "unsupported_venue_count": int(replay["unsupported_venue_count"]),
                },
                "strata": {
                    stratum: _stratum_summary(
                        [item for item in snapshots if item["stratum"] == stratum],
                        window_seconds=int(window),
                    )
                    for stratum in strata
                },
            }
        cohorts[label] = {
            "acquisition_run_key": run_key,
            "windows": cohort_windows,
        }

    comparisons: dict[str, Any] = {}
    for window in windows_seconds:
        key = str(window)
        a_strata = cohorts["A"]["windows"][key]["strata"]
        b_strata = cohorts["B"]["windows"][key]["strata"]
        shared_strata = sorted(set(a_strata) & set(b_strata))
        comparisons[key] = {}
        for stratum in shared_strata:
            comparisons[key][stratum] = {
                "nonempty_snapshot_pct_gap_pp": (
                    None
                    if a_strata[stratum]["nonempty_snapshot_pct"] is None
                    or b_strata[stratum]["nonempty_snapshot_pct"] is None
                    else abs(
                        float(a_strata[stratum]["nonempty_snapshot_pct"])
                        - float(b_strata[stratum]["nonempty_snapshot_pct"])
                    )
                ),
                "features": {
                    feature: _comparison(
                        a_strata[stratum]["features"][feature],
                        b_strata[stratum]["features"][feature],
                    )
                    for feature in FEATURES
                },
            }

    return {
        "type": "launch_burst_stability_audit",
        "version": STABILITY_AUDIT_VERSION,
        "windows_seconds": list(windows_seconds),
        "cohorts": cohorts,
        "comparisons": comparisons,
        "scientific_lock": {
            "outcome_blind": True,
            "future_outcomes_loaded": False,
            "economic_thresholds_defined": False,
            "feature_thresholds_selected": False,
            "pnl_reported": False,
            "price_or_notional_required": False,
            "diagnostic_only": True,
        },
        "known_limitations": [
            "DB-shadow timestamps are integer seconds; sub-second launch timing is not identifiable",
            "price/notional are absent in this audited V68 sample",
            "PumpSwap sample support is insufficient for A/B stability inference when a stratum is absent",
            "censoring rises with longer windows and must be inspected before using a horizon",
        ],
    }


def _parse_windows(value: str) -> tuple[int, ...]:
    result = tuple(sorted({int(item.strip()) for item in value.split(",") if item.strip()}))
    if not result or any(item <= 0 for item in result):
        raise argparse.ArgumentTypeError("windows must be positive comma-separated integers")
    return result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Outcome-blind Launch Burst A/B stability audit v0")
    parser.add_argument("--run-a", required=True)
    parser.add_argument("--run-b", required=True)
    parser.add_argument("--windows", type=_parse_windows, default=DEFAULT_WINDOWS_SECONDS)
    parser.add_argument(
        "--output",
        default="artifacts/launch_burst_stability_audit_v0/report.json",
    )
    args = parser.parse_args()
    report = run_stability_audit(
        run_a=args.run_a,
        run_b=args.run_b,
        windows_seconds=tuple(args.windows),
    )
    output = Path(args.output)
    _write_json(output, report)
    print(
        "Launch Burst Stability Audit V0 "
        f"A={args.run_a} B={args.run_b} windows={list(args.windows)}"
    )
    print(f"output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
