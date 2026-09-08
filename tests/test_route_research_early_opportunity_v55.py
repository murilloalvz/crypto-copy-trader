from __future__ import annotations

from types import SimpleNamespace
import unittest

from src.route_research_early_opportunity_v55 import (
    FEATURE_DEFINITIONS_V55,
    V55_MIN_FEATURE_COVERAGE_PCT_PER_SUBCOHORT,
    candidate_coverage_ok_v55,
    derived_features_from_bundle_v55,
)
from src.route_research_feature_review_v47 import CausalFeatureRowV47


def _window(seconds, *, events, buys, sells, ub, us, repeated=None):
    return SimpleNamespace(
        window_seconds=seconds,
        event_count=events,
        buy_count=buys,
        sell_count=sells,
        unique_buy_wallet_count=ub,
        unique_sell_wallet_count=us,
        repeated_wallet_event_share_pct=repeated,
    )


def _row(cohort: str, value):
    return CausalFeatureRowV47(
        acquisition_run_key=f"run-{cohort}",
        cohort=cohort,
        episode_key=f"episode-{cohort}-{value}",
        token_mint="token",
        episode_t0=100,
        research_decision_as_of=110,
        features={"candidate": value},
        feature_observed_at={"candidate": 110},
        labels={300: None, 900: None, 3600: None},
        outcome_statuses={300: "PROVIDER_ERROR", 900: "PROVIDER_ERROR", 3600: "PROVIDER_ERROR"},
    )


class RouteResearchEarlyOpportunityV55Tests(unittest.TestCase):
    def test_closed_feature_set_does_not_recycle_failed_raw_flow60_count(self):
        names = {item.name for item in FEATURE_DEFINITIONS_V55}
        self.assertNotIn("flow60_event_count", names)
        self.assertIn("flow10_vs_60_event_rate_ratio", names)
        self.assertIn("flow30_vs_300_event_rate_ratio", names)

    def test_derived_features_use_only_snapshot_windows(self):
        bundle = SimpleNamespace(
            core=SimpleNamespace(
                flow_windows=(
                    _window(10, events=5, buys=4, sells=1, ub=4, us=1, repeated=20.0),
                    _window(30, events=9, buys=6, sells=3, ub=5, us=2, repeated=22.0),
                    _window(60, events=12, buys=7, sells=5, ub=6, us=4, repeated=25.0),
                    _window(300, events=30, buys=18, sells=12, ub=12, us=8, repeated=30.0),
                )
            )
        )
        features = derived_features_from_bundle_v55(bundle)
        self.assertEqual(features["flow10_event_count"], 5)
        self.assertAlmostEqual(features["flow10_vs_60_event_rate_ratio"], 2.5)
        self.assertAlmostEqual(features["flow30_vs_300_event_rate_ratio"], 3.0)
        self.assertAlmostEqual(features["flow10_buy_share_pct"], 80.0)
        self.assertAlmostEqual(features["flow60_buy_share_pct"], 100.0 * 7 / 12)
        self.assertEqual(features["flow30_wallet_direction_balance"], 3)
        self.assertEqual(features["flow60_wallet_direction_balance"], 2)
        self.assertEqual(features["flow30_repeated_wallet_event_share_pct"], 22.0)

    def test_rate_ratio_is_explicitly_missing_without_long_window_support(self):
        bundle = SimpleNamespace(
            core=SimpleNamespace(
                flow_windows=(
                    _window(10, events=1, buys=1, sells=0, ub=1, us=0),
                    _window(30, events=1, buys=1, sells=0, ub=1, us=0),
                    _window(60, events=0, buys=0, sells=0, ub=0, us=0),
                    _window(300, events=0, buys=0, sells=0, ub=0, us=0),
                )
            )
        )
        features = derived_features_from_bundle_v55(bundle)
        self.assertIsNone(features["flow10_vs_60_event_rate_ratio"])
        self.assertIsNone(features["flow30_vs_300_event_rate_ratio"])

    def test_candidate_coverage_requires_each_subcohort(self):
        rows = tuple(_row("A", 1) for _ in range(8)) + tuple(_row("A", None) for _ in range(2))
        rows += tuple(_row("B", 1) for _ in range(8)) + tuple(_row("B", None) for _ in range(2))
        self.assertEqual(V55_MIN_FEATURE_COVERAGE_PCT_PER_SUBCOHORT, 80.0)
        self.assertTrue(candidate_coverage_ok_v55(rows=rows, feature_name="candidate"))

        rows_bad = tuple(_row("A", 1) for _ in range(8)) + tuple(_row("A", None) for _ in range(2))
        rows_bad += tuple(_row("B", 1) for _ in range(7)) + tuple(_row("B", None) for _ in range(3))
        self.assertFalse(candidate_coverage_ok_v55(rows=rows_bad, feature_name="candidate"))


if __name__ == "__main__":
    unittest.main()
