from __future__ import annotations

from dataclasses import dataclass
import math
import unittest

from src.market_first_feature_discovery_v1 import (
    FEATURE_IDS,
    acceleration_features_v1,
    feature_definitions_v1,
    liquidity_exitability_discovery_status_v1,
)
from src.opportunity_feature_matrix_v0 import (
    TRACK_MARKET_FIRST,
    assert_selector_feature_eligible_v0,
    feature_spec_v0,
)


@dataclass(frozen=True)
class Row:
    observed_wall_ns: int
    event_key: str
    side: str
    quote_amount_raw: int
    quote_reserve_raw: int
    wallet_key: str | None


class MarketFirstFeatureDiscoveryV1Tests(unittest.TestCase):
    def setUp(self):
        self.anchor = 1_000_000_000
        self.cutoff = self.anchor + 5_000_000_000
        self.rows = [
            Row(self.anchor + 1_000_000_000, "e1", "buy", 100, 1000, "A"),
            Row(self.anchor + 2_000_000_000, "e2", "sell", 50, 1000, "B"),
            Row(self.anchor + 3_000_000_000, "e3", "buy", 200, 1000, "C"),
            Row(self.anchor + 4_000_000_000, "e4", "buy", 100, 1000, "D"),
        ]

    def test_two_half_acceleration_semantics_are_exact(self):
        features = acceleration_features_v1(
            self.rows,
            anchor_wall_ns=self.anchor,
            cutoff_wall_ns=self.cutoff,
        )
        self.assertAlmostEqual(features["mf_event_rate_acceleration_per_s2"], 0.0)
        self.assertAlmostEqual(features["mf_buy_event_rate_acceleration_per_s2"], 0.16)
        self.assertAlmostEqual(features["mf_unique_buy_wallet_arrival_acceleration_per_s2"], 0.16)
        self.assertAlmostEqual(features["mf_signed_flow_acceleration_per_s2"], 0.04)
        self.assertAlmostEqual(
            features["mf_directional_efficiency_delta_late_minus_early"],
            2.0 / 3.0,
        )
        self.assertAlmostEqual(
            features["mf_top_wallet_gross_share_delta_pct_points_late_minus_early"],
            0.0,
        )

    def test_future_row_after_cutoff_cannot_change_features(self):
        baseline = acceleration_features_v1(
            self.rows,
            anchor_wall_ns=self.anchor,
            cutoff_wall_ns=self.cutoff,
        )
        future = Row(
            self.cutoff + 1_000_000_000,
            "future",
            "buy",
            999999999,
            1000,
            "FUTURE",
        )
        with_future = acceleration_features_v1(
            [*self.rows, future],
            anchor_wall_ns=self.anchor,
            cutoff_wall_ns=self.cutoff,
        )
        self.assertEqual(baseline, with_future)

    def test_wallet_dynamics_fail_closed_when_identity_is_incomplete(self):
        rows = list(self.rows)
        rows[2] = Row(
            rows[2].observed_wall_ns,
            rows[2].event_key,
            rows[2].side,
            rows[2].quote_amount_raw,
            rows[2].quote_reserve_raw,
            None,
        )
        features = acceleration_features_v1(
            rows,
            anchor_wall_ns=self.anchor,
            cutoff_wall_ns=self.cutoff,
        )
        self.assertIsNone(features["mf_unique_buy_wallet_arrival_acceleration_per_s2"])
        self.assertIsNone(features["mf_top_wallet_gross_share_delta_pct_points_late_minus_early"])
        self.assertIsNotNone(features["mf_event_rate_acceleration_per_s2"])
        self.assertIsNotNone(features["mf_signed_flow_acceleration_per_s2"])

    def test_empty_window_is_missing_not_zero_signal(self):
        features = acceleration_features_v1(
            [],
            anchor_wall_ns=self.anchor,
            cutoff_wall_ns=self.cutoff,
        )
        self.assertEqual(set(features), set(FEATURE_IDS))
        self.assertTrue(all(value is None for value in features.values()))

    def test_non_five_second_window_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "frozen 5s"):
            acceleration_features_v1(
                self.rows,
                anchor_wall_ns=self.anchor,
                cutoff_wall_ns=self.cutoff + 1,
            )

    def test_discovery_features_are_registered_but_forbidden_in_selectors(self):
        definitions = feature_definitions_v1()
        self.assertEqual(set(definitions), set(FEATURE_IDS))
        for feature_id in FEATURE_IDS:
            spec = feature_spec_v0(feature_id)
            self.assertEqual(spec.track, TRACK_MARKET_FIRST)
            self.assertTrue(spec.diagnostic_only)
            self.assertFalse(spec.selector_eligible)
            self.assertFalse(spec.execution_only)
            self.assertFalse(spec.future_dependent)
            with self.assertRaisesRegex(ValueError, "diagnostic-only"):
                assert_selector_feature_eligible_v0(
                    feature_id,
                    selector_track=TRACK_MARKET_FIRST,
                )

    def test_liquidity_exitability_remains_blocked_without_execution_leakage(self):
        status = liquidity_exitability_discovery_status_v1()
        self.assertEqual(status["status"], "BLOCKED_NO_RELIABLE_CAUSAL_EXITABILITY_FEATURE")
        self.assertFalse(status["selector_eligible"])
        text = str(status["why_not_promoted"])
        self.assertIn("Provider route availability", text)
        self.assertIn("forbidden", text)


if __name__ == "__main__":
    unittest.main()
