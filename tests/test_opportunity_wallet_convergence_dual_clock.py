import unittest

from src.market_observation_store import StoredMarketTrade
from src.market_opportunity_radar import MarketTradeObservation
from src.opportunity_wallet_convergence_v60 import (
    FrozenWalletCohortMemberV60,
    build_wallet_convergence_evidence_v60,
)


def _row(key: str, *, wallet: str, chain_time: int, observed_at: int | None = None) -> StoredMarketTrade:
    return StoredMarketTrade(
        acquisition_run_key="run",
        event_key=key,
        source_provider="test",
        observation=MarketTradeObservation(
            token_mint="TOKEN",
            side="buy",
            chain_time=chain_time,
            observed_at=chain_time if observed_at is None else observed_at,
            wallet_address=wallet,
            transaction_key=key,
        ),
    )


class OpportunityWalletConvergenceDualClockTests(unittest.TestCase):
    def test_member_enrolled_between_t0_and_decision_is_not_eligible(self):
        evidence = build_wallet_convergence_evidence_v60(
            acquisition_run_key="run",
            token_mint="TOKEN",
            market_anchor_time=100,
            as_of=110,
            window_seconds=60,
            cohort_key="cohort",
            members=[
                FrozenWalletCohortMemberV60("EARLY", "cohort", 90, "sig-a"),
                FrozenWalletCohortMemberV60("LATE", "cohort", 105, "sig-b"),
            ],
            stored_trades=[
                _row("1", wallet="EARLY", chain_time=95),
                _row("2", wallet="LATE", chain_time=96),
            ],
        )
        self.assertEqual(evidence.market_anchor_time, 100)
        self.assertEqual(evidence.as_of, 110)
        self.assertEqual(evidence.eligible_cohort_size, 1)
        self.assertEqual(evidence.cohort_event_count, 1)
        self.assertEqual(evidence.unique_cohort_wallet_count, 1)

    def test_post_t0_trade_is_excluded_even_if_known_by_decision(self):
        evidence = build_wallet_convergence_evidence_v60(
            acquisition_run_key="run",
            token_mint="TOKEN",
            market_anchor_time=100,
            as_of=110,
            window_seconds=60,
            cohort_key="cohort",
            members=[FrozenWalletCohortMemberV60("A", "cohort", 80, "sig")],
            stored_trades=[
                _row("pre", wallet="A", chain_time=95, observed_at=96),
                _row("post", wallet="A", chain_time=105, observed_at=106),
            ],
        )
        self.assertEqual(evidence.market_event_count, 1)
        self.assertEqual(evidence.cohort_event_count, 1)
        self.assertEqual(evidence.first_cohort_buy_offset_seconds, -5)
        self.assertEqual(evidence.last_cohort_buy_offset_seconds, -5)

    def test_pre_t0_trade_discovered_after_decision_is_excluded(self):
        evidence = build_wallet_convergence_evidence_v60(
            acquisition_run_key="run",
            token_mint="TOKEN",
            market_anchor_time=100,
            as_of=105,
            window_seconds=60,
            cohort_key="cohort",
            members=[FrozenWalletCohortMemberV60("A", "cohort", 80, "sig")],
            stored_trades=[
                _row("known", wallet="A", chain_time=90, observed_at=95),
                _row("late", wallet="A", chain_time=96, observed_at=106),
            ],
        )
        self.assertEqual(evidence.market_event_count, 1)
        self.assertEqual(evidence.cohort_event_count, 1)


if __name__ == "__main__":
    unittest.main()
