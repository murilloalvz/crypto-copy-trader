import unittest

from src.route_research_feature_review_v47 import CausalFeatureRowV47
from src.route_research_prospective_flow60_buy_share_v68 import (
    V68_FEATURE_NAME,
    V68_FAVORABLE_GROUP,
    V68_GROUPS,
    V68_LOW_MAX,
    V68_MID_MAX,
    V68_OPPOSITE_GROUP,
    frozen_flow60_buy_share_group_v68,
    primary_gate_v68,
)


class ProspectiveFlow60BuyShareV68Tests(unittest.TestCase):
    def row(self, *, cohort: str, episode: str, value, ret900):
        return CausalFeatureRowV47(
            acquisition_run_key=f"run-{cohort}",
            cohort=cohort,
            episode_key=episode,
            token_mint=f"token-{episode}",
            episode_t0=100,
            research_decision_as_of=120,
            features={V68_FEATURE_NAME: value},
            feature_observed_at={V68_FEATURE_NAME: 120},
            labels={300: None, 900: ret900, 3600: None},
            outcome_statuses={300: "PROVIDER_ERROR", 900: "AVAILABLE", 3600: "PROVIDER_ERROR"},
        )

    def test_frozen_constants_match_published_v55_candidate(self):
        self.assertEqual(V68_FEATURE_NAME, "flow60_buy_share_pct")
        self.assertEqual(V68_GROUPS, ("LOW", "MID", "HIGH"))
        self.assertEqual(V68_FAVORABLE_GROUP, "LOW")
        self.assertEqual(V68_OPPOSITE_GROUP, "HIGH")
        self.assertEqual(V68_LOW_MAX, 57.1429)
        self.assertEqual(V68_MID_MAX, 65.7143)

    def test_group_boundaries_are_frozen(self):
        self.assertEqual(frozen_flow60_buy_share_group_v68(0.0), "LOW")
        self.assertEqual(frozen_flow60_buy_share_group_v68(57.1429), "LOW")
        self.assertEqual(frozen_flow60_buy_share_group_v68(57.1430), "MID")
        self.assertEqual(frozen_flow60_buy_share_group_v68(65.7143), "MID")
        self.assertEqual(frozen_flow60_buy_share_group_v68(65.7144), "HIGH")
        self.assertEqual(frozen_flow60_buy_share_group_v68(100.0), "HIGH")

    def test_invalid_feature_values_fail_closed(self):
        for value in (-0.1, 100.1, float("inf"), float("nan"), True, "50"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    frozen_flow60_buy_share_group_v68(value)

    def test_pass_requires_robust_favorable_low_in_both_subcohorts(self):
        rows = []
        for cohort in ("A", "B"):
            for i, ret in enumerate((8.0, 10.0, 12.0, 14.0, 16.0)):
                rows.append(self.row(cohort=cohort, episode=f"{cohort}-low-{i}", value=50.0, ret900=ret))
            for i, ret in enumerate((-15.0, -12.0, -10.0, -8.0, -5.0)):
                rows.append(self.row(cohort=cohort, episode=f"{cohort}-high-{i}", value=80.0, ret900=ret))
        gate = primary_gate_v68(rows=tuple(rows))
        self.assertEqual(
            gate.classification,
            "PASS_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS",
        )
        self.assertTrue(gate.support_ok)
        self.assertTrue(gate.same_direction_ok)
        self.assertTrue(gate.favorable_positive_median_both)
        self.assertTrue(gate.favorable_pf_gt_one_both)
        self.assertTrue(gate.aggregate_favorable_pf_gt_one)
        self.assertTrue(gate.aggregate_favorable_mean_without_best_positive)

    def test_less_bad_low_is_not_enough_to_pass(self):
        rows = []
        for cohort in ("A", "B"):
            for i, ret in enumerate((-8.0, -7.0, -6.0, -5.0, -4.0)):
                rows.append(self.row(cohort=cohort, episode=f"{cohort}-low-{i}", value=50.0, ret900=ret))
            for i, ret in enumerate((-30.0, -25.0, -20.0, -15.0, -10.0)):
                rows.append(self.row(cohort=cohort, episode=f"{cohort}-high-{i}", value=80.0, ret900=ret))
        gate = primary_gate_v68(rows=tuple(rows))
        self.assertEqual(
            gate.classification,
            "FAIL_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS",
        )
        self.assertTrue(gate.same_direction_ok)
        self.assertFalse(gate.favorable_positive_median_both)

    def test_insufficient_extreme_support_is_inconclusive(self):
        rows = []
        for cohort in ("A", "B"):
            for i in range(5):
                rows.append(self.row(cohort=cohort, episode=f"{cohort}-low-{i}", value=50.0, ret900=10.0))
            for i in range(4):
                rows.append(self.row(cohort=cohort, episode=f"{cohort}-high-{i}", value=80.0, ret900=-10.0))
        gate = primary_gate_v68(rows=tuple(rows))
        self.assertEqual(gate.classification, "INCONCLUSIVE_V68_PRIMARY_SUPPORT")
        self.assertFalse(gate.support_ok)

    def test_missing_feature_fails_observability(self):
        good = self.row(cohort="A", episode="good", value=50.0, ret900=10.0)
        missing = CausalFeatureRowV47(
            acquisition_run_key="run-B",
            cohort="B",
            episode_key="missing",
            token_mint="token-missing",
            episode_t0=100,
            research_decision_as_of=120,
            features={V68_FEATURE_NAME: None},
            feature_observed_at={V68_FEATURE_NAME: 120},
            labels={300: None, 900: -10.0, 3600: None},
            outcome_statuses={300: "PROVIDER_ERROR", 900: "AVAILABLE", 3600: "PROVIDER_ERROR"},
        )
        gate = primary_gate_v68(rows=(good, missing))
        self.assertEqual(gate.classification, "FAIL_V68_FEATURE_OBSERVABILITY")
        self.assertEqual(gate.feature_known, 1)
        self.assertEqual(gate.feature_total, 2)


if __name__ == "__main__":
    unittest.main()
