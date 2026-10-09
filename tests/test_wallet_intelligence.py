import unittest

from src.discovery.models import (
    DailyWalletActivity,
    TokenPosition,
    WalletHistory,
    WalletPositions,
)
from src.wallet_intelligence import build_wallet_strategy_profile


def _position(
    token: str,
    pnl: float,
    roi: float,
    invested: float,
    hold: float,
    *,
    trades: int = 2,
    liquidity: float = 100_000,
    market_cap: float = 5_000_000,
) -> TokenPosition:
    return TokenPosition(
        token=token,
        symbol=token,
        realized_pnl_usd=pnl,
        invested_usd=invested,
        roi_pct=roi,
        trades=trades,
        average_buy_usd=invested,
        hold_time_seconds=hold,
        last_trade_ms=None,
        liquidity_usd=liquidity,
        market_cap_usd=market_cap,
        primary_market="test",
    )


class WalletIntelligenceTests(unittest.TestCase):
    def test_marks_outlier_dependent_positive_pnl(self):
        positions = WalletPositions(
            address="wallet",
            pnl_mode="strict",
            total_available=10,
            positions=tuple(
                [_position("moon", 1000, 500, 100, 3600)]
                + [_position(f"loss{i}", -50, -50, 100, 3600) for i in range(9)]
            ),
        )
        history = WalletHistory(
            address="wallet",
            days=(
                DailyWalletActivity("2026-08-01", 1000, 1, 1, 100, 200, 3600),
                DailyWalletActivity("2026-08-02", -450, 9, 9, 900, 1800, 3600),
            ),
        )

        profile = build_wallet_strategy_profile("wallet", history, positions)

        self.assertGreater(profile.realized_pnl_usd, 0)
        self.assertLessEqual(profile.pnl_without_top_winner_usd, 0)
        self.assertIn("profit_concentrated_in_top_winner", profile.flags)
        self.assertIn(
            "positive_pnl_disappears_without_best_position",
            profile.flags,
        )

    def test_profiles_hold_liquidity_and_intraday_archetype(self):
        positions = WalletPositions(
            address="wallet",
            pnl_mode="strict",
            total_available=12,
            positions=tuple(
                _position(
                    f"t{i}",
                    20 if i % 2 == 0 else -5,
                    10 if i % 2 == 0 else -2,
                    100,
                    7_200,
                    liquidity=120_000,
                )
                for i in range(12)
            ),
        )
        history = WalletHistory(address="wallet", days=())

        profile = build_wallet_strategy_profile("wallet", history, positions)

        self.assertEqual(profile.archetype, "intraday")
        self.assertEqual(profile.liquidity_coverage_pct, 100.0)
        self.assertEqual(profile.liquid_capital_share_pct, 100.0)
        self.assertTrue(profile.delay_research_ready)

    def test_onchain_sequence_detects_roundtrip_and_scaled_behavior(self):
        positions = WalletPositions(
            address="wallet",
            pnl_mode="strict",
            total_available=10,
            positions=tuple(
                _position(f"t{i}", 10, 10, 100, 3600)
                for i in range(10)
            ),
        )
        history = WalletHistory(address="wallet", days=())
        swaps = [
            {
                "kind": "swap",
                "status": "success",
                "token_mint": "a",
                "token_change": 1,
                "block_time": 100,
                "dex": "PumpSwap",
            },
            {
                "kind": "swap",
                "status": "success",
                "token_mint": "a",
                "token_change": 2,
                "block_time": 130,
                "dex": "PumpSwap",
            },
            {
                "kind": "swap",
                "status": "success",
                "token_mint": "a",
                "token_change": -3,
                "block_time": 160,
                "dex": "Jupiter v6",
            },
            {
                "kind": "swap",
                "status": "success",
                "token_mint": "b",
                "token_change": 1,
                "block_time": 220,
                "dex": "PumpSwap",
            },
        ]

        profile = build_wallet_strategy_profile(
            "wallet", history, positions, swaps
        )

        self.assertEqual(profile.local_swap_count, 4)
        self.assertEqual(profile.local_token_count, 2)
        self.assertEqual(profile.local_buy_count, 3)
        self.assertEqual(profile.local_sell_count, 1)
        self.assertEqual(profile.local_roundtrip_token_share_pct, 50.0)
        self.assertEqual(profile.local_multi_action_token_share_pct, 50.0)
        self.assertEqual(profile.execution_style, "scaled_or_multi_leg")
        self.assertEqual(profile.dex_mix["PumpSwap"], 3)

    def test_short_hold_blocks_delay_research_without_rejecting_wallet_quality(self):
        positions = WalletPositions(
            address="wallet",
            pnl_mode="strict",
            total_available=10,
            positions=tuple(
                _position(f"t{i}", 10, 10, 100, 120)
                for i in range(10)
            ),
        )
        history = WalletHistory(address="wallet", days=())

        profile = build_wallet_strategy_profile("wallet", history, positions)

        self.assertEqual(profile.archetype, "ultra_short")
        self.assertFalse(profile.delay_research_ready)
        self.assertIn("holding_time_too_short_for_delayed_copy", profile.flags)


if __name__ == "__main__":
    unittest.main()
