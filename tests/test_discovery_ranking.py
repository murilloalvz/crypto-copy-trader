import unittest

from src.discovery.models import CandidateInput, LeaderboardWallet, WalletPeriodMetrics
from src.discovery.ranking import (
    CandidatePolicy,
    filter_30d,
    filter_recent,
    prefilter_leaderboard,
    rank_candidates,
)


def period(
    name: str,
    *,
    trades: int = 100,
    wins: int = 29,
    losses: int = 21,
    tokens: int = 12,
    pnl: float = 20_000,
    roi: float = 30,
) -> WalletPeriodMetrics:
    return WalletPeriodMetrics(
        period=name,
        unique_tokens=tokens,
        total_buy=trades // 2,
        total_sell=trades - trades // 2,
        total_trade=trades,
        total_win=wins,
        total_loss=losses,
        win_rate_pct=100 * wins / (wins + losses) if wins + losses else 0,
        total_invested_usd=50_000,
        total_sold_usd=70_000,
        current_value_usd=1_000,
        realized_pnl_usd=pnl,
        roi_pct=roi,
        unrealized_pnl_usd=0,
        total_pnl_usd=pnl,
        avg_profit_per_trade_usd=pnl / trades if trades else 0,
    )


def candidate(
    address: str,
    *,
    pnl: float = 20_000,
    trades_30d: int = 100,
    trades_7d: int = 20,
    wins: int = 29,
    losses: int = 21,
    tokens: int = 12,
    roi: float = 30,
    pnl_7d: float = 3_000,
    pnl_90d: float = 50_000,
) -> CandidateInput:
    leaderboard = LeaderboardWallet(address, pnl, 100_000, trades_30d)
    return CandidateInput(
        address=address,
        source_rank=1,
        leaderboard=leaderboard,
        metrics_30d=period(
            "30d", trades=trades_30d, wins=wins, losses=losses,
            tokens=tokens, pnl=pnl, roi=roi,
        ),
        metrics_7d=period(
            "7d", trades=trades_7d, wins=max(3, wins // 4),
            losses=max(2, losses // 4), tokens=max(3, tokens // 2),
            pnl=pnl_7d, roi=8,
        ),
        metrics_90d=period(
            "90d", trades=trades_30d * 2, wins=wins * 2,
            losses=losses * 2, tokens=tokens * 2, pnl=pnl_90d, roi=45,
        ),
    )


class CandidateFilterTests(unittest.TestCase):
    def setUp(self):
        self.policy = CandidatePolicy()

    def test_source_prefilter_rejects_low_sample_and_hft_extreme(self):
        low = LeaderboardWallet("low", 1000, 2000, 19)
        hft = LeaderboardWallet("hft", 1000, 2000, 1001)

        self.assertIn("source_too_few_trades", prefilter_leaderboard(low, self.policy))
        self.assertIn("source_too_many_trades", prefilter_leaderboard(hft, self.policy))

    def test_detailed_filter_requires_quality_beyond_positive_pnl(self):
        weak = period("30d", trades=50, wins=2, losses=8, tokens=1, pnl=500_000, roi=200)

        reasons = filter_30d(weak, self.policy)

        self.assertIn("win_rate_below_minimum", reasons)
        self.assertIn("too_few_tokens", reasons)

    def test_recent_activity_is_a_separate_filter(self):
        self.assertEqual(filter_recent(period("7d", trades=0), self.policy), ("inactive_7d",))


class CandidateRankingTests(unittest.TestCase):
    def test_nominal_pnl_whale_does_not_automatically_win(self):
        whale = candidate(
            "whale", pnl=500_000, trades_30d=900, trades_7d=280,
            wins=6, losses=5, tokens=4, roi=5, pnl_7d=-20_000, pnl_90d=-50_000,
        )
        consistent = candidate(
            "consistent", pnl=30_000, trades_30d=120, trades_7d=25,
            wins=35, losses=20, tokens=18, roi=42, pnl_7d=4_000, pnl_90d=80_000,
        )

        ranked = rank_candidates([whale, consistent])

        self.assertEqual(ranked[0].address, "consistent")
        self.assertGreater(ranked[0].candidate_score, ranked[1].candidate_score)
        self.assertTrue(ranked[1].penalties)

    def test_scores_are_bounded_and_explainable(self):
        result = rank_candidates([candidate("wallet")])[0]

        self.assertGreaterEqual(result.candidate_score, 0)
        self.assertLessEqual(result.candidate_score, 100)
        self.assertIn("consistency", result.score_components)
        self.assertTrue(any("ativa" in reason for reason in result.reasons))

    def test_missing_90d_data_does_not_invent_consistency(self):
        complete = candidate("complete")
        incomplete = CandidateInput(
            address="incomplete",
            source_rank=2,
            leaderboard=complete.leaderboard,
            metrics_30d=complete.metrics_30d,
            metrics_7d=complete.metrics_7d,
            metrics_90d=None,
        )

        results = {item.address: item for item in rank_candidates([complete, incomplete])}

        self.assertGreater(
            results["complete"].score_components["consistency"],
            results["incomplete"].score_components["consistency"],
        )


if __name__ == "__main__":
    unittest.main()
