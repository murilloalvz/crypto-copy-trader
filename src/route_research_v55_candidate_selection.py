from __future__ import annotations

from dataclasses import dataclass

from src.route_research_feature_review_v47 import FeatureEffectV47


@dataclass(frozen=True)
class CandidateSelectionRecordV55:
    feature_name: str
    family: str
    grouping_descriptor: str
    favorable_group: str
    opposite_group: str
    delta_median_a: float
    delta_median_b: float
    delta_median_all: float
    coverage_a_pct: float
    coverage_b_pct: float
    weakest_subcohort_abs_delta: float
    split_balance_ratio: float


def build_candidate_selection_record_v55(
    *,
    effect: FeatureEffectV47,
    grouping_descriptor: str,
    coverage_a_pct: float,
    coverage_b_pct: float,
    minimum_coverage_pct: float = 80.0,
) -> CandidateSelectionRecordV55 | None:
    """Convert one already-computed v55 discovery effect into an eligible selection record.

    This function does not inspect raw returns, fit a model, alter bins or create a trading rule.
    It applies the pre-registered post-discovery eligibility/ranking semantics only.
    """

    if effect.classification != "SAME_DIRECTION_DESCRIPTIVE_ONLY":
        return None
    if min(coverage_a_pct, coverage_b_pct) < minimum_coverage_pct:
        return None
    if effect.comparison != "HIGH-LOW":
        return None
    if (
        effect.delta_median_a is None
        or effect.delta_median_b is None
        or effect.delta_median_all is None
    ):
        return None

    a = float(effect.delta_median_a)
    b = float(effect.delta_median_b)
    overall = float(effect.delta_median_all)
    if a == 0.0 or b == 0.0 or overall == 0.0:
        return None
    if not ((a > 0) == (b > 0) == (overall > 0)):
        return None

    abs_a = abs(a)
    abs_b = abs(b)
    strongest = max(abs_a, abs_b)
    weakest = min(abs_a, abs_b)
    balance = weakest / strongest if strongest > 0 else 0.0
    favorable = "HIGH" if a > 0 else "LOW"
    opposite = "LOW" if favorable == "HIGH" else "HIGH"

    return CandidateSelectionRecordV55(
        feature_name=effect.feature_name,
        family=effect.family,
        grouping_descriptor=grouping_descriptor,
        favorable_group=favorable,
        opposite_group=opposite,
        delta_median_a=a,
        delta_median_b=b,
        delta_median_all=overall,
        coverage_a_pct=float(coverage_a_pct),
        coverage_b_pct=float(coverage_b_pct),
        weakest_subcohort_abs_delta=weakest,
        split_balance_ratio=balance,
    )


def rank_candidate_selection_records_v55(
    records: list[CandidateSelectionRecordV55]
    | tuple[CandidateSelectionRecordV55, ...],
) -> tuple[CandidateSelectionRecordV55, ...]:
    """Apply the pre-registered deterministic ranking; rank #1 is the only carry-forward."""

    return tuple(
        sorted(
            records,
            key=lambda item: (
                -item.weakest_subcohort_abs_delta,
                -item.split_balance_ratio,
                -abs(item.delta_median_all),
                -min(item.coverage_a_pct, item.coverage_b_pct),
                item.feature_name,
            ),
        )
    )


def select_one_candidate_v55(
    records: list[CandidateSelectionRecordV55]
    | tuple[CandidateSelectionRecordV55, ...],
) -> CandidateSelectionRecordV55 | None:
    ranked = rank_candidate_selection_records_v55(records)
    return ranked[0] if ranked else None
