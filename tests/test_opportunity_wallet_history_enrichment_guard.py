from __future__ import annotations

import unittest

from src.market_opportunity_episode_store import MarketOpportunityEpisode
from src.opportunity_episode_enrichment import build_episode_enrichment_bundle
from src.opportunity_wallet_intelligence import HistoricalWalletOpportunityAssociation


class OpportunityWalletHistoryEnrichmentGuardTests(unittest.TestCase):
    @staticmethod
    def _episode() -> MarketOpportunityEpisode:
        return MarketOpportunityEpisode(
            episode_key="current",
            acquisition_run_key="run",
            token_mint="TOKEN",
            first_trigger_key="trigger",
            first_trigger_kind="established_acceleration",
            first_trigger_direction="buy_pressure",
            first_trigger_chain_time=999,
            first_trigger_observed_at=1000,
            episode_closes_at=1060,
            decision_as_of=None,
        )

    @staticmethod
    def _association(*, prior_decision: int, outcome_observed_at: int):
        return HistoricalWalletOpportunityAssociation(
            episode_key="prior",
            wallet_address="wallet",
            token_mint="OLD",
            prior_decision_as_of=prior_decision,
            outcome_observed_at=outcome_observed_at,
            horizon_seconds=300,
            executable_quote_return_pct=5.0,
            entry_quote_key="entry",
            exit_quote_key="exit",
            method_version="market_first_wallet_opportunity_history_v1",
        )

    def test_outcome_at_same_second_as_current_t0_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "strictly known before current T0"):
            build_episode_enrichment_bundle(
                episode=self._episode(),
                as_of=1010,
                historical_wallet_opportunity_associations=[
                    self._association(prior_decision=500, outcome_observed_at=1000)
                ],
            )

    def test_prior_decision_at_current_t0_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "decision must be strictly before current T0"):
            build_episode_enrichment_bundle(
                episode=self._episode(),
                as_of=1010,
                historical_wallet_opportunity_associations=[
                    self._association(prior_decision=1000, outcome_observed_at=1001)
                ],
            )


if __name__ == "__main__":
    unittest.main()
