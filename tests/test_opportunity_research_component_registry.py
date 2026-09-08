import unittest

from src.opportunity_research_component_registry import (
    assert_components_allowed_in_preentry_selection,
    get_research_component_spec,
)


class OpportunityResearchComponentRegistryTests(unittest.TestCase):
    def test_current_shared_preentry_components_are_allowed(self):
        assert_components_allowed_in_preentry_selection(
            (
                "movement_intensity_direction",
                "participant_distribution",
                "temporal_flow_structure",
                "wallet_convergence",
                "token_hazard_integrity",
            )
        )

    def test_exit_geometry_is_forbidden_in_preentry_selection(self):
        with self.assertRaisesRegex(ValueError, "market_first_exit_geometry"):
            assert_components_allowed_in_preentry_selection(("market_first_exit_geometry",))

    def test_route_executability_stays_a_separate_gate(self):
        spec = get_research_component_spec("route_executability")
        self.assertEqual(spec.phase, "execution_gate")
        self.assertFalse(spec.preentry_selection_eligible)

    def test_direct_funding_requires_separate_protocol_before_selection(self):
        spec = get_research_component_spec("direct_funding_relationship")
        self.assertFalse(spec.preentry_selection_eligible)
        self.assertIn("does not prove", spec.causal_boundary)

    def test_pons_components_are_chain_specific_not_solana_thresholds(self):
        lifecycle = get_research_component_spec("pons_lifecycle_progress")
        launch = get_research_component_spec("pons_launch_quality")
        self.assertEqual(lifecycle.chain_scope, "robinhood_chain_pons")
        self.assertEqual(launch.chain_scope, "robinhood_chain_pons")
        self.assertFalse(lifecycle.preentry_selection_eligible)
        self.assertFalse(launch.preentry_selection_eligible)

    def test_duplicate_components_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate research component"):
            assert_components_allowed_in_preentry_selection(
                ("participant_distribution", "participant_distribution")
            )


if __name__ == "__main__":
    unittest.main()
