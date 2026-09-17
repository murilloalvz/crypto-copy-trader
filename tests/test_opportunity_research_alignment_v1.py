from __future__ import annotations

import unittest

from src.opportunity_research_alignment_v1 import (
    DECISION_DIMENSIONS_V1,
    HYPOTHESIS_OVERRIDES_V1,
    REUSE_CONTRACT_V1,
    ROBINHOOD_PLAN_V1,
    SCIENTIFIC_GUARDRAILS_V1,
    SOLANA_PLAN_V1,
    TRACKS_V1,
    alignment_report_v1,
    validate_alignment_v1,
)


class OpportunityResearchAlignmentV1Tests(unittest.TestCase):
    def test_alignment_validates_and_keeps_tracks_independent(self):
        validate_alignment_v1()
        self.assertEqual(len(DECISION_DIMENSIONS_V1), len(set(DECISION_DIMENSIONS_V1)))
        self.assertEqual(
            TRACKS_V1["convergence"],
            "BLOCKED_UNTIL_INDEPENDENT_EVIDENCE_SUPPORTS_IT",
        )

    def test_solana_finishes_routeable_edge_before_new_selector_work(self):
        self.assertEqual(SOLANA_PLAN_V1[0].stage_id, "sol_routeable_edge_discovery_v2")
        self.assertEqual(SOLANA_PLAN_V1[1].stage_id, "sol_coordination_organicity_discovery_v0")
        self.assertFalse(any("selector_threshold" in stage.stage_id for stage in SOLANA_PLAN_V1))

    def test_robinhood_starts_with_sequencer_signal_plane_and_chain_native_copyability(self):
        self.assertEqual(ROBINHOOD_PLAN_V1[0].stage_id, "rh_sequencer_feed_signal_plane_v1")
        self.assertEqual(ROBINHOOD_PLAN_V1[2].stage_id, "rh_protocol_opening_copyability_v0")
        self.assertEqual(ROBINHOOD_PLAN_V1[0].plane, "signal")
        self.assertEqual(ROBINHOOD_PLAN_V1[2].dimension, "copyability_execution")

    def test_cross_chain_reuse_is_methodology_not_thresholds(self):
        blocked = set(REUSE_CONTRACT_V1["must_not_be_inherited_across_chains"])
        self.assertIn("selector_thresholds", blocked)
        self.assertIn("fees_slippage_and_exit_rules", blocked)
        self.assertIn("priority_fee_logic", blocked)
        self.assertEqual(
            REUSE_CONTRACT_V1["robinhood_sources"]["sequencer_head"],
            "b99b6cb96a7c9c9db46b706816cdc3379f19ecdf",
        )

    def test_coordination_override_requires_entity_adjusted_discovery_without_threshold(self):
        hypothesis = HYPOTHESIS_OVERRIDES_V1["H_ORGANIC_VS_COORDINATED_V0"]
        self.assertEqual(
            hypothesis["status"],
            "ENTITY_ADJUSTED_CAUSAL_DISCOVERY_REQUIRED_NOT_SELECTOR_READY",
        )
        self.assertIsNone(hypothesis["threshold"])
        self.assertIn("unique_buy_entity_count", hypothesis["candidate_features"])
        self.assertIn("coordination_compression_ratio", hypothesis["candidate_features"])

    def test_ml_and_provider_leakage_remain_blocked(self):
        guards = set(SCIENTIFIC_GUARDRAILS_V1)
        self.assertIn("NO_ML_OR_AUTOTUNING_BEFORE_ADEQUATE_INDEPENDENT_ROUTE_USABLE_LABELS", guards)
        self.assertIn("NO_PROVIDER_OR_POSTDECISION_EXECUTION_FIELD_AS_MARKET_SELECTOR_FEATURE", guards)
        self.assertIn("ROBINHOOD_OPENING_TAX_AND_PROTOCOL_CAPS_ARE_COPYABILITY_NOT_ALPHA", guards)

    def test_report_is_machine_readable(self):
        report = alignment_report_v1()
        self.assertEqual(report["version"], "opportunity_research_alignment_v1")
        self.assertEqual(report["solana_plan"][0]["stage_id"], "sol_routeable_edge_discovery_v2")
        self.assertEqual(report["robinhood_plan"][0]["stage_id"], "rh_sequencer_feed_signal_plane_v1")


if __name__ == "__main__":
    unittest.main()
