import unittest

from src.market_activity_dynamics_v0 import build_market_activity_dynamics_v0
from src.market_episode_research_snapshot import (
    MARKET_EPISODE_RESEARCH_SNAPSHOT_VERSION,
    MarketRegimeResearchFactsV0,
    build_market_episode_research_snapshot_v0,
)
from src.market_intelligence_baseline import build_market_intelligence_baseline_v0
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.market_protocol_facts import build_market_protocol_facts_v0
from src.opportunity_snapshot_core import build_opportunity_snapshot_core_v1
from src.pump_creation_mode_facts import build_pump_creation_mode_facts_v0


class MarketEpisodeResearchSnapshotV0Tests(unittest.TestCase):
    def _episode(self, **overrides):
        values = dict(
            episode_key="EP1",
            acquisition_run_key="RUN1",
            token_mint="MINT_A",
            first_trigger_key="TR1",
            first_trigger_kind="market_radar",
            first_trigger_direction="up",
            first_trigger_chain_time=100,
            first_trigger_observed_at=101,
            episode_closes_at=161,
            decision_as_of=110,
        )
        values.update(overrides)
        return MarketOpportunityEpisode(**values)

    def _baseline(self, *, token_mint="MINT_A", as_of=110):
        protocol = build_market_protocol_facts_v0(
            token_mint=token_mint,
            as_of=as_of,
        )
        core = build_opportunity_snapshot_core_v1(
            token_mint=token_mint,
            as_of=as_of,
            flow_observations=(),
            quotes=(),
            flow_windows_seconds=(30,),
        )
        return build_market_intelligence_baseline_v0(protocol=protocol, snapshot=core)

    def _activity(self, *, token_mint="MINT_A", as_of=110, chain_as_of=None):
        core = build_opportunity_snapshot_core_v1(
            token_mint=token_mint,
            as_of=as_of,
            chain_as_of=chain_as_of,
            flow_observations=(),
            quotes=(),
            flow_windows_seconds=(10, 30, 60, 300),
        )
        return build_market_activity_dynamics_v0(core)

    def _mode(self, *, token_mint="MINT_A", as_of=110):
        return build_pump_creation_mode_facts_v0(
            token_mint=token_mint,
            as_of=as_of,
        )

    def _regime(self, **overrides):
        values = dict(
            method_version="covered_page_hinkley_v0",
            detector="river.PageHinkley",
            metric="event_count",
            detection_count=1,
            latest_detection_chain_time=108,
            observed_bins_consumed=100,
            missing_bins_skipped=0,
            detector_resets_due_to_missing=0,
            contiguous_segments=1,
            data_quality_flags=(),
        )
        values.update(overrides)
        return MarketRegimeResearchFactsV0(**values)

    def test_composes_frozen_market_first_episode(self):
        result = build_market_episode_research_snapshot_v0(
            episode=self._episode(),
            market_intelligence=self._baseline(),
            pump_creation_mode=self._mode(),
            activity_dynamics=self._activity(),
            regime=self._regime(),
        )
        self.assertEqual(result.method_version, MARKET_EPISODE_RESEARCH_SNAPSHOT_VERSION)
        self.assertEqual(result.decision_as_of, 110)
        self.assertEqual(result.token_mint, "MINT_A")
        self.assertEqual(result.regime.detection_count, 1)
        self.assertEqual(result.activity_dynamics.token_mint, "MINT_A")
        self.assertIn("pump_create_v2_mode_not_observed", result.data_quality_flags)

    def test_requires_frozen_decision_as_of(self):
        with self.assertRaises(ValueError):
            build_market_episode_research_snapshot_v0(
                episode=self._episode(decision_as_of=None),
                market_intelligence=self._baseline(),
                pump_creation_mode=self._mode(),
            )

    def test_rejects_cross_token_evidence(self):
        with self.assertRaises(ValueError):
            build_market_episode_research_snapshot_v0(
                episode=self._episode(),
                market_intelligence=self._baseline(token_mint="MINT_B"),
                pump_creation_mode=self._mode(),
            )

    def test_rejects_mismatched_local_as_of(self):
        with self.assertRaises(ValueError):
            build_market_episode_research_snapshot_v0(
                episode=self._episode(),
                market_intelligence=self._baseline(as_of=109),
                pump_creation_mode=self._mode(),
            )

    def test_rejects_mismatched_activity_t0(self):
        with self.assertRaises(ValueError):
            build_market_episode_research_snapshot_v0(
                episode=self._episode(),
                market_intelligence=self._baseline(),
                pump_creation_mode=self._mode(),
                activity_dynamics=self._activity(as_of=109),
            )

    def test_regime_chain_clock_ahead_of_local_decision_clock_is_valid(self):
        result = build_market_episode_research_snapshot_v0(
            episode=self._episode(),
            market_intelligence=self._baseline(),
            pump_creation_mode=self._mode(),
            regime=self._regime(latest_detection_chain_time=111),
        )
        self.assertEqual(result.decision_as_of, 110)
        self.assertEqual(result.regime.latest_detection_chain_time, 111)

    def test_missing_regime_is_explicit_not_zero_or_false(self):
        result = build_market_episode_research_snapshot_v0(
            episode=self._episode(),
            market_intelligence=self._baseline(),
            pump_creation_mode=self._mode(),
            regime=None,
        )
        self.assertIsNone(result.regime)
        self.assertIn("regime_evidence_not_available", result.data_quality_flags)

    def test_missing_activity_dynamics_is_explicit_not_reconstructed(self):
        result = build_market_episode_research_snapshot_v0(
            episode=self._episode(),
            market_intelligence=self._baseline(),
            pump_creation_mode=self._mode(),
            activity_dynamics=None,
        )
        self.assertIsNone(result.activity_dynamics)
        self.assertIn("activity_dynamics_not_available", result.data_quality_flags)

    def test_output_has_no_outcome_score_or_social_fields(self):
        result = build_market_episode_research_snapshot_v0(
            episode=self._episode(),
            market_intelligence=self._baseline(),
            pump_creation_mode=self._mode(),
            activity_dynamics=self._activity(),
        )
        forbidden = {
            "outcome",
            "score",
            "confidence",
            "recommendation",
            "take",
            "skip",
            "social",
        }
        self.assertTrue(forbidden.isdisjoint(result.__dataclass_fields__))


if __name__ == "__main__":
    unittest.main()
