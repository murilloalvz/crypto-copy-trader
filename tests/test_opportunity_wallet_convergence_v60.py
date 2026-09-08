import unittest

from src.market_observation_store import StoredMarketTrade
from src.market_opportunity_radar import MarketTradeObservation
from src.opportunity_wallet_convergence_v60 import (
    FrozenWalletCohortMemberV60,
    build_wallet_convergence_evidence_v60,
)


def _row(
    key: str,
    *,
    wallet: str | None,
    side: str,
    chain_time: int,
    observed_at: int | None = None,
    mint: str = "TOKEN",
    run: str = "run",
) -> StoredMarketTrade:
    return StoredMarketTrade(
        acquisition_run_key=run,
        event_key=key,
        source_provider="test",
        observation=MarketTradeObservation(
            token_mint=mint,
            side=side,
            chain_time=chain_time,
            observed_at=chain_time if observed_at is None else observed_at,
            wallet_address=wallet,
            transaction_key=key,
        ),
    )


class OpportunityWalletConvergenceV60Tests(unittest.TestCase):
    def test_repeated_buys_are_one_wallet_but_multiple_events(self):
        members = [FrozenWalletCohortMemberV60("A", "cohort", 50, "fast|staged")]
        evidence = build_wallet_convergence_evidence_v60(
            acquisition_run_key="run",
            token_mint="TOKEN",
            as_of=100,
            window_seconds=30,
            cohort_key="cohort",
            members=members,
            stored_trades=[
                _row("1", wallet="A", side="buy", chain_time=80),
                _row("2", wallet="A", side="buy", chain_time=90),
                _row("3", wallet="X", side="buy", chain_time=95),
            ],
        )
        self.assertEqual(evidence.cohort_event_count, 2)
        self.assertEqual(evidence.unique_cohort_wallet_count, 1)
        self.assertEqual(evidence.unique_cohort_buy_wallet_count, 1)
        self.assertEqual(evidence.repeated_cohort_event_share_pct, 50.0)
        self.assertEqual(evidence.cohort_share_of_known_wallet_events_pct, 200 / 3)

    def test_member_frozen_after_episode_is_not_retrospective_evidence(self):
        members = [FrozenWalletCohortMemberV60("A", "cohort", 100, "x")]
        evidence = build_wallet_convergence_evidence_v60(
            acquisition_run_key="run",
            token_mint="TOKEN",
            as_of=100,
            window_seconds=30,
            cohort_key="cohort",
            members=members,
            stored_trades=[_row("1", wallet="A", side="buy", chain_time=90)],
        )
        self.assertEqual(evidence.eligible_cohort_size, 0)
        self.assertEqual(evidence.cohort_event_count, 0)
        self.assertIn(
            "no_cohort_members_frozen_before_market_anchor",
            evidence.data_quality_flags,
        )

    def test_old_chain_event_discovered_late_is_excluded(self):
        members = [FrozenWalletCohortMemberV60("A", "cohort", 50, "x")]
        evidence = build_wallet_convergence_evidence_v60(
            acquisition_run_key="run",
            token_mint="TOKEN",
            as_of=100,
            window_seconds=30,
            cohort_key="cohort",
            members=members,
            stored_trades=[_row("1", wallet="A", side="buy", chain_time=90, observed_at=101)],
        )
        self.assertEqual(evidence.market_event_count, 0)
        self.assertEqual(evidence.cohort_event_count, 0)

    def test_strategy_diversity_counts_only_with_complete_signature_coverage(self):
        members = [
            FrozenWalletCohortMemberV60("A", "cohort", 50, "fast"),
            FrozenWalletCohortMemberV60("B", "cohort", 50, "selective"),
        ]
        evidence = build_wallet_convergence_evidence_v60(
            acquisition_run_key="run",
            token_mint="TOKEN",
            as_of=100,
            window_seconds=60,
            cohort_key="cohort",
            members=members,
            stored_trades=[
                _row("1", wallet="A", side="buy", chain_time=70),
                _row("2", wallet="B", side="buy", chain_time=80),
            ],
        )
        self.assertEqual(evidence.unique_cohort_wallet_count, 2)
        self.assertEqual(evidence.unique_strategy_signature_count, 2)

        incomplete = build_wallet_convergence_evidence_v60(
            acquisition_run_key="run",
            token_mint="TOKEN",
            as_of=100,
            window_seconds=60,
            cohort_key="cohort",
            members=[
                FrozenWalletCohortMemberV60("A", "cohort", 50, "fast"),
                FrozenWalletCohortMemberV60("B", "cohort", 50, None),
            ],
            stored_trades=[
                _row("1", wallet="A", side="buy", chain_time=70),
                _row("2", wallet="B", side="buy", chain_time=80),
            ],
        )
        self.assertIsNone(incomplete.unique_strategy_signature_count)
        self.assertIn("partial_strategy_signature_coverage", incomplete.data_quality_flags)

    def test_buy_sell_overlap_is_descriptive_not_two_independent_wallets(self):
        members = [FrozenWalletCohortMemberV60("A", "cohort", 50, "x")]
        evidence = build_wallet_convergence_evidence_v60(
            acquisition_run_key="run",
            token_mint="TOKEN",
            as_of=100,
            window_seconds=60,
            cohort_key="cohort",
            members=members,
            stored_trades=[
                _row("1", wallet="A", side="buy", chain_time=70),
                _row("2", wallet="A", side="sell", chain_time=90),
            ],
        )
        self.assertEqual(evidence.unique_cohort_wallet_count, 1)
        self.assertEqual(evidence.unique_cohort_buy_wallet_count, 1)
        self.assertEqual(evidence.unique_cohort_sell_wallet_count, 1)
        self.assertEqual(evidence.cohort_buy_sell_overlap_count, 1)

    def test_partial_market_wallet_coverage_stays_explicit(self):
        members = [FrozenWalletCohortMemberV60("A", "cohort", 50, "x")]
        evidence = build_wallet_convergence_evidence_v60(
            acquisition_run_key="run",
            token_mint="TOKEN",
            as_of=100,
            window_seconds=60,
            cohort_key="cohort",
            members=members,
            stored_trades=[
                _row("1", wallet="A", side="buy", chain_time=70),
                _row("2", wallet=None, side="buy", chain_time=80),
            ],
        )
        self.assertEqual(evidence.market_wallet_identity_coverage_pct, 50.0)
        self.assertIn("partial_market_wallet_identity_coverage", evidence.data_quality_flags)

    def test_duplicate_wallet_membership_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate wallet"):
            build_wallet_convergence_evidence_v60(
                acquisition_run_key="run",
                token_mint="TOKEN",
                as_of=100,
                window_seconds=60,
                cohort_key="cohort",
                members=[
                    FrozenWalletCohortMemberV60("A", "cohort", 10),
                    FrozenWalletCohortMemberV60("A", "cohort", 20),
                ],
                stored_trades=[],
            )


if __name__ == "__main__":
    unittest.main()
