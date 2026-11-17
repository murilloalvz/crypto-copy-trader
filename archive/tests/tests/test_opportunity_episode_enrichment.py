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
from src.opportunity_onchain_hazard import OnchainMintHazardEvidence, TOKEN_PROGRAM


class OpportunityEpisodeEnrichmentTests(unittest.TestCase):
    @staticmethod
    def _episode() -> MarketOpportunityEpisode:
        return MarketOpportunityEpisode(
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

    @staticmethod
    def _record_flow() -> None:
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

    def test_bundle_uses_shared_market_flow_and_explicit_risk_missingness(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "enrichment.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._episode()
                self._record_flow()
                bundle = build_episode_enrichment_bundle(episode=episode, as_of=1000)

        fast = next(item for item in bundle.core.flow_windows if item.window_seconds == 30)
        self.assertEqual(fast.event_count, 6)
        self.assertEqual(bundle.wallet_intelligence.participant_wallet_count, 6)
        self.assertEqual(bundle.risk.status, "not_integrated")
        self.assertIn("token_hazard_provider_not_integrated", bundle.risk.data_quality_flags)
        self.assertIn("no_execution_context", bundle.core.data_quality_flags)

    def test_onchain_hazard_stays_provider_native_and_does_not_impersonate_holder_metric(self):
        evidence = OnchainMintHazardEvidence(
            episode_key="episode",
            token_mint="TOKEN",
            provider="solana_rpc_mint_hazard_v1",
            observed_at=998,
            context_slot=12345,
            status="AVAILABLE",
            token_program=TOKEN_PROGRAM,
            decimals=6,
            supply_raw="1000000000",
            mint_authority_present=False,
            freeze_authority_present=False,
            token_2022=False,
            extensions_present=(),
            top10_token_account_concentration_pct=76.0,
            largest_token_accounts_observed=20,
            largest_accounts_sum_raw="760000000",
            largest_accounts_context_slot=12346,
            largest_accounts_error_type=None,
            largest_accounts_error_message=None,
            data_quality_flags=(
                "largest_accounts_are_token_accounts_not_unique_owners",
                "top10_token_account_concentration_is_not_holder_concentration",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "enrichment.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._episode()
                self._record_flow()
                bundle = build_episode_enrichment_bundle(
                    episode=episode,
                    as_of=1000,
                    hazard_evidence=evidence,
                )

        self.assertEqual(bundle.risk.status, "AVAILABLE")
        self.assertEqual(bundle.risk.provider, "solana_rpc_mint_hazard_v1")
        self.assertFalse(bundle.risk.mint_authority_present)
        self.assertFalse(bundle.risk.freeze_authority_present)
        self.assertEqual(bundle.risk.top10_token_account_concentration_pct, 76.0)
        self.assertEqual(bundle.risk.largest_token_accounts_observed, 20)
        self.assertEqual(bundle.risk.mint_context_slot, 12345)
        self.assertEqual(bundle.risk.largest_accounts_context_slot, 12346)
        self.assertIsNone(bundle.risk.top10_pct)
        self.assertIsNone(bundle.risk.risk_score)
        self.assertIn(
            "top10_token_account_concentration_is_not_holder_concentration",
            bundle.risk.data_quality_flags,
        )

    def test_later_onchain_hazard_is_not_backfilled_into_earlier_as_of(self):
        evidence = OnchainMintHazardEvidence(
            episode_key="episode",
            token_mint="TOKEN",
            provider="solana_rpc_mint_hazard_v1",
            observed_at=1005,
            context_slot=12345,
            status="AVAILABLE",
            token_program=TOKEN_PROGRAM,
            decimals=6,
            supply_raw="1000000000",
            mint_authority_present=False,
            freeze_authority_present=False,
            token_2022=False,
            extensions_present=(),
            top10_token_account_concentration_pct=76.0,
            largest_token_accounts_observed=20,
            largest_accounts_sum_raw="760000000",
            largest_accounts_context_slot=12346,
            largest_accounts_error_type=None,
            largest_accounts_error_message=None,
            data_quality_flags=(),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "enrichment.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                episode = self._episode()
                bundle = build_episode_enrichment_bundle(
                    episode=episode,
                    as_of=1000,
                    hazard_evidence=evidence,
                )

        self.assertEqual(bundle.risk.status, "not_observed_as_of")
        self.assertIsNone(bundle.risk.observed_at)
        self.assertIsNone(bundle.risk.top10_token_account_concentration_pct)
        self.assertIn("token_hazard_observed_after_as_of", bundle.risk.data_quality_flags)

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
