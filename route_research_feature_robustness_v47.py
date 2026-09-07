from __future__ import annotations

import argparse
import math

from src.route_research_feature_review_v47 import (
    FEATURE_DEFINITIONS_V47,
    build_feature_dataset_v47,
    effect_for_feature_v47,
    grouping_for_feature_v47,
)
from src.route_research_feature_robustness_v47 import (
    group_label_values_v47,
    robust_return_metrics_v47,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "v47 offline candidate robustness review over the already-observed v46 A/B cohort. "
            "READ ONLY: reuses v47 groupings; no providers, writes, backfill, or new thresholds."
        )
    )
    parser.add_argument(
        "--base-run-key",
        required=True,
        help="v46 base key; -A and -B are derived automatically",
    )
    return parser


def _fmt(value) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        if math.isinf(value):
            return "inf"
        return f"{value:.3f}"
    return str(value)


def _comparison_groups(definition, grouping) -> tuple[str, str] | None:
    if (
        definition.kind == "numeric"
        and "LOW" in grouping.ordered_groups
        and "HIGH" in grouping.ordered_groups
    ):
        return "LOW", "HIGH"
    if len(grouping.ordered_groups) == 2:
        return grouping.ordered_groups[0], grouping.ordered_groups[1]
    return None


def main() -> int:
    args = build_parser().parse_args()
    base = args.base_run_key.strip()
    if not base:
        raise SystemExit("--base-run-key cannot be empty")
    run_keys = (f"{base}-A", f"{base}-B")

    print("Crypto Copy Trader — v47 Candidate Robustness Review")
    print(
        "Mode: READ ONLY / DESCRIPTIVE ROBUSTNESS — persisted v46 evidence only; "
        "reuses v47 feature groupings exactly; no provider calls, writes, backfill, "
        "detector changes, strategy rules, or threshold discovery."
    )
    print(f"base_run_key={base} run_keys={run_keys}")

    dataset = build_feature_dataset_v47(acquisition_run_keys=run_keys)
    rows = dataset.rows
    count_a = sum(1 for row in rows if row.cohort == "A")
    count_b = sum(1 for row in rows if row.cohort == "B")
    hard_fail = any(
        (
            not rows,
            dataset.lineage_violations != 0,
            dataset.missing_decisions != 0,
            dataset.missing_episodes != 0,
            dataset.missing_hazard_attempts != 0,
            dataset.missing_entry_quotes != 0,
            dataset.official_decision_mutations != 0,
            count_a == 0,
            count_b == 0,
        )
    )

    print("\nV47 ROBUSTNESS CAUSAL AUDIT")
    print(
        f"rows_total={len(rows)} rows_A={count_a} rows_B={count_b} "
        f"lineage_violations={dataset.lineage_violations} "
        f"missing_decisions={dataset.missing_decisions} "
        f"missing_episodes={dataset.missing_episodes} "
        f"missing_hazard_attempts={dataset.missing_hazard_attempts} "
        f"missing_entry_quotes={dataset.missing_entry_quotes} "
        f"official_decision_mutations={dataset.official_decision_mutations}"
    )
    if hard_fail:
        print("classification=FAIL_V47_ROBUSTNESS_CAUSAL_AUDIT")
        return 2
    print("classification=PASS_V47_ROBUSTNESS_CAUSAL_AUDIT")

    definition_by_name = {item.name: item for item in FEATURE_DEFINITIONS_V47}
    groupings = {
        definition.name: grouping_for_feature_v47(rows=rows, definition=definition)
        for definition in FEATURE_DEFINITIONS_V47
    }
    effects = []
    for horizon in (300, 900, 3600):
        for definition in FEATURE_DEFINITIONS_V47:
            effect = effect_for_feature_v47(
                rows=rows,
                definition=definition,
                grouping=groupings[definition.name],
                horizon_seconds=horizon,
            )
            if effect.classification == "SAME_DIRECTION_DESCRIPTIVE_ONLY":
                effects.append(effect)
    effects.sort(key=lambda item: abs(float(item.delta_median_all or 0.0)), reverse=True)

    print("\nV47 CANDIDATE ROBUSTNESS METRICS")
    print(
        "metrics=n,positive_share,mean,median,profit_factor,best,worst,mean_without_best,"
        "largest_winner_share_gross_profit_pct"
    )
    if not effects:
        print("none")
    for effect in effects:
        definition = definition_by_name[effect.feature_name]
        grouping = groupings[effect.feature_name]
        groups = _comparison_groups(definition, grouping)
        if groups is None:
            continue
        first, second = groups
        print(
            f"\ncandidate horizon={effect.horizon_seconds}s feature={effect.feature_name} "
            f"family={effect.family} comparison={second}-{first} "
            f"grouping={grouping.descriptor} "
            f"delta_median_A={_fmt(effect.delta_median_a)} "
            f"delta_median_B={_fmt(effect.delta_median_b)} "
            f"delta_median_ALL={_fmt(effect.delta_median_all)}"
        )
        for scope in ("A", "B", "ALL"):
            for group in (first, second):
                values = group_label_values_v47(
                    rows=rows,
                    grouping=grouping,
                    horizon_seconds=effect.horizon_seconds,
                    scope=scope,
                    group=group,
                )
                metrics = robust_return_metrics_v47(values)
                print(
                    f"scope={scope} group={group} n={metrics.n} "
                    f"positive_share={_fmt(metrics.positive_share_pct)} "
                    f"mean={_fmt(metrics.mean_return_pct)} "
                    f"median={_fmt(metrics.median_return_pct)} "
                    f"profit_factor={_fmt(metrics.profit_factor)} "
                    f"best={_fmt(metrics.best_return_pct)} "
                    f"worst={_fmt(metrics.worst_return_pct)} "
                    f"mean_without_best={_fmt(metrics.mean_without_best_pct)} "
                    f"largest_winner_share_gross_profit_pct="
                    f"{_fmt(metrics.largest_winner_share_gross_profit_pct)}"
                )

    print("\nV47 ROBUSTNESS FINAL CLASSIFICATION")
    print(f"same_direction_candidates_reviewed={len(effects)}")
    print("classification=ROBUSTNESS_METRICS_READY_FOR_MANUAL_HYPOTHESIS_SELECTION")
    print(
        "Interpretation: these metrics deepen the already-observed v47 candidates only. "
        "They do not validate a trading rule and do not create a virgin holdout. "
        "Reject candidates that are low-support, unstable in economic shape, or dominated by "
        "one winner before freezing any hypothesis for fresh v48 data."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
