from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.assets import USDC_MINT
from src.causal_quote_store import record_causal_quote
from src.causal_quotes import CausalQuoteObservation
from src.jupiter_episode_execution import JUPITER_ENTRY_PROVIDER, JUPITER_ENTRY_PURPOSE
from src.market_observation_store import record_market_trade
from src.market_opportunity_episode_store import (
    MarketOpportunityEpisode,
    assign_market_opportunity_trigger,
    freeze_market_opportunity_decision_as_of,
)
from src.market_opportunity_radar import MarketTradeObservation
from src.opportunity_forward_outcome_store import (
    complete_opportunity_forward_outcome,
    schedule_opportunity_forward_outcomes,
)
from src.opportunity_provider_attempt_store import (
    begin_provider_attempt,
    complete_provider_attempt,
)
from src.opportunity_wallet_intelligence import (
    HistoricalWalletOpportunityAssociation,
    OpportunityWalletParticipation,
    build_opportunity_wallet_intelligence,
)
from src.opportunity_wallet_market_history import (
    MARKET_FIRST_WALLET_HISTORY_VERSION,
    load_market_first_wallet_opportunity_history,
)


PRIOR_TOKEN = "PriorToken1111111111111111111111111111111111"
CURRENT_TOKEN = "CurrentToken11111111111111111111111111111111"
WALLET_A = "WalletA111111111111111111111111111111111111"


class OpportunityWalletMarketHistoryTests(unittest.TestCase):
    def _current_episode(self, *, t0: int = 600) -> MarketOpportunityEpisode:
        return MarketOpportunityEpisode(
            episode_key="current-episode",
            acquisition_run_key="current-run",
            token_mint=CURRENT_TOKEN,
            first_trigger_key="current-trigger",
            first_trigger_kind="established_acceleration",
            first_trigger_direction="buy_pressure",
            first_trigger_chain_time=t0 - 1,
            first_trigger_observed_at=t0,
            episode_closes_at=t0 + 60,
            decision_as_of=None,
        )

    def _quote(
        self,
        *,
        token: str,
        side: str,
        observed_at: int,
        price: float,
    ) -> CausalQuoteObservation:
        if side == "buy":
            input_mint, output_mint = USDC_MINT, token
        else:
            input_mint, output_mint = token, USDC_MINT
        return CausalQuoteObservation(
            token_mint=token,
            side=side,
            market_time=observed_at - 1,
            observed_at=observed_at,
            price_usd=price,
            source="test_executable_quote",
            executable=True,
            input_mint=input_mint,
            output_mint=output_mint,
            input_amount_raw="1000000",
            output_amount_raw="1000000",
            route_id=f"route-{side}-{observed_at}",
        )

    def _seed_prior(
        self,
        *,
        outcome_observed_at: int = 425,
        complete_horizon: int = 300,
    ) -> MarketOpportunityEpisode:
        prior = assign_market_opportunity_trigger(
            acquisition_run_key="prior-run",
            trigger_key="prior-trigger",
            token_mint=PRIOR_TOKEN,
            trigger_kind="established_acceleration",
            direction="buy_pressure",
            chain_time=99,
            observed_at=100,
            method_version="market_opportunity_radar_v1_1_tx_aware",
            venue="pump",
        )
        record_market_trade(
            acquisition_run_key="prior-run",
            event_key="prior-wallet-event",
            source_provider="pump",
            observation=MarketTradeObservation(
                token_mint=PRIOR_TOKEN,
                side="buy",
                chain_time=109,
                observed_at=110,
                wallet_address=WALLET_A,
                venue="pump",
                transaction_key="prior-tx",
            ),
        )
        prior = freeze_market_opportunity_decision_as_of(
            prior.episode_key, decision_as_of=120
        )

        entry_key = "entry-quote-prior"
        record_causal_quote(
            self._quote(token=PRIOR_TOKEN, side="buy", observed_at=115, price=1.0),
            quote_key=entry_key,
        )
        attempt_key = "provider-entry-prior"
        self.assertTrue(
            begin_provider_attempt(
                attempt_key=attempt_key,
                acquisition_run_key="prior-run",
                episode_key=prior.episode_key,
                provider=JUPITER_ENTRY_PROVIDER,
                purpose=JUPITER_ENTRY_PURPOSE,
                started_at=105,
            )
        )
        complete_provider_attempt(
            attempt_key=attempt_key,
            status="AVAILABLE",
            completed_at=119,
            artifact_key=entry_key,
            details={"assembled_transaction_present": True},
        )

        scheduled = schedule_opportunity_forward_outcomes(prior)
        selected = next(
            item for item in scheduled if item.horizon_seconds == complete_horizon
        )
        exit_key = f"exit-quote-{complete_horizon}"
        record_causal_quote(
            self._quote(
                token=PRIOR_TOKEN,
                side="sell",
                observed_at=outcome_observed_at,
                price=1.2,
            ),
            quote_key=exit_key,
        )
        complete_opportunity_forward_outcome(
            outcome_key=selected.outcome_key,
            status="AVAILABLE",
            observed_at=outcome_observed_at,
            quote_key=exit_key,
        )
        return prior

    def test_loader_builds_association_from_official_market_first_quotes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wallet-history.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                prior = self._seed_prior()
                result = load_market_first_wallet_opportunity_history(
                    current_episode=self._current_episode(),
                    current_participant_wallets=[WALLET_A, "never-seen-before"],
                    horizon_seconds=300,
                )

        self.assertEqual(result.history_cutoff, 600)
        self.assertEqual(result.candidate_prior_episode_count, 1)
        self.assertEqual(result.eligible_labeled_prior_episode_count, 1)
        self.assertEqual(result.prior_episodes_with_matching_participants, 1)
        self.assertEqual(len(result.associations), 1)
        association = result.associations[0]
        self.assertEqual(association.episode_key, prior.episode_key)
        self.assertEqual(association.wallet_address, WALLET_A)
        self.assertEqual(association.method_version, MARKET_FIRST_WALLET_HISTORY_VERSION)
        self.assertAlmostEqual(association.executable_quote_return_pct, 20.0)
        self.assertEqual(association.horizon_seconds, 300)
        self.assertIn("partial_market_first_history_coverage", result.data_quality_flags)

    def test_outcome_at_current_t0_is_excluded_as_ambiguous_not_backfilled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wallet-history.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self._seed_prior(outcome_observed_at=600)
                result = load_market_first_wallet_opportunity_history(
                    current_episode=self._current_episode(t0=600),
                    current_participant_wallets=[WALLET_A],
                    horizon_seconds=300,
                )

        self.assertEqual(result.associations, ())
        self.assertIn("no_valid_market_first_history_sample", result.data_quality_flags)
        exclusions = dict(result.exclusion_counts)
        self.assertEqual(exclusions["forward_outcome_not_known_strictly_pre_t0"], 1)

    def test_predeclared_horizon_does_not_fallback_to_another_available_label(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wallet-history.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self._seed_prior(complete_horizon=300)
                result = load_market_first_wallet_opportunity_history(
                    current_episode=self._current_episode(),
                    current_participant_wallets=[WALLET_A],
                    horizon_seconds=900,
                )

        self.assertEqual(result.associations, ())
        self.assertEqual(dict(result.exclusion_counts)["forward_outcome_not_available"], 1)

    def test_history_cutoff_cannot_move_after_current_t0(self):
        with self.assertRaises(ValueError):
            load_market_first_wallet_opportunity_history(
                current_episode=self._current_episode(t0=600),
                current_participant_wallets=[WALLET_A],
                horizon_seconds=300,
                history_cutoff=601,
            )

    def test_market_opportunity_return_never_populates_wallet_realized_pnl_fields(self):
        association = HistoricalWalletOpportunityAssociation(
            episode_key="prior-episode",
            wallet_address=WALLET_A,
            token_mint=PRIOR_TOKEN,
            prior_decision_as_of=100,
            outcome_observed_at=500,
            horizon_seconds=300,
            executable_quote_return_pct=25.0,
            entry_quote_key="entry",
            exit_quote_key="exit",
            method_version=MARKET_FIRST_WALLET_HISTORY_VERSION,
        )
        snapshot = build_opportunity_wallet_intelligence(
            episode_key="current-episode",
            token_mint=CURRENT_TOKEN,
            as_of=600,
            participations=[
                OpportunityWalletParticipation(
                    episode_key="current-episode",
                    wallet_address=WALLET_A,
                    token_mint=CURRENT_TOKEN,
                    side="buy",
                    chain_time=590,
                    observed_at=591,
                )
            ],
            historical_outcomes=[],
            historical_opportunity_associations=[association],
        )
        row = snapshot.wallets[0]
        self.assertEqual(row.prior_resolved_episode_count, 0)
        self.assertIsNone(row.prior_mean_realized_return_pct)
        self.assertEqual(row.prior_market_first_episode_count, 1)
        self.assertEqual(row.prior_market_first_mean_executable_quote_return_pct, 25.0)
        self.assertEqual(snapshot.participants_with_market_first_history, 1)

    def test_mixed_horizons_are_rejected_in_one_wallet_snapshot(self):
        base = dict(
            episode_key="prior-a",
            wallet_address=WALLET_A,
            token_mint=PRIOR_TOKEN,
            prior_decision_as_of=100,
            outcome_observed_at=500,
            executable_quote_return_pct=1.0,
            entry_quote_key="entry",
            exit_quote_key="exit",
            method_version=MARKET_FIRST_WALLET_HISTORY_VERSION,
        )
        associations = [
            HistoricalWalletOpportunityAssociation(horizon_seconds=300, **base),
            HistoricalWalletOpportunityAssociation(
                horizon_seconds=900, **{**base, "episode_key": "prior-b"}
            ),
        ]
        with self.assertRaises(ValueError):
            build_opportunity_wallet_intelligence(
                episode_key="current-episode",
                token_mint=CURRENT_TOKEN,
                as_of=600,
                participations=[
                    OpportunityWalletParticipation(
                        episode_key="current-episode",
                        wallet_address=WALLET_A,
                        token_mint=CURRENT_TOKEN,
                        side="buy",
                        chain_time=590,
                        observed_at=591,
                    )
                ],
                historical_outcomes=[],
                historical_opportunity_associations=associations,
            )


if __name__ == "__main__":
    unittest.main()
