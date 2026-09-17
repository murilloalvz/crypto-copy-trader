from __future__ import annotations

from dataclasses import dataclass
import unittest

from src.coordination_entity_intelligence_v0 import (
    CAUSAL_FEATURE_IDS,
    POSTDECISION_FEATURE_IDS,
    DeployerHistoryEvidenceV0,
    EntityLinkEvidenceV0,
    FundingRelationEvidenceV0,
    coordination_features_v0,
    postdecision_coordination_outcomes_v0,
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


class CoordinationEntityIntelligenceV0Tests(unittest.TestCase):
    def setUp(self):
        self.cutoff = 10_000
        self.rows = [
            Row(1_000, "1", "buy", 100, 1_000, "A"),
            Row(2_000, "2", "buy", 100, 1_000, "B"),
            Row(3_000, "3", "buy", 100, 1_000, "C"),
            Row(4_000, "4", "sell", 50, 1_000, "B"),
        ]

    def test_entity_adjusted_breadth_concentration_and_churn_are_exact(self):
        link = EntityLinkEvidenceV0("A", "B", 500, "shared_control", "unit")
        result = coordination_features_v0(
            self.rows,
            decision_cutoff_wall_ns=self.cutoff,
            entity_links=[link],
        )
        features = result["features"]
        self.assertEqual(result["raw_unique_buy_wallet_count"], 3)
        self.assertEqual(features["mf_unique_buy_entity_count"], 2)
        self.assertAlmostEqual(features["mf_coordination_compression_ratio"], 1.5)
        self.assertAlmostEqual(
            features["mf_top_entity_gross_flow_share_pct"],
            100.0 * 0.25 / 0.35,
        )
        self.assertAlmostEqual(features["mf_entity_churn_proxy"], 0.10 / 0.35)
        self.assertFalse(result["selector_eligible"])
        self.assertFalse(result["threshold_defined"])

    def test_entity_link_observed_after_decision_is_ignored(self):
        future_link = EntityLinkEvidenceV0("A", "B", 20_000, "future_relation", "unit")
        result = coordination_features_v0(
            self.rows,
            decision_cutoff_wall_ns=self.cutoff,
            entity_links=[future_link],
        )
        self.assertEqual(result["features"]["mf_unique_buy_entity_count"], 3)
        self.assertEqual(result["accepted_causal_entity_link_count"], 0)

    def test_funding_relation_does_not_automatically_merge_entities(self):
        relation = FundingRelationEvidenceV0("FUNDER", "A", 500, "unit")
        result = coordination_features_v0(
            self.rows,
            decision_cutoff_wall_ns=self.cutoff,
            funding_relations=[relation],
        )
        self.assertEqual(result["features"]["mf_unique_buy_entity_count"], 3)
        self.assertAlmostEqual(
            result["features"]["mf_funding_linked_buy_wallet_share_pct"],
            100.0 / 3.0,
        )

    def test_deployer_history_is_prior_only_and_future_history_is_not_backdated(self):
        evidence = [
            DeployerHistoryEvidenceV0("D", 500, 400, 7, "unit"),
            DeployerHistoryEvidenceV0("D", 5_000, 20_000, 99, "future_history"),
        ]
        result = coordination_features_v0(
            self.rows,
            decision_cutoff_wall_ns=self.cutoff,
            deployer_wallet="D",
            deployer_history=evidence,
        )
        self.assertEqual(result["features"]["mf_deployer_prior_launch_count"], 7)

    def test_missing_wallet_identity_fails_closed_for_entity_features(self):
        rows = [*self.rows, Row(4_500, "5", "buy", 10, 1_000, None)]
        result = coordination_features_v0(rows, decision_cutoff_wall_ns=self.cutoff)
        self.assertIsNone(result["features"]["mf_unique_buy_entity_count"])
        self.assertIsNone(result["features"]["mf_top_entity_gross_flow_share_pct"])
        self.assertIsNone(result["raw_unique_buy_wallet_count"])

    def test_followup_retention_and_sell_pressure_are_explicitly_future_dependent(self):
        link = EntityLinkEvidenceV0("A", "B", 500, "same_entity", "unit")
        followup = [
            Row(11_000, "f1", "buy", 50, 1_000, "A"),
            Row(12_000, "f2", "sell", 150, 1_000, "C"),
        ]
        result = postdecision_coordination_outcomes_v0(
            self.rows,
            followup,
            decision_cutoff_wall_ns=self.cutoff,
            followup_cutoff_wall_ns=20_000,
            entity_links=[link],
        )
        self.assertAlmostEqual(
            result["features"]["mf_early_buyer_retention_ratio_followup"],
            0.5,
        )
        self.assertAlmostEqual(
            result["features"]["mf_sell_pressure_followup_ratio"],
            0.75,
        )
        self.assertTrue(result["future_dependent"])
        self.assertFalse(result["selector_eligible"])

    def test_causal_coordination_features_are_registered_diagnostic_only(self):
        for feature_id in CAUSAL_FEATURE_IDS:
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

    def test_postdecision_features_are_registered_future_only_and_blocked(self):
        for feature_id in POSTDECISION_FEATURE_IDS:
            spec = feature_spec_v0(feature_id)
            self.assertEqual(spec.track, TRACK_MARKET_FIRST)
            self.assertTrue(spec.diagnostic_only)
            self.assertFalse(spec.selector_eligible)
            self.assertFalse(spec.execution_only)
            self.assertTrue(spec.future_dependent)
            with self.assertRaisesRegex(ValueError, "future-dependent"):
                assert_selector_feature_eligible_v0(
                    feature_id,
                    selector_track=TRACK_MARKET_FIRST,
                )


if __name__ == "__main__":
    unittest.main()
