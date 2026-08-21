import unittest
from datetime import datetime, timezone

from src.discovery.models import DailyWalletActivity, TraderSnapshot, WalletHistory
from src.discovery.tracker_service import SolanaTrackerDiscoveryService

NOW = datetime(2026, 8, 21, 12, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)
WALLET_GOOD = "HkFGQsW8mr8DTC2AE2WcC7MzwSnynfEryGMQSht271nf"
WALLET_HFT = "ApAKzJEqfnP7F74Za5xdTQxZMK4nD8dFTVBQ9bksTtGM"


def snapshot(address, *, trades=120, last_trade_ms=NOW_MS, pnl=30_000):
    return TraderSnapshot(
        address=address,
        realized_pnl_usd=pnl,
        volume_usd=150_000,
        trading_days=18,
        profitable_days=12,
        losing_days=6,
        max_single_day_pnl_usd=8_000,
        roi_pct=42,
        invested_usd=60_000,
        proceeds_usd=90_000,
        buys=55,
        sells=trades - 55,
        trades=trades,
        tokens_traded=18,
        profitable_tokens=11,
        losing_tokens=7,
        closed_tokens=18,
        win_rate_pct=61.1,
        first_trade_ms=NOW_MS - 90 * 86_400_000,
        last_trade_ms=last_trade_ms,
        pnl_mode="strict",
    )


def history(address):
    activities = []
    for day, pnl in (("2026-08-18", 1_000), ("2026-08-19", -300), ("2026-08-20", 700)):
        activities.append(
            DailyWalletActivity(
                date=day,
                realized_pnl_usd=pnl,
                buys=4,
                sells=4,
                invested_usd=2_000,
                volume_usd=4_000,
                avg_hold_seconds=3_600,
            )
        )
    activities.append(
        DailyWalletActivity(
            date="2026-07-01",
            realized_pnl_usd=4_000,
            buys=10,
            sells=10,
            invested_usd=10_000,
            volume_usd=20_000,
            avg_hold_seconds=7_200,
        )
    )
    return WalletHistory(address, tuple(activities))


class FakeTrackerClient:
    def __init__(self):
        self.calls = []

    def top_traders(self, limit, **kwargs):
        self.calls.append(("top", limit, kwargs))
        return [snapshot(WALLET_GOOD), snapshot(WALLET_HFT, trades=1_500)]

    def wallet_history(self, address, period):
        self.calls.append(("history", address, period))
        return history(address)


class TrackerDiscoveryTests(unittest.TestCase):
    def test_filters_hft_before_history_and_builds_risk_signals(self):
        client = FakeTrackerClient()

        report = SolanaTrackerDiscoveryService(client=client, now=NOW).discover(250)

        self.assertEqual(report.source_count, 2)
        self.assertEqual(report.prefiltered_count, 1)
        self.assertEqual(report.passed_count, 1)
        self.assertEqual(report.candidates[0].address, WALLET_GOOD)
        self.assertEqual(report.candidates[0].source, "solana_tracker")
        self.assertGreater(report.candidates[0].signals.realized_drawdown_usd, 0)
        self.assertGreater(report.candidates[0].signals.top_positive_day_share_pct, 50)
        self.assertNotIn(("history", WALLET_HFT, "90d"), client.calls)
        top_call = client.calls[0]
        self.assertEqual(top_call[2]["max_single_token_pct"], 50)

    def test_score_includes_drawdown_and_concentration_penalty(self):
        result = SolanaTrackerDiscoveryService(
            client=FakeTrackerClient(), now=NOW
        ).discover(250).candidates[0]

        self.assertIn("drawdown", result.score_components)
        self.assertTrue(any("concentrado" in item for item in result.penalties))
        self.assertTrue(any("drawdown" in item for item in result.reasons))


if __name__ == "__main__":
    unittest.main()
