import unittest
from dataclasses import fields

from src.opportunity_wallet_intelligence import (
    HistoricalWalletOutcome,
    OpportunityWalletIntelligenceSnapshot,
    OpportunityWalletParticipation,
    build_opportunity_wallet_intelligence,
)


class OpportunityWalletIntelligenceTests(unittest.TestCase):
    def _participation(self, wallet: str, *, observed_at: int = 100, notional: float | None = 10.0):
        return OpportunityWalletParticipation(
            episode_key="episode-1",
            wallet_address=wallet,
            token_mint="TOKEN",
            side="buy",
            chain_time=observed_at - 1,
            observed_at=observed_at,
            notional_usd=notional,
        )

    def _history(
        self,
        wallet: str,
        *,
        episode_key: str = "old-episode",
        token: str = "OLD",
        outcome_observed_at: int | None = 90,
        realized_return_pct: float | None = 12.0,
        hold_seconds: int | None = 300,
    ):
        return HistoricalWalletOutcome(
            episode_key=episode_key,
            wallet_address=wallet,
            token_mint=token,
            entry_observed_at=50,
            outcome_observed_at=outcome_observed_at,
            realized_return_pct=realized_return_pct,
            hold_seconds=hold_seconds,
        )

    def test_wallets_are_discovered_from_current_episode_without_allowlist(self):
        snapshot = build_opportunity_wallet_intelligence(
            episode_key="episode-1",
            token_mint="TOKEN",
            as_of=120,
            participations=[self._participation("wallet-new")],
            historical_outcomes=[],
        )
        self.assertEqual(snapshot.participant_wallet_count, 1)
        self.assertEqual(snapshot.wallets[0].wallet_address, "wallet-new")
        self.assertIn("no_resolved_prior_history", snapshot.wallets[0].data_quality_flags)

    def test_future_historical_outcome_is_not_used_at_t0(self):
        snapshot = build_opportunity_wallet_intelligence(
            episode_key="episode-1",
            token_mint="TOKEN",
            as_of=120,
            participations=[self._participation("wallet-A")],
            historical_outcomes=[self._history("wallet-A", outcome_observed_at=121, realized_return_pct=99.0)],
        )
        row = snapshot.wallets[0]
        self.assertEqual(row.prior_resolved_episode_count, 0)
        self.assertIsNone(row.prior_median_realized_return_pct)

    def test_unresolved_history_stays_missing_not_negative(self):
        snapshot = build_opportunity_wallet_intelligence(
            episode_key="episode-1",
            token_mint="TOKEN",
            as_of=120,
            participations=[self._participation("wallet-A")],
            historical_outcomes=[self._history("wallet-A", outcome_observed_at=None, realized_return_pct=None)],
        )
        row = snapshot.wallets[0]
        self.assertEqual(row.prior_resolved_episode_count, 0)
        self.assertIsNone(row.prior_positive_outcome_share_pct)

    def test_current_episode_cannot_leak_into_prior_competence_evidence(self):
        snapshot = build_opportunity_wallet_intelligence(
            episode_key="episode-1",
            token_mint="TOKEN",
            as_of=120,
            participations=[self._participation("wallet-A")],
            historical_outcomes=[
                self._history(
                    "wallet-A",
                    episode_key="episode-1",
                    token="TOKEN",
                    outcome_observed_at=110,
                    realized_return_pct=500.0,
                )
            ],
        )
        self.assertEqual(snapshot.wallets[0].prior_resolved_episode_count, 0)

    def test_prior_resolved_history_is_described_without_binary_approval(self):
        history = [
            self._history("wallet-A", episode_key="old-1", realized_return_pct=10.0, hold_seconds=100),
            self._history("wallet-A", episode_key="old-2", realized_return_pct=-2.0, hold_seconds=300),
            self._history("wallet-A", episode_key="old-3", token="TOKEN", realized_return_pct=4.0, hold_seconds=500),
        ]
        snapshot = build_opportunity_wallet_intelligence(
            episode_key="episode-1",
            token_mint="TOKEN",
            as_of=120,
            participations=[self._participation("wallet-A")],
            historical_outcomes=history,
        )
        row = snapshot.wallets[0]
        self.assertEqual(row.prior_resolved_episode_count, 3)
        self.assertEqual(row.prior_unique_token_count, 2)
        self.assertEqual(row.prior_same_token_episode_count, 1)
        self.assertAlmostEqual(row.prior_positive_outcome_share_pct or 0, 200 / 3)
        self.assertEqual(row.prior_median_realized_return_pct, 4.0)
        self.assertEqual(row.prior_median_hold_seconds, 300)
        self.assertIn("small_resolved_history_sample", row.data_quality_flags)

    def test_future_current_participation_is_excluded(self):
        snapshot = build_opportunity_wallet_intelligence(
            episode_key="episode-1",
            token_mint="TOKEN",
            as_of=120,
            participations=[
                self._participation("wallet-A", observed_at=100),
                self._participation("wallet-B", observed_at=121),
            ],
            historical_outcomes=[],
        )
        self.assertEqual(snapshot.participant_wallet_count, 1)
        self.assertEqual(snapshot.wallets[0].wallet_address, "wallet-A")

    def test_partial_notional_coverage_is_not_presented_as_complete(self):
        snapshot = build_opportunity_wallet_intelligence(
            episode_key="episode-1",
            token_mint="TOKEN",
            as_of=120,
            participations=[
                self._participation("wallet-A", notional=10.0),
                self._participation("wallet-B", notional=None),
            ],
            historical_outcomes=[],
        )
        self.assertEqual(snapshot.notional_coverage_pct, 50.0)
        self.assertIsNone(snapshot.wallets[0].current_notional_usd)
        self.assertIsNone(snapshot.wallets[1].current_notional_usd)
        self.assertIn("partial_current_notional_coverage", snapshot.data_quality_flags)

    def test_snapshot_contract_has_no_wallet_score_passed_or_recommendation(self):
        names = {item.name for item in fields(OpportunityWalletIntelligenceSnapshot)}
        forbidden = {"score", "wallet_score", "passed", "recommended", "decision", "buy"}
        self.assertTrue(names.isdisjoint(forbidden))


if __name__ == "__main__":
    unittest.main()
