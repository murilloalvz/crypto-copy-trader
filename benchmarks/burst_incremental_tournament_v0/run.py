from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from benchmarks.burst_selection_diagnostic_v0.run import (
    _finite_number,
    _metrics_dict,
    _scope_rows,
    tercile_cutpoints,
)
from src.route_research_early_opportunity_v55 import (
    build_early_opportunity_dataset_v55,
)


VERSION = "burst_incremental_tournament_v0"
CLASSIFICATION = "DIAGNOSTIC_ONLY_NO_FRESH_VERDICT"
PRIMARY_HORIZON_SECONDS = 900
HORIZONS_SECONDS = (300, 900, 3600)
CATASTROPHIC_RETURN_PCT = -80.0

REPETITION_FEATURE = "flow30_repeated_wallet_event_share_pct"
IMPACT_FEATURE = "entry_price_impact_pct_points"


def _tail_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return (
        100.0
        * sum(value <= CATASTROPHIC_RETURN_PCT for value in values)
        / len(values)
    )


def _safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return "INF" if value > 0 else "-INF"
    return value


def _row_repetition(row) -> float | None:
    return _finite_number(row.features.get(REPETITION_FEATURE))


def _row_impact_closeness(row) -> float | None:
    signed = _finite_number(row.features.get(IMPACT_FEATURE))
    return -abs(signed) if signed is not None else None


def _cutpoints(rows) -> dict[str, float]:
    repetition = [
        value
        for row in rows
        if (value := _row_repetition(row)) is not None
    ]
    impact = [
        value
        for row in rows
        if (value := _row_impact_closeness(row)) is not None
    ]
    if not repetition or not impact:
        raise ValueError("tournament requires repetition and price-impact coverage")
    rep_low, rep_high = tercile_cutpoints(repetition)
    imp_low, imp_high = tercile_cutpoints(impact)
    return {
        "repetition_low_max": rep_low,
        "repetition_mid_max": rep_high,
        "impact_closeness_low_max": imp_low,
        "impact_closeness_mid_max": imp_high,
    }


def _take(row, variant: str, cutpoints: dict[str, float]) -> bool:
    repetition = _row_repetition(row)
    impact = _row_impact_closeness(row)

    if variant == "BURST_BASELINE":
        return True

    if variant == "LOW_REPETITION":
        return (
            repetition is not None
            and repetition <= cutpoints["repetition_low_max"]
        )

    if variant == "IMPACT_CLOSE_TO_ZERO":
        return (
            impact is not None
            and impact > cutpoints["impact_closeness_mid_max"]
        )

    if variant == "LOW_REPETITION_AND_IMPACT_CLOSE":
        return (
            repetition is not None
            and impact is not None
            and repetition <= cutpoints["repetition_low_max"]
            and impact > cutpoints["impact_closeness_mid_max"]
        )

    raise ValueError(f"unknown variant: {variant}")


def _variant_metrics(rows, variant: str, cutpoints: dict[str, float], horizon: int):
    selected = [row for row in rows if _take(row, variant, cutpoints)]
    values = [
        float(row.labels[horizon])
        for row in selected
        if _finite_number(row.labels.get(horizon)) is not None
    ]
    metrics = _metrics_dict(values)
    return {
        **metrics,
        "selected_rows": len(selected),
        "available_outcomes": len(values),
        "take_rate_pct": (
            100.0 * len(selected) / len(rows) if rows else None
        ),
        "catastrophic_loss_count": sum(
            value <= CATASTROPHIC_RETURN_PCT for value in values
        ),
        "catastrophic_loss_rate_pct": _tail_rate(values),
    }


def _variant_overlap(rows, cutpoints: dict[str, float]) -> dict[str, int]:
    rep = {
        (row.acquisition_run_key, row.episode_key)
        for row in rows
        if _take(row, "LOW_REPETITION", cutpoints)
    }
    imp = {
        (row.acquisition_run_key, row.episode_key)
        for row in rows
        if _take(row, "IMPACT_CLOSE_TO_ZERO", cutpoints)
    }
    return {
        "low_repetition_rows": len(rep),
        "impact_close_rows": len(imp),
        "intersection_rows": len(rep & imp),
        "union_rows": len(rep | imp),
    }


def build_report(run_keys: tuple[str, str]) -> dict[str, Any]:
    dataset = build_early_opportunity_dataset_v55(
        acquisition_run_keys=run_keys
    )
    rows = dataset.rows
    cutpoints = _cutpoints(rows)

    variants = (
        "BURST_BASELINE",
        "LOW_REPETITION",
        "IMPACT_CLOSE_TO_ZERO",
        "LOW_REPETITION_AND_IMPACT_CLOSE",
    )

    results: dict[str, Any] = {}
    for horizon in HORIZONS_SECONDS:
        results[str(horizon)] = {}
        for scope in ("A", "B", "ALL"):
            scoped = _scope_rows(rows, scope)
            results[str(horizon)][scope] = {
                variant: _variant_metrics(
                    scoped,
                    variant,
                    cutpoints,
                    horizon,
                )
                for variant in variants
            }

    return {
        "type": "burst_incremental_tournament_report",
        "version": VERSION,
        "classification": CLASSIFICATION,
        "authorization": (
            "read_only_discovery_on_consumed_v68_03_no_selector_no_new_fresh"
        ),
        "run_keys": list(run_keys),
        "rows_total": len(rows),
        "dataset_quality": {
            "lineage_violations": dataset.base.lineage_violations,
            "augmentation_failures": dataset.augmentation_failures,
            "feature_clock_violations": dataset.feature_clock_violations,
        },
        "feature_contract": {
            "low_repetition_feature": REPETITION_FEATURE,
            "impact_source_feature": IMPACT_FEATURE,
            "impact_transform": "-abs(entry_price_impact_pct_points)",
            "cutpoint_method": "outcome_blind_global_feature_terciles",
            "low_repetition_rule": (
                "feature <= global lower-tercile cutpoint"
            ),
            "impact_close_rule": (
                "-abs(priceImpact) > global upper-tercile cutpoint"
            ),
            "flow60_closed_feature_used": False,
            "decision_delay_used": False,
            "participant_quality_used": False,
        },
        "cutpoints": cutpoints,
        "overlap": _variant_overlap(rows, cutpoints),
        "results": results,
        "scientific_note": (
            "This tournament is retrospective discovery on the consumed V68 "
            "-03 sample. The two feature directions come from the immediately "
            "preceding causal diagnostic; no variant can be called edge. "
            "The AND combination is the only interaction tested because it is "
            "the predeclared composition of one market-structure candidate "
            "(low 30s wallet repetition) and one copyability candidate "
            "(price impact close to zero). Any promotion requires freezing "
            "the exact rule before a new independent fresh cohort."
        ),
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def print_summary(report: dict[str, Any]) -> None:
    print("Crypto Copy Trader — Burst Incremental Tournament V0")
    print(f"classification={report['classification']}")
    print(f"rows_total={report['rows_total']}")
    q = report["dataset_quality"]
    print(
        "dataset_quality="
        f"lineage_violations={q['lineage_violations']} "
        f"augmentation_failures={q['augmentation_failures']} "
        f"feature_clock_violations={q['feature_clock_violations']}"
    )
    c = report["cutpoints"]
    print(
        "CUTPOINTS "
        f"repetition_low_max={c['repetition_low_max']:.6f} "
        f"impact_closeness_mid_max={c['impact_closeness_mid_max']:.6f}"
    )
    overlap = report["overlap"]
    print(
        "OVERLAP "
        f"low_repetition={overlap['low_repetition_rows']} "
        f"impact_close={overlap['impact_close_rows']} "
        f"intersection={overlap['intersection_rows']} "
        f"union={overlap['union_rows']}"
    )

    print("\n=== PRIMARY 900s ===")
    for scope in ("A", "B", "ALL"):
        print(f"--- {scope} ---")
        for variant, metrics in report["results"]["900"][scope].items():
            print(
                f"{variant} "
                f"selected={metrics['selected_rows']} "
                f"outcomes={metrics['available_outcomes']} "
                f"take_rate={_fmt(metrics['take_rate_pct'])} "
                f"positive_pct={_fmt(metrics['positive_share_pct'])} "
                f"mean={_fmt(metrics['mean_return_pct'])} "
                f"median={_fmt(metrics['median_return_pct'])} "
                f"PF={_fmt(metrics['profit_factor'])} "
                f"mean_wo_best={_fmt(metrics['mean_without_best_pct'])} "
                f"catastrophic_count={metrics['catastrophic_loss_count']} "
                f"catastrophic_pct={_fmt(metrics['catastrophic_loss_rate_pct'])}"
            )

    print("\n=== HORIZON ROBUSTNESS ALL ===")
    for horizon in HORIZONS_SECONDS:
        print(f"HORIZON={horizon}")
        for variant, metrics in report["results"][str(horizon)]["ALL"].items():
            print(
                f"{variant} "
                f"n={metrics['available_outcomes']} "
                f"median={_fmt(metrics['median_return_pct'])} "
                f"PF={_fmt(metrics['profit_factor'])} "
                f"mean_wo_best={_fmt(metrics['mean_without_best_pct'])} "
                f"catastrophic_pct={_fmt(metrics['catastrophic_loss_rate_pct'])}"
            )

    print("\nDIAGNOSTIC_ONLY=True")
    print("NO_SELECTOR_FROZEN=True")
    print("NO_NEW_FRESH=True")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only incremental tournament: Burst baseline vs low wallet "
            "repetition vs price-impact closeness vs their AND."
        )
    )
    parser.add_argument("--run-keys", nargs=2, required=True)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "artifacts/burst_incremental_tournament_v0/report.json"
        ),
    )
    args = parser.parse_args()

    report = build_report(
        (
            str(args.run_keys[0]).strip(),
            str(args.run_keys[1]).strip(),
        )
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print_summary(report)
    print(f"report={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
