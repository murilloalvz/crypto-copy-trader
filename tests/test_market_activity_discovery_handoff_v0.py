import unittest

from src.market_activity_discovery_handoff_v0 import (
    MARKET_ACTIVITY_DISCOVERY_HANDOFF_VERSION,
    build_market_activity_discovery_handoff_v0,
)
from src.market_opportunity_episode_store import MarketOpportunityEpisode


class MarketActivityDiscoveryHandoffV0Tests(unittest.TestCase):
    def _episode(self, **overrides):
        values = dict(
            episode_key="EP1",
            acquisition_run_key="RUN1",
            token_mint="MINT_A",
            first_trigger_key="TRIGGER1",
            first_trigger_kind="market_radar",
            first_trigger_direction="up",
            first_trigger_chain_time=1200,
            first_trigger_observed_at=1000,
            episode_closes_at=1060,
            decision_as_of=None,
        )
        values.update(overrides)
        return MarketOpportunityEpisode(**values)

    def test_first_trigger_builds_stable_first_trigger_clock_envelope(self):
        episode = self._episode()
        result = build_market_activity_discovery_handoff_v0(
            episode=episode,
            trigger_key="TRIGGER1",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.method_version, MARKET_ACTIVITY_DISCOVERY_HANDOFF_VERSION)
        self.assertEqual(result.decision_as_of, 1000)
        self.assertEqual(result.chain_as_of, 1200)
        self.assertEqual(result.token_mint, "MINT_A")
        self.assertIn("RUN1", result.handoff_key)
        self.assertIn("EP1", result.handoff_key)

    def test_exact_replay_produces_identical_envelope_even_after_episode_freeze(self):
        first = build_market_activity_discovery_handoff_v0(
            episode=self._episode(decision_as_of=None),
            trigger_key="TRIGGER1",
        )
        replay = build_market_activity_discovery_handoff_v0(
            episode=self._episode(decision_as_of=1000),
            trigger_key="TRIGGER1",
        )
        self.assertEqual(first, replay)

    def test_continuation_trigger_does_not_create_research_handoff(self):
        result = build_market_activity_discovery_handoff_v0(
            episode=self._episode(),
            trigger_key="TRIGGER2",
        )
        self.assertIsNone(result)

    def test_chain_clock_ahead_of_local_clock_is_valid(self):
        result = build_market_activity_discovery_handoff_v0(
            episode=self._episode(first_trigger_chain_time=9999, first_trigger_observed_at=1000),
            trigger_key="TRIGGER1",
        )
        self.assertEqual(result.decision_as_of, 1000)
        self.assertEqual(result.chain_as_of, 9999)

    def test_empty_trigger_key_rejected(self):
        with self.assertRaises(ValueError):
            build_market_activity_discovery_handoff_v0(
                episode=self._episode(),
                trigger_key=" ",
            )


if __name__ == "__main__":
    unittest.main()
