from __future__ import annotations

import argparse
import math
import sys

import route_research_forward_cohort_v43 as v43
import route_research_forward_cohort_v46 as v46
from src.opportunity_route_research_store import load_route_research_outcomes
from src.route_research_feature_review_v47 import build_feature_dataset_v47
from src.route_research_prospective_holdout_v48 import (
    V48_FEATURE_NAME,
    V48_GROUPS,
    V48_LOW_MAX,
    V48_MID_MAX,
    V48_MIN_GROUP_SUPPORT_PER_SUBCOHORT,
    V48_PRIMARY_HORIZON_SECONDS,
    group_metrics_v48,
    primary_gate_v48,
)
import unified_market_execution_quote_smoke_v31 as v31
import unified_market_route_research_smoke_v49 as v49
import unified_market_route_research_smoke_v54 as v54


V48_VALIDATED_SYSTEMS_PROFILE = "v54_demand_only_resolution"
V48_VALIDATED_PUMP_PREPARE_WORKERS = v49.V49_PUMP_PREPARE_WORKERS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "v48 fresh prospective holdout for the pre-registered flow60 hypothesis. "
            "PAPER / RESEARCH / READ ONLY; frozen v46 A/B cohort/economic protocol with the "
            "prospectively validated v54 demand-only systems profile."
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
    """Run the frozen v46 cohort protocol on the validated v54 systems scheduling path.

    The amendment is deliberately scoped below the v46/v44/v43 cohort/economic logic: v54 replaces
    only the v42 systems smoke entry point used during acquisition, and the measured Pump prepare
    worker count remains the validated v49+ value. Both globals are restored even on failure.
    Detector thresholds, provider pacing, cohort cap/minimum, horizons, route notional/slippage,
    forward collector and the v48 evaluator remain unchanged.
    """

    original_argv = list(sys.argv)
    original_v42_run = v43.v42.run_smoke_v42
    original_pump_prepare_workers = v31.PASS_PUMP_PREPARE_WORKERS
    try:
        v43.v42.run_smoke_v42 = v54.run_smoke_v54
        v31.PASS_PUMP_PREPARE_WORKERS = V48_VALIDATED_PUMP_PREPARE_WORKERS
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


def _print_metrics(rows) -> None:
    print("\nV48 FROZEN GROUP ECONOMICS")
    print(
        "feature=flow60_event_count frozen_bins="
        f"LOW<=${V48_LOW_MAX} MID={V48_LOW_MAX + 1}-{V48_MID_MAX} HIGH>{V48_MID_MAX}".replace("$", "")
    )
    print("primary_horizon=900s primary_contrast=LOW-vs-HIGH; 300s/3600s and MID are diagnostic only")
    for horizon in (300, 900, 3600):
        print(f"\n[horizon={horizon}s]")
        for scope in ("A", "B", "ALL"):
            metrics = group_metrics_v48(rows=rows, horizon_seconds=horizon, scope=scope)
            for group in V48_GROUPS:
                item = metrics[group]
                print(
                    f"scope={scope} group={group} n={item.n} "
                    f"positive_share={_fmt(item.positive_share_pct)} "
                    f"mean={_fmt(item.mean_return_pct)} median={_fmt(item.median_return_pct)} "
                    f"profit_factor={_fmt(item.profit_factor)} best={_fmt(item.best_return_pct)} "
                    f"worst={_fmt(item.worst_return_pct)} "
                    f"mean_without_best={_fmt(item.mean_without_best_pct)} "
                    f"largest_winner_share_gross_profit_pct={_fmt(item.largest_winner_share_gross_profit_pct)}"
                )


def main() -> int:
    args = build_parser().parse_args()
    base = args.run_key.strip()
    if not base:
        raise SystemExit("--run-key cannot be empty")
    if min(args.hazard_start_interval_ms, args.entry_start_interval_ms, args.exit_start_interval_ms) < 0:
        raise SystemExit("provider pacing intervals cannot be negative")

    run_keys = (f"{base}-A", f"{base}-B")
    print("Crypto Copy Trader — Prospective Flow60 Holdout v48")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — fresh data only; no detector change, no strategy filter, "
        "no signing/submission, no threshold discovery."
    )
    print("\nV48 PRE-REGISTERED PRIMARY HYPOTHESIS")
    print(
        f"feature={V48_FEATURE_NAME} cutoff_clock=research_decision_as_of "
        f"LOW<=25 MID=26-47 HIGH>47 primary_horizon={V48_PRIMARY_HORIZON_SECONDS}s "
        "primary_contrast=LOW-vs-HIGH"
    )
    print(
        "primary_pass_requires=LOW median > HIGH median in A/B/ALL; LOW median>0 and PF>1 in A/B; "
        "aggregate LOW PF>1; aggregate LOW mean_without_best>0"
    )
    print(
        f"minimum_available_support_per_subcohort=LOW>={V48_MIN_GROUP_SUPPORT_PER_SUBCOHORT} "
        f"HIGH>={V48_MIN_GROUP_SUPPORT_PER_SUBCOHORT}"
    )
    print(
        f"systems_profile={V48_VALIDATED_SYSTEMS_PROFILE} "
        f"pump_prepare_workers={V48_VALIDATED_PUMP_PREPARE_WORKERS} "
        "cohort_protocol=v46_frozen economic_evaluator=v48_frozen"
    )
    print(f"base_run_key={base} run_keys={run_keys}")

    if not _fresh_run_preflight(run_keys):
        print("classification=FAIL_V48_RUN_KEY_NOT_FRESH")
        print("Interpretation: v48 must use untouched fresh run keys; do not reuse or overwrite prior evidence.")
        return 2
    print("fresh_run_preflight=PASS")

    acquisition_result = _run_v46(args, base)
    if acquisition_result != 0:
        print("\nV48 ACQUISITION GATE")
        print("classification=FAIL_V48_FROZEN_V46_ACQUISITION_PATH")
        print(
            "Interpretation: no economic hypothesis verdict because the frozen v46 cohort protocol "
            "on the validated v54 systems profile did not pass."
        )
        return 2

    dataset = build_feature_dataset_v47(acquisition_run_keys=run_keys)
    rows = dataset.rows
    count_a = sum(1 for row in rows if row.cohort == "A")
    count_b = sum(1 for row in rows if row.cohort == "B")
    print("\nV48 CAUSAL HOLDOUT AUDIT")
    print(
        f"rows_total={len(rows)} rows_A={count_a} rows_B={count_b} "
        f"lineage_violations={dataset.lineage_violations} missing_decisions={dataset.missing_decisions} "
        f"missing_episodes={dataset.missing_episodes} missing_hazard_attempts={dataset.missing_hazard_attempts} "
        f"missing_entry_quotes={dataset.missing_entry_quotes} "
        f"official_decision_mutations={dataset.official_decision_mutations}"
    )
    causal_fail = any(
        (
            not rows,
            count_a == 0,
            count_b == 0,
            dataset.lineage_violations != 0,
            dataset.missing_decisions != 0,
            dataset.missing_episodes != 0,
            dataset.missing_hazard_attempts != 0,
            dataset.missing_entry_quotes != 0,
            dataset.official_decision_mutations != 0,
        )
    )
    if causal_fail:
        print("classification=FAIL_V48_CAUSAL_HOLDOUT_AUDIT")
        return 2
    print("classification=PASS_V48_CAUSAL_HOLDOUT_AUDIT")

    _print_metrics(rows)
    gate = primary_gate_v48(rows=rows)
    print("\nV48 PRIMARY PROSPECTIVE GATE")
    print(
        f"feature_coverage={gate.feature_known}/{gate.feature_total}({gate.feature_coverage_pct:.1f}%) "
        f"support_ok={gate.support_ok} same_direction_ok={gate.same_direction_ok} "
        f"low_positive_median_both={gate.low_positive_median_both} "
        f"low_pf_gt_one_both={gate.low_pf_gt_one_both} "
        f"aggregate_low_pf_gt_one={gate.aggregate_low_pf_gt_one} "
        f"aggregate_low_mean_without_best_positive={gate.aggregate_low_mean_without_best_positive}"
    )
    print(f"classification={gate.classification}")
    print(
        "Interpretation: PASS would prospectively replicate one route-only market-opportunity hypothesis only. "
        "It is not executable/fill/shadow/live-money PASS. FAIL or INCONCLUSIVE must not be rescued by retuning "
        "the bins or switching hypotheses on this same holdout."
    )
    return 0 if gate.classification == "PASS_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
