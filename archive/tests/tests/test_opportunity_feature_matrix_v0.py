from __future__ import annotations

from pathlib import Path
import unittest

from src.launch_burst_sniper_v1 import EXPECTED_POLICY_HASH, load_sniper_policy_v1
from src.opportunity_feature_matrix_v0 import (
    TRACK_MARKET_FIRST,
    assert_selector_feature_eligible_v0,
    feature_matrix_rows_v0,
    feature_spec_v0,
)
from src.social_event_evidence_v0 import social_event_evidence_from_mapping_v0


SNIPER_POLICY = Path("benchmarks") / "launch_burst_sniper_v1" / "sniper_policy_v1.frozen.json"
SNIPER_FEATURES = {
    "signed_flow_over_event_reserve",
    "event_count",
    "directional_flow_efficiency",
    "wallet_identity_coverage_pct",
    "wallet_gross_flow_coverage_pct",
    "unique_buy_wallet_count",
    "top_wallet_gross_flow_share_worst_case_pct",
    "transaction_identity_coverage_pct",
    "unique_transaction_count",
}
REQUIRED_MATRIX_FIELDS = {
    "feature_id",
    "track",
    "category",
    "description",
    "causal_source",
    "earliest_causal_availability",
    "selector_eligible",
    "diagnostic_only",
    "execution_only",
    "future_dependent",
    "missing_data_policy",
    "normalization_scope",
    "chain_scope",
    "scientific_status",
    "hypothesis_role",
}


class OpportunityFeatureMatrixV0Tests(unittest.TestCase):
    def test_matrix_is_machine_readable_and_has_required_fields(self):
        rows = feature_matrix_rows_v0()
        self.assertGreaterEqual(len(rows), len(SNIPER_FEATURES))
        for row in rows:
            self.assertEqual(set(row), REQUIRED_MATRIX_FIELDS)

    def test_sniper_v1_primary_features_are_registered_market_first_and_selector_eligible(self):
        policy = load_sniper_policy_v1(SNIPER_POLICY)
        self.assertEqual(policy["policy_hash_sha256"], EXPECTED_POLICY_HASH)
        policy_features = {
            str(predicate["feature"])
            for predicate in policy["primary_selector"]["predicates"]
        }
        self.assertEqual(policy_features, SNIPER_FEATURES)
        for feature_id in policy_features:
            spec = feature_spec_v0(feature_id)
            self.assertEqual(spec.track, TRACK_MARKET_FIRST)
            self.assertTrue(spec.selector_eligible)
            self.assertFalse(spec.diagnostic_only)
            self.assertFalse(spec.execution_only)
            self.assertFalse(spec.future_dependent)
            self.assertEqual(spec.earliest_causal_availability, "at_or_before_frozen_5s_decision_cutoff")

    def test_future_leakage_is_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "future-dependent"):
            assert_selector_feature_eligible_v0(
                "future_return_60s",
                selector_track=TRACK_MARKET_FIRST,
            )

    def test_execution_leakage_is_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "execution-only"):
            assert_selector_feature_eligible_v0(
                "provider_price_impact_pct_points",
                selector_track=TRACK_MARKET_FIRST,
            )

    def test_diagnostic_leakage_is_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "diagnostic-only"):
            assert_selector_feature_eligible_v0(
                "causal_capture_sha256",
                selector_track=TRACK_MARKET_FIRST,
            )

    def test_track_leakage_is_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "track leakage"):
            assert_selector_feature_eligible_v0(
                "observed_event_count",
                selector_track=TRACK_MARKET_FIRST,
            )

    def test_unknown_selector_feature_is_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "unregistered selector feature"):
            assert_selector_feature_eligible_v0(
                "totally_unknown_feature",
                selector_track=TRACK_MARKET_FIRST,
            )

    def test_published_at_cannot_backdate_social_causal_availability(self):
        item = social_event_evidence_from_mapping_v0(
            {
                "source_kind": "social_post",
                "source_key": "source:alice",
                "source_event_id": "post-backdated",
                "event_kind": "mention",
                "observed_wall_ns": 1_000,
                "published_at_ns": 1,
                "token_mint": "TOKEN",
                "token_mapping_observed_wall_ns": 1_200,
            }
        )
        self.assertEqual(item.published_at_ns, 1)
        self.assertEqual(item.causal_available_wall_ns, 1_200)
        self.assertNotEqual(item.causal_available_wall_ns, item.published_at_ns)


if __name__ == "__main__":
    unittest.main()
