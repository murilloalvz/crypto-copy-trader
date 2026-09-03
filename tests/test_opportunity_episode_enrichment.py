import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import record_market_trade
from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.market_opportunity_radar import MarketTradeObservation
from src.opportunity_episode_enrichment import build_episode_enrichment_bundle
from src.opportunity_enrichment_store import (
    admit_opportunity_episode,
    complete_opportunity_enrichment,
    load_opportunity_enrichment_attempt,
)


class OpportunityEpisodeEnrichmentTests(unittest.TestCase):
    def test_bundle_uses_shared_market_flow_and_explicit_risk_missingness(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "enrichment.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = MarketOpportunityEpisode(
                    episode_key="episode",
                    acquisition_run_key="run",
                    token_mint="TOKEN",
                    first_trigger_key="trigger",
                    first_trigger_kind="activity_acceleration",
                    first_trigger_direction="upward_pressure",
                    first_trigger_chain_time=990,
                    first_trigger_observed_at=991,
                    episode_closes_at=1051,
                    decision_as_of=None,
                )
                for i in range(6):
                    record_market_trade(
                        acquisition_run_key="run",
                        event_key=f"event-{i}",
                        source_provider="pump_or_pumpswap",
                        observation=MarketTradeObservation(
                            token_mint="TOKEN",
                            side="buy" if i < 5 else "sell",
                            chain_time=975 + i * 4,
                            observed_at=976 + i * 4,
                            wallet_address=f"W{i}",
                            venue="pump_swap" if i % 2 else "pump_bonding_curve",
                            transaction_key=f"tx-{i}",
                        ),
                    )
                bundle = build_episode_enrichment_bundle(episode=episode, as_of=1000)

        fast = next(item for item in bundle.core.flow_windows if item.window_seconds == 30)
        self.assertEqual(fast.event_count, 6)
        self.assertEqual(bundle.wallet_intelligence.participant_wallet_count, 6)
        self.assertEqual(bundle.risk.status, "not_integrated")
        self.assertIn("token_hazard_provider_not_integrated", bundle.risk.data_quality_flags)
        self.assertIn("no_execution_context", bundle.core.data_quality_flags)

    def test_episode_admission_is_idempotent_and_completion_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "admission.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self.assertTrue(
                    admit_opportunity_episode(
                        acquisition_run_key="run", episode_key="episode", admitted_at=100
                    )
                )
                self.assertFalse(
                    admit_opportunity_episode(
                        acquisition_run_key="run", episode_key="episode", admitted_at=101
                    )
                )
                completed = complete_opportunity_enrichment(
                    acquisition_run_key="run",
                    episode_key="episode",
                    completed_at=110,
                    decision_as_of=109,
                )
                loaded = load_opportunity_enrichment_attempt(
                    acquisition_run_key="run", episode_key="episode"
                )
                with self.assertRaises(ValueError):
                    complete_opportunity_enrichment(
                        acquisition_run_key="run",
                        episode_key="episode",
                        completed_at=111,
                        decision_as_of=109,
                    )

        self.assertEqual(completed.status, "COMPLETED")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.decision_as_of, 109)


if __name__ == "__main__":
    unittest.main()
