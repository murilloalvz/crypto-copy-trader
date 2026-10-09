from __future__ import annotations

import argparse
import math
import sys

import route_research_forward_cohort_v43 as v43
import route_research_forward_cohort_v46 as v46
from src.opportunity_route_research_store import load_route_research_outcomes
from src.route_research_early_opportunity_v55 import (
    FEATURE_DEFINITIONS_V55,
    V55_MIN_FEATURE_COVERAGE_PCT_PER_SUBCOHORT,
    V55_MIN_ROWS_PER_SUBCOHORT,
    V55_PRIMARY_DISCOVERY_HORIZON_SECONDS,
    build_early_opportunity_dataset_v55,
    candidate_coverage_ok_v55,
    feature_coverage_by_scope_v55,
)
from src.route_research_feature_review_v47 import (
    effect_for_feature_v47,
    grouping_for_feature_v47,
    return_metrics_v47,
)
import unified_market_execution_quote_smoke_v31 as v31
import unified_market_route_research_smoke_v49 as v49
import unified_market_route_research_smoke_v54 as v54


V55_SYSTEMS_PROFILE = "v54_demand_only_resolution"
V55_PUMP_PREPARE_WORKERS = v49.V49_PUMP_PREPARE_WORKERS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "v55 fresh causal early-opportunity discovery. PAPER / RESEARCH / READ ONLY; "
            "frozen detector and v46 acquisition semantics on the validated v54 systems profile."
        )
    )
    parser.add_argument("--run-key", required=True, help="Fresh base run key; -A and -B are appended")
    parser.add_argument("--hazard-start-interval-ms", type=int, default=650)
    parser.add_argument("--entry-start-interval-ms", type=int, default=1000)
    parser.add_argument("--exit-start-interval-ms", type=int, default=250)
    return parser


def _fmt(value) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        if math.isinf(value):
            return "inf"
        return f"{value:.3f}"
    return str(value)


def _fresh_run_preflight(run_keys: tuple[str, str]) -> bool:
    return all(len(load_route_research_outcomes(acquisition_run_key=run_key)) == 0 for run_key in run_keys)


def _run_v46(args, base: str) -> int:
    original_argv = list(sys.argv)
    original_v42_run = v43.v42.run_smoke_v42
    original_pump_prepare_workers = v31.PASS_PUMP_PREPARE_WORKERS
    try:
        v43.v42.run_smoke_v42 = v54.run_smoke_v54
        v31.PASS_PUMP_PREPARE_WORKERS = V55_PUMP_PREPARE_WORKERS
        sys.argv = [
            "route_research_forward_cohort_v46.py",
            "--run-key",
            base,
            "--hazard-start-interval-ms",
            str(args.hazard_start_interval_ms),
            "--entry-start-interval-ms",
            str(args.entry_start_interval_ms),
            "--exit-start-interval-ms",
            str(args.exit_start_interval_ms),
        ]
        return int(v46.main())
    finally:
        sys.argv = original_argv
        v43.v42.run_smoke_v42 = original_v42_run
        v31.PASS_PUMP_PREPARE_WORKERS = original_pump_prepare_workers


def _baseline(rows, horizon: int, scope: str):
    scoped = rows if scope == "ALL" else tuple(row for row in rows if row.cohort == scope)
    values = [float(row.labels[horizon]) for row in scoped if row.labels.get(horizon) is not None]
    return return_metrics_v47(values)


def main() -> int:
    args = build_parser().parse_args()
    base = args.run_key.strip()
    if not base:
        raise SystemExit("--run-key cannot be empty")
    if min(args.hazard_start_interval_ms, args.entry_start_interval_ms, args.exit_start_interval_ms) < 0:
        raise SystemExit("provider pacing intervals cannot be negative")

    run_keys = (f"{base}-A", f"{base}-B")
    print("Crypto Copy Trader — Causal Early-Opportunity Discovery v55")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — fresh discovery data only; no detector change, "
        "no trading filter, no signing/submission, no model fitting, no label-optimized thresholds."
    )
    print(
        f"systems_profile={V55_SYSTEMS_PROFILE} pump_prepare_workers={V55_PUMP_PREPARE_WORKERS} "
        f"primary_discovery_horizon={V55_PRIMARY_DISCOVERY_HORIZON_SECONDS}s"
    )
    print(
        "discovery_rule=closed feature set; numeric groups are value-only; labels are used only "
        "after features are frozen to describe associations."
    )
    print(f"base_run_key={base} run_keys={run_keys}")

    if not _fresh_run_preflight(run_keys):
        print("classification=FAIL_V55_RUN_KEY_NOT_FRESH")
        return 2
    print("fresh_run_preflight=PASS")

    acquisition_result = _run_v46(args, base)
    if acquisition_result != 0:
        print("\nV55 ACQUISITION GATE")
        print("classification=FAIL_V55_FROZEN_V46_ACQUISITION_PATH")
        print("Interpretation: discovery did not start because the frozen acquisition path failed closed.")
        return 2

    dataset = build_early_opportunity_dataset_v55(acquisition_run_keys=run_keys)
    rows = dataset.rows
    count_a = sum(1 for row in rows if row.cohort == "A")
    count_b = sum(1 for row in rows if row.cohort == "B")
    base_ds = dataset.base

    print("\nV55 CAUSAL DATASET AUDIT")
    print(
        f"rows_total={len(rows)} rows_A={count_a} rows_B={count_b} "
        f"lineage_violations={base_ds.lineage_violations} "
        f"missing_decisions={base_ds.missing_decisions} missing_episodes={base_ds.missing_episodes} "
        f"missing_hazard_attempts={base_ds.missing_hazard_attempts} "
        f"missing_entry_quotes={base_ds.missing_entry_quotes} "
        f"official_decision_mutations={base_ds.official_decision_mutations} "
        f"augmentation_failures={dataset.augmentation_failures} "
        f"feature_clock_violations={dataset.feature_clock_violations}"
    )
    hard_fail = any(
        (
            count_a < V55_MIN_ROWS_PER_SUBCOHORT,
            count_b < V55_MIN_ROWS_PER_SUBCOHORT,
            base_ds.lineage_violations != 0,
            base_ds.missing_decisions != 0,
            base_ds.missing_episodes != 0,
            base_ds.missing_hazard_attempts != 0,
            base_ds.missing_entry_quotes != 0,
            base_ds.official_decision_mutations != 0,
            dataset.augmentation_failures != 0,
            dataset.feature_clock_violations != 0,
        )
    )
    if hard_fail:
        print("classification=FAIL_V55_CAUSAL_DISCOVERY_DATASET")
        return 2
    print("classification=PASS_V55_CAUSAL_DISCOVERY_DATASET")

    print("\nV55 BASELINE ROUTE-ONLY ECONOMICS")
    for horizon in (300, 900, 3600):
        for scope in ("A", "B", "ALL"):
            metrics = _baseline(rows, horizon, scope)
            print(
                f"horizon={horizon}s scope={scope} n={metrics.n} "
                f"positive_share={_fmt(metrics.positive_share_pct)} "
                f"mean={_fmt(metrics.mean_return_pct)} median={_fmt(metrics.median_return_pct)} "
                f"profit_factor={_fmt(metrics.profit_factor)}"
            )

    print("\nV55 FEATURE COVERAGE")
    groupings = {}
    for definition in FEATURE_DEFINITIONS_V55:
        grouping = grouping_for_feature_v47(rows=rows, definition=definition)
        groupings[definition.name] = grouping
        parts = []
        for scope in ("A", "B", "ALL"):
            known, total, pct = feature_coverage_by_scope_v55(
                rows=rows, feature_name=definition.name, scope=scope
            )
            parts.append(f"{scope}={known}/{total}({pct:.1f}%)")
        print(
            f"feature={definition.name} family={definition.family} coverage={' '.join(parts)} "
            f"grouping={grouping.descriptor} groups={grouping.ordered_groups}"
        )

    print("\nV55 DESCRIPTIVE FEATURE EFFECTS")
    effects_900 = []
    for horizon in (300, 900, 3600):
        print(f"\n[horizon={horizon}s]")
        for definition in FEATURE_DEFINITIONS_V55:
            grouping = groupings[definition.name]
            effect = effect_for_feature_v47(
                rows=rows,
                definition=definition,
                grouping=grouping,
                horizon_seconds=horizon,
            )
            if horizon == V55_PRIMARY_DISCOVERY_HORIZON_SECONDS:
                effects_900.append(effect)
            print(
                f"feature={effect.feature_name} family={effect.family} comparison={effect.comparison or 'NA'} "
                f"delta_median_A={_fmt(effect.delta_median_a)} support_A={effect.support_a} "
                f"delta_median_B={_fmt(effect.delta_median_b)} support_B={effect.support_b} "
                f"delta_median_ALL={_fmt(effect.delta_median_all)} classification={effect.classification}"
            )

    print("\nV55 900S HYPOTHESIS CANDIDATES")
    candidates = [
        effect
        for effect in effects_900
        if effect.classification == "SAME_DIRECTION_DESCRIPTIVE_ONLY"
        and candidate_coverage_ok_v55(rows=rows, feature_name=effect.feature_name)
    ]
    candidates.sort(key=lambda item: abs(float(item.delta_median_all or 0.0)), reverse=True)
    if not candidates:
        print("none")
    else:
        for effect in candidates:
            print(
                f"feature={effect.feature_name} family={effect.family} comparison={effect.comparison} "
                f"delta_median_A={_fmt(effect.delta_median_a)} delta_median_B={_fmt(effect.delta_median_b)} "
                f"delta_median_ALL={_fmt(effect.delta_median_all)} "
                "status=HYPOTHESIS_CANDIDATE_FOR_SEPARATE_FUTURE_HOLDOUT_ONLY"
            )

    print("\nV55 FINAL CLASSIFICATION")
    print(
        f"causal_dataset_clean={not hard_fail} rows_A={count_a} rows_B={count_b} "
        f"minimum_feature_coverage_pct={V55_MIN_FEATURE_COVERAGE_PCT_PER_SUBCOHORT:.1f} "
        f"same_direction_900s_candidates={len(candidates)}"
    )
    print("classification=READY_FOR_V55_DESCRIPTIVE_HYPOTHESIS_REVIEW")
    print(
        "Interpretation: v55 completes discovery, not validation. No candidate is a trading rule. "
        "Do not fit combinations, retune bins, or reuse these A/B rows as a holdout. A candidate must "
        "be chosen and frozen in a separate protocol before any new prospective validation."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
