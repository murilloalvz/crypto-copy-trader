from __future__ import annotations

import argparse
import math

from src.route_research_feature_review_v47 import (
    FEATURE_DEFINITIONS_V47,
    V47_MIN_SPLIT_GROUP_SUPPORT,
    build_feature_dataset_v47,
    effect_for_feature_v47,
    feature_coverage_v47,
    group_metrics_v47,
    grouping_for_feature_v47,
    return_metrics_v47,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "v47 offline causal feature review over an already-complete v46 A/B cohort. "
            "READ ONLY: no provider calls, no writes, no strategy thresholds."
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


def _baseline(rows, horizon: int, scope: str):
    scoped = rows if scope == "ALL" else tuple(row for row in rows if row.cohort == scope)
    values = [float(row.labels[horizon]) for row in scoped if row.labels.get(horizon) is not None]
    return return_metrics_v47(values)


def main() -> int:
    args = build_parser().parse_args()
    base = args.base_run_key.strip()
    if not base:
        raise SystemExit("--base-run-key cannot be empty")
    run_keys = (f"{base}-A", f"{base}-B")

    print("Crypto Copy Trader — Offline Causal Feature Review v47")
    print(
        "Mode: READ ONLY / DESCRIPTIVE DISCOVERY — persisted v46 evidence only; no RPC/Jupiter calls, "
        "no writes, no backfill, no detector/strategy/threshold change."
    )
    print(f"base_run_key={base} run_keys={run_keys}")
    print(
        "causal_rule=every feature must be observable at or before research_decision_as_of; "
        "numeric bins use feature values only, never labels."
    )

    dataset = build_feature_dataset_v47(acquisition_run_keys=run_keys)
    rows = dataset.rows
    count_a = sum(1 for row in rows if row.cohort == "A")
    count_b = sum(1 for row in rows if row.cohort == "B")

    print("\nV47 CAUSAL DATASET AUDIT")
    print(
        f"rows_total={len(rows)} rows_A={count_a} rows_B={count_b} "
        f"lineage_violations={dataset.lineage_violations} "
        f"missing_decisions={dataset.missing_decisions} missing_episodes={dataset.missing_episodes} "
        f"missing_hazard_attempts={dataset.missing_hazard_attempts} "
        f"missing_entry_quotes={dataset.missing_entry_quotes} "
        f"official_decision_mutations={dataset.official_decision_mutations}"
    )

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
    if hard_fail:
        print("classification=FAIL_V47_CAUSAL_DATASET_AUDIT")
        return 2
    print("classification=PASS_V47_CAUSAL_DATASET_AUDIT")

    print("\nV47 BASELINE ROUTE-ONLY ECONOMICS")
    baseline_ready = True
    for horizon in (300, 900, 3600):
        for scope in ("A", "B", "ALL"):
            metrics = _baseline(rows, horizon, scope)
            if scope == "ALL" and metrics.n < 30:
                baseline_ready = False
            print(
                f"horizon={horizon}s scope={scope} n={metrics.n} "
                f"positive_share={_fmt(metrics.positive_share_pct)} "
                f"mean={_fmt(metrics.mean_return_pct)} median={_fmt(metrics.median_return_pct)} "
                f"profit_factor={_fmt(metrics.profit_factor)}"
            )

    print("\nV47 FEATURE COVERAGE")
    groupings = {}
    for definition in FEATURE_DEFINITIONS_V47:
        grouping = grouping_for_feature_v47(rows=rows, definition=definition)
        groupings[definition.name] = grouping
        coverage_parts = []
        for scope in ("A", "B", "ALL"):
            known, total, pct = feature_coverage_v47(
                rows=rows, feature_name=definition.name, scope=scope
            )
            coverage_parts.append(f"{scope}={known}/{total}({pct:.1f}%)")
        print(
            f"feature={definition.name} family={definition.family} kind={definition.kind} "
            f"coverage={' '.join(coverage_parts)} grouping={grouping.descriptor} "
            f"groups={grouping.ordered_groups}"
        )

    print("\nV47 DESCRIPTIVE FEATURE EFFECTS")
    print(
        f"comparison_metric=median_return_delta minimum_group_support_per_subcohort="
        f"{V47_MIN_SPLIT_GROUP_SUPPORT}"
    )
    effects = []
    for horizon in (300, 900, 3600):
        print(f"\n[horizon={horizon}s]")
        for definition in FEATURE_DEFINITIONS_V47:
            grouping = groupings[definition.name]
            effect = effect_for_feature_v47(
                rows=rows,
                definition=definition,
                grouping=grouping,
                horizon_seconds=horizon,
            )
            effects.append(effect)
            print(
                f"feature={effect.feature_name} family={effect.family} "
                f"comparison={effect.comparison or 'NA'} "
                f"delta_median_A={_fmt(effect.delta_median_a)} support_A={effect.support_a} "
                f"delta_median_B={_fmt(effect.delta_median_b)} support_B={effect.support_b} "
                f"delta_median_ALL={_fmt(effect.delta_median_all)} "
                f"classification={effect.classification}"
            )

    print("\nV47 SAME-DIRECTION DESCRIPTIVE CANDIDATES")
    candidates = [
        effect
        for effect in effects
        if effect.classification == "SAME_DIRECTION_DESCRIPTIVE_ONLY"
    ]
    candidates.sort(
        key=lambda item: abs(float(item.delta_median_all or 0.0)), reverse=True
    )
    if not candidates:
        print("none")
    else:
        for effect in candidates:
            print(
                f"horizon={effect.horizon_seconds}s feature={effect.feature_name} "
                f"comparison={effect.comparison} delta_median_A={_fmt(effect.delta_median_a)} "
                f"delta_median_B={_fmt(effect.delta_median_b)} "
                f"delta_median_ALL={_fmt(effect.delta_median_all)} "
                "status=HYPOTHESIS_CANDIDATE_FOR_FUTURE_HOLDOUT_ONLY"
            )

    same_direction_15m = sum(
        1
        for item in candidates
        if item.horizon_seconds == 900
    )
    print("\nV47 FINAL CLASSIFICATION")
    print(
        f"causal_dataset_clean={not hard_fail} aggregate_label_sample_ready={baseline_ready} "
        f"same_direction_descriptive_candidates={len(candidates)} "
        f"same_direction_900s_candidates={same_direction_15m}"
    )
    print(
        "classification="
        + ("READY_FOR_DESCRIPTIVE_HYPOTHESIS_REVIEW" if baseline_ready else "INCONCLUSIVE_V47_LABEL_SAMPLE")
    )
    print(
        "Interpretation: v47 is discovery only. A and B are already observed and are NOT a virgin "
        "holdout for any new rule. No candidate here is a trading filter. Any chosen hypothesis must "
        "be frozen before a fresh v48 out-of-sample cohort."
    )
    return 0 if baseline_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
