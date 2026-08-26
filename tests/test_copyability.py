import unittest
from dataclasses import replace

from src.discovery.copyability import CopyabilityPolicy, calculate_copyability
from src.discovery.models import CandidateSignals, TokenPosition, WalletPositions
from src.discovery.ranking import rank_candidates
from tests.test_discovery_ranking import candidate


def quality_candidate(*, trades=120, hold_seconds=3_600):
    item = candidate("HkFGQsW8mr8DTC2AE2WcC7MzwSnynfEryGMQSht271nf", trades_30d=trades)
    signals = CandidateSignals(
        trading_days_30d=18,
        profitable_days_30d=12,
        losing_days_30d=6,
        median_daily_pnl_usd=500,
        top_positive_day_share_pct=20,
        realized_drawdown_usd=1_000,
        realized_drawdown_pct=2,
        avg_hold_seconds=hold_seconds,
        last_trade_age_days=1,
        single_token_profit_cap_pct=30,
        arbitrage_excluded=True,
        strict_pnl_mode=True,
    )
    return rank_candidates([replace(item, signals=signals)])[0]


def position(index: int, *, liquidity=200_000, invested=1_000, average_buy=100):
    return TokenPosition(
        token=f"{index + 1}" * 32,
        symbol=f"T{index}",
        realized_pnl_usd=100,
        invested_usd=invested,
        roi_pct=10,
        trades=10,
        average_buy_usd=average_buy,
        hold_time_seconds=3_600,
        last_trade_ms=1_770_000_000_000,
        liquidity_usd=liquidity,
        market_cap_usd=2_000_000,
        primary_market="pumpfun-amm",
    )


def wallet_positions(items, pnl_mode="strict"):
    return WalletPositions(
        address="HkFGQsW8mr8DTC2AE2WcC7MzwSnynfEryGMQSht271nf",
        positions=tuple(items),
        total_available=len(items),
        pnl_mode=pnl_mode,
    )


class CopyabilityTests(unittest.TestCase):
    def test_liquid_slower_wallet_passes_with_explainable_components(self):
        result = calculate_copyability(
            quality_candidate(), wallet_positions([position(i) for i in range(10)])
        )

        self.assertTrue(result.passed)
        self.assertGreaterEqual(result.copyability_score, 60)
        self.assertEqual(result.metrics.liquid_position_share_pct, 100)
        self.assertEqual(result.metrics.liquid_capital_share_pct, 100)
        self.assertIn("holding_time", result.score_components)
        self.assertIn("entry_impact_proxy", result.score_components)

    def test_capital_weighted_liquidity_rejects_hidden_illiquid_exposure(self):
        positions = [position(i, liquidity=200_000, invested=100) for i in range(6)]
        positions.extend(position(i + 6, liquidity=5_000, invested=2_000) for i in range(4))

        result = calculate_copyability(quality_candidate(), wallet_positions(positions))

        self.assertGreaterEqual(result.metrics.liquid_position_share_pct, 50)
        self.assertLess(result.metrics.liquid_capital_share_pct, 60)
        self.assertFalse(result.passed)
        self.assertIn("liquid_capital_share_low", result.rejection_reasons)

    def test_fast_candidate_is_not_promoted_even_with_liquid_tokens(self):
        result = calculate_copyability(
            quality_candidate(hold_seconds=174),
            wallet_positions([position(i) for i in range(10)]),
        )

        self.assertFalse(result.passed)
        self.assertIn("average_hold_too_short", result.rejection_reasons)

    def test_hft_candidate_is_rejected_separately_from_quality(self):
        result = calculate_copyability(
            quality_candidate(trades=900),
            wallet_positions([position(i) for i in range(10)]),
        )

        self.assertFalse(result.passed)
        self.assertIn("trade_frequency_too_high", result.rejection_reasons)

    def test_missing_liquidity_is_unknown_and_fails_coverage(self):
        positions = [position(i, liquidity=None) for i in range(7)]
        positions.extend(position(i + 7) for i in range(3))

        result = calculate_copyability(quality_candidate(), wallet_positions(positions))

        self.assertEqual(result.metrics.liquidity_coverage_pct, 30)
        self.assertIn("liquidity_coverage_low", result.rejection_reasons)

    def test_policy_can_be_adjusted_without_changing_formula(self):
        policy = CopyabilityPolicy(min_token_liquidity_usd=250_000)

        result = calculate_copyability(
            quality_candidate(),
            wallet_positions([position(i, liquidity=200_000) for i in range(10)]),
            policy,
        )

        self.assertIn("liquid_position_share_low", result.rejection_reasons)


if __name__ == "__main__":
    unittest.main()
