from __future__ import annotations

import copy
import unittest

from src.opportunity_edge_registry_v0 import (
    load_edge_registry_v0,
    selector_candidates_v0,
    validate_edge_registry_v0,
)


class OpportunityEdgeRegistryV0Tests(unittest.TestCase):
    def setUp(self):
        self.registry = load_edge_registry_v0()

    def _signal(self, signal_id: str):
        return next(row for row in self.registry["signals"] if row["signal_id"] == signal_id)

    def test_registry_loads_and_preserves_independent_research_planes(self):
        self.assertEqual(self.registry["selector_policy_effect"], "NO_POLICY_CHANGE")
        self.assertEqual(self.registry["weighted_score_policy"], "NONE_V0")
        self.assertEqual(self.registry["research_planes"]["market_first"], "INDEPENDENT")
        self.assertEqual(self.registry["research_planes"]["social_event_first"], "INDEPENDENT")
        self.assertEqual(
            self.registry["research_planes"]["convergence"],
            "SEPARATE_PREREGISTRATION_REQUIRED",
        )

    def test_market_selector_candidates_exclude_execution_and_outcomes(self):
        candidates = selector_candidates_v0(self.registry, plane="MARKET_FIRST")
        self.assertTrue(candidates)
        self.assertTrue(all(row["plane"] == "MARKET_FIRST" for row in candidates))
        self.assertTrue(all(row["eligible_pre_entry"] is True for row in candidates))
        ids = {row["signal_id"] for row in candidates}
        self.assertNotIn("execution.provider_price_impact", ids)
        self.assertNotIn("outcome.future_route_return", ids)

    def test_execution_fields_are_explicitly_isolated_from_opportunity_selection(self):
        signal = self._signal("execution.provider_price_impact")
        self.assertEqual(signal["plane"], "EXECUTION")
        self.assertFalse(signal["eligible_pre_entry"])
        self.assertEqual(signal["current_status"], "FORBIDDEN_AS_SELECTOR")
        self.assertEqual(signal["selector_role"], "EXECUTION_ADMISSION")

    def test_outcome_fields_are_never_selector_inputs(self):
        for signal_id in (
            "outcome.future_route_return",
            "outcome.route_shadow_pnl",
            "outcome.realized_pnl",
        ):
            signal = self._signal(signal_id)
            self.assertEqual(signal["plane"], "OUTCOME_ONLY")
            self.assertFalse(signal["eligible_pre_entry"])
            self.assertEqual(signal["current_status"], "FORBIDDEN_AS_SELECTOR")
            self.assertEqual(signal["selector_role"], "OUTCOME_ONLY")

    def test_validator_rejects_execution_field_promoted_into_selector(self):
        mutated = copy.deepcopy(self.registry)
        signal = next(row for row in mutated["signals"] if row["signal_id"] == "execution.route_availability")
        signal["eligible_pre_entry"] = True
        signal["current_status"] = "AVAILABLE"
        signal["selector_role"] = "PRE_ENTRY_SELECTOR_CANDIDATE"
        with self.assertRaisesRegex(ValueError, "execution signal"):
            validate_edge_registry_v0(mutated)

    def test_validator_rejects_future_return_disguised_as_market_selector(self):
        mutated = copy.deepcopy(self.registry)
        mutated["signals"].append(
            {
                "signal_id": "market.future_return_60s",
                "family": "bad_test",
                "definition": "test",
                "plane": "MARKET_FIRST",
                "causal_source_time": "MARKET_EVIDENCE_WINDOW_CUTOFF",
                "eligible_pre_entry": True,
                "current_status": "AVAILABLE",
                "selector_role": "PRE_ENTRY_SELECTOR_CANDIDATE",
                "coverage_requirement": "test",
                "adversarial_risk": "test",
                "evidence_level": "L1_CAUSALLY_MEASURABLE",
                "research_stage": "test",
                "promotion_gate": "test",
                "notes": "test",
            }
        )
        with self.assertRaisesRegex(ValueError, "outcome-bearing"):
            validate_edge_registry_v0(mutated)

    def test_validator_rejects_published_metadata_as_causal_clock(self):
        mutated = copy.deepcopy(self.registry)
        signal = next(row for row in mutated["signals"] if row["signal_id"] == "social.observed_event_count")
        signal["causal_source_time"] = "published_at_ns"
        with self.assertRaisesRegex(ValueError, "published_at"):
            validate_edge_registry_v0(mutated)

    def test_external_bot_heuristics_are_not_mislabeled_as_proven_edge(self):
        for signal_id in (
            "supply.deployer_dev_history",
            "supply.top_holder_concentration",
            "supply.insider_bundle_concentration",
            "wallet.past_only_reputation",
            "wallet.common_funder_cluster",
            "social.source_past_only_reputation",
        ):
            signal = self._signal(signal_id)
            self.assertIn(signal["current_status"], {"NEEDS_COLLECTION", "DERIVABLE"})
            self.assertIn(signal["evidence_level"], {"L0_EXTERNAL_HEURISTIC", "L1_CAUSALLY_MEASURABLE"})


if __name__ == "__main__":
    unittest.main()
