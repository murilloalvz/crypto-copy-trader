from __future__ import annotations

import unittest

from src.route_research_feature_review_v47 import FeatureEffectV47
from src.route_research_v55_candidate_selection import (
    build_candidate_selection_record_v55,
    rank_candidate_selection_records_v55,
    select_one_candidate_v55,
)


def effect(
    *,
    name: str,
    a: float,
    b: float,
    overall: float,
    classification: str = "SAME_DIRECTION_DESCRIPTIVE_ONLY",
) -> FeatureEffectV47:
    return FeatureEffectV47(
        feature_name=name,
        family="synthetic",
        horizon_seconds=900,
        comparison="HIGH-LOW",
        delta_median_a=a,
        delta_median_b=b,
        delta_median_all=overall,
        support_a=(8, 8),
        support_b=(8, 8),
        classification=classification,
    )


class V55CandidateSelectionTests(unittest.TestCase):
    def test_positive_delta_freezes_high_as_favorable(self):
        record = build_candidate_selection_record_v55(
            effect=effect(name="x", a=10.0, b=5.0, overall=7.0),
            grouping_descriptor="value_only_tertiles low_cut<=1 mid_cut<=2",
            coverage_a_pct=100.0,
            coverage_b_pct=100.0,
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.favorable_group, "HIGH")
        self.assertEqual(record.opposite_group, "LOW")

    def test_negative_delta_freezes_low_as_favorable(self):
        record = build_candidate_selection_record_v55(
            effect=effect(name="x", a=-10.0, b=-5.0, overall=-7.0),
            grouping_descriptor="value_only_tertiles low_cut<=1 mid_cut<=2",
            coverage_a_pct=100.0,
            coverage_b_pct=100.0,
        )
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.favorable_group, "LOW")
        self.assertEqual(record.opposite_group, "HIGH")

    def test_low_coverage_is_not_eligible(self):
        record = build_candidate_selection_record_v55(
            effect=effect(name="x", a=10.0, b=10.0, overall=10.0),
            grouping_descriptor="bins",
            coverage_a_pct=79.9,
            coverage_b_pct=100.0,
        )
        self.assertIsNone(record)

    def test_unstable_or_non_candidate_effect_is_not_eligible(self):
        record = build_candidate_selection_record_v55(
            effect=effect(
                name="x",
                a=10.0,
                b=-10.0,
                overall=1.0,
                classification="UNSTABLE_ACROSS_SUBCOHORTS",
            ),
            grouping_descriptor="bins",
            coverage_a_pct=100.0,
            coverage_b_pct=100.0,
        )
        self.assertIsNone(record)

    def test_weakest_subcohort_beats_larger_aggregate(self):
        balanced = build_candidate_selection_record_v55(
            effect=effect(name="balanced", a=8.0, b=8.0, overall=8.0),
            grouping_descriptor="bins-balanced",
            coverage_a_pct=100.0,
            coverage_b_pct=100.0,
        )
        aggregate_star = build_candidate_selection_record_v55(
            effect=effect(name="aggregate_star", a=30.0, b=2.0, overall=20.0),
            grouping_descriptor="bins-star",
            coverage_a_pct=100.0,
            coverage_b_pct=100.0,
        )
        assert balanced is not None and aggregate_star is not None
        ranked = rank_candidate_selection_records_v55((aggregate_star, balanced))
        self.assertEqual(ranked[0].feature_name, "balanced")
        self.assertEqual(select_one_candidate_v55((aggregate_star, balanced)).feature_name, "balanced")

    def test_balance_ratio_breaks_equal_weakest_split(self):
        balanced = build_candidate_selection_record_v55(
            effect=effect(name="balanced", a=8.0, b=8.0, overall=8.0),
            grouping_descriptor="bins-balanced",
            coverage_a_pct=100.0,
            coverage_b_pct=100.0,
        )
        lopsided = build_candidate_selection_record_v55(
            effect=effect(name="lopsided", a=8.0, b=20.0, overall=12.0),
            grouping_descriptor="bins-lopsided",
            coverage_a_pct=100.0,
            coverage_b_pct=100.0,
        )
        assert balanced is not None and lopsided is not None
        ranked = rank_candidate_selection_records_v55((lopsided, balanced))
        self.assertEqual(ranked[0].feature_name, "balanced")

    def test_lexical_final_tie_break_is_deterministic(self):
        first = build_candidate_selection_record_v55(
            effect=effect(name="a_feature", a=8.0, b=8.0, overall=8.0),
            grouping_descriptor="bins-a",
            coverage_a_pct=100.0,
            coverage_b_pct=100.0,
        )
        second = build_candidate_selection_record_v55(
            effect=effect(name="b_feature", a=8.0, b=8.0, overall=8.0),
            grouping_descriptor="bins-b",
            coverage_a_pct=100.0,
            coverage_b_pct=100.0,
        )
        assert first is not None and second is not None
        ranked = rank_candidate_selection_records_v55((second, first))
        self.assertEqual(ranked[0].feature_name, "a_feature")


if __name__ == "__main__":
    unittest.main()
