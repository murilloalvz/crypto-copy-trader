from __future__ import annotations

import argparse

from src.route_research_early_opportunity_v55 import (
    FEATURE_DEFINITIONS_V55,
    V55_MIN_FEATURE_COVERAGE_PCT_PER_SUBCOHORT,
    V55_MIN_ROWS_PER_SUBCOHORT,
    V55_PRIMARY_DISCOVERY_HORIZON_SECONDS,
    build_early_opportunity_dataset_v55,
    feature_coverage_by_scope_v55,
)
from src.route_research_feature_review_v47 import (
    effect_for_feature_v47,
    grouping_for_feature_v47,
)
from src.route_research_v55_candidate_selection import (
    build_candidate_selection_record_v55,
    rank_candidate_selection_records_v55,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only deterministic candidate selection over a completed v55 discovery base. "
            "No providers, no writes, no model fitting, no threshold tuning."
        )
    )
    parser.add_argument("--base-run-key", required=True)
    return parser


def _audit_ok(dataset) -> tuple[bool, int, int]:
    rows = dataset.rows
    count_a = sum(1 for row in rows if row.cohort == "A")
    count_b = sum(1 for row in rows if row.cohort == "B")
    base = dataset.base
    ok = not any(
        (
            count_a < V55_MIN_ROWS_PER_SUBCOHORT,
            count_b < V55_MIN_ROWS_PER_SUBCOHORT,
            base.lineage_violations != 0,
            base.missing_decisions != 0,
            base.missing_episodes != 0,
            base.missing_hazard_attempts != 0,
            base.missing_entry_quotes != 0,
            base.official_decision_mutations != 0,
            dataset.augmentation_failures != 0,
            dataset.feature_clock_violations != 0,
        )
    )
    return ok, count_a, count_b


def main() -> int:
    args = build_parser().parse_args()
    base_run_key = args.base_run_key.strip()
    if not base_run_key:
        raise SystemExit("--base-run-key cannot be empty")
    run_keys = (f"{base_run_key}-A", f"{base_run_key}-B")

    print("Crypto Copy Trader — v55 Deterministic Candidate Selection")
    print(
        "Mode: READ ONLY / POST-DISCOVERY REVIEW — persisted completed v55 evidence only; "
        "no provider calls, writes, models, new features or threshold tuning."
    )
    print(f"base_run_key={base_run_key} run_keys={run_keys}")
    print(
        "ranking=weakest_subcohort_abs_delta -> split_balance_ratio -> abs_aggregate_delta -> "
        "min_A_B_coverage -> feature_name"
    )

    dataset = build_early_opportunity_dataset_v55(acquisition_run_keys=run_keys)
    audit_ok, count_a, count_b = _audit_ok(dataset)
    print("\nV55 SELECTION DATASET AUDIT")
    print(
        f"rows_total={len(dataset.rows)} rows_A={count_a} rows_B={count_b} "
        f"lineage_violations={dataset.base.lineage_violations} "
        f"missing_decisions={dataset.base.missing_decisions} "
        f"missing_episodes={dataset.base.missing_episodes} "
        f"missing_hazard_attempts={dataset.base.missing_hazard_attempts} "
        f"missing_entry_quotes={dataset.base.missing_entry_quotes} "
        f"official_decision_mutations={dataset.base.official_decision_mutations} "
        f"augmentation_failures={dataset.augmentation_failures} "
        f"feature_clock_violations={dataset.feature_clock_violations}"
    )
    if not audit_ok:
        print("classification=FAIL_V55_CANDIDATE_SELECTION_DATASET")
        return 2
    print("classification=PASS_V55_CANDIDATE_SELECTION_DATASET")

    candidates = []
    for definition in FEATURE_DEFINITIONS_V55:
        grouping = grouping_for_feature_v47(rows=dataset.rows, definition=definition)
        effect = effect_for_feature_v47(
            rows=dataset.rows,
            definition=definition,
            grouping=grouping,
            horizon_seconds=V55_PRIMARY_DISCOVERY_HORIZON_SECONDS,
        )
        _ka, _ta, coverage_a = feature_coverage_by_scope_v55(
            rows=dataset.rows,
            feature_name=definition.name,
            scope="A",
        )
        _kb, _tb, coverage_b = feature_coverage_by_scope_v55(
            rows=dataset.rows,
            feature_name=definition.name,
            scope="B",
        )
        candidate = build_candidate_selection_record_v55(
            effect=effect,
            grouping_descriptor=grouping.descriptor,
            coverage_a_pct=coverage_a,
            coverage_b_pct=coverage_b,
            minimum_coverage_pct=V55_MIN_FEATURE_COVERAGE_PCT_PER_SUBCOHORT,
        )
        if candidate is not None:
            candidates.append(candidate)

    ranked = rank_candidate_selection_records_v55(candidates)
    print("\nV55 PRE-REGISTERED CANDIDATE RANKING")
    if not ranked:
        print("none")
        print("classification=NO_V55_CANDIDATE_FOR_PROSPECTIVE_HOLDOUT")
        print(
            "Interpretation: do not loosen feature, coverage, support or horizon rules to create a candidate."
        )
        return 0

    for index, item in enumerate(ranked, start=1):
        print(
            f"rank={index} feature={item.feature_name} family={item.family} "
            f"favorable={item.favorable_group} opposite={item.opposite_group} "
            f"delta_median_A={item.delta_median_a:.3f} "
            f"delta_median_B={item.delta_median_b:.3f} "
            f"delta_median_ALL={item.delta_median_all:.3f} "
            f"weakest_abs_delta={item.weakest_subcohort_abs_delta:.3f} "
            f"split_balance_ratio={item.split_balance_ratio:.3f} "
            f"coverage_A={item.coverage_a_pct:.1f}% coverage_B={item.coverage_b_pct:.1f}% "
            f"grouping={item.grouping_descriptor}"
        )

    selected = ranked[0]
    print("\nV55 CARRY-FORWARD SELECTION")
    print(
        f"feature={selected.feature_name} favorable={selected.favorable_group} "
        f"opposite={selected.opposite_group} grouping={selected.grouping_descriptor}"
    )
    print("classification=SELECTED_V55_DISCOVERY_HYPOTHESIS_FOR_PREREGISTRATION_ONLY")
    print(
        "Interpretation: rank #1 may be preregistered for one separate fresh prospective holdout. "
        "It is not a trading rule and its discovery effect size is not an expected return."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
