import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database, services
from src.database import add_wallet, initialize_database, rows
from src.demo import DEMO_WALLET_ADDRESS, DEMO_WALLET_LABEL, DemoSolanaClient
from src.prices import Pool
from src.services import generate_paper_trades, price_paper_trades, sync_wallet


class MarketProvider:
    def __init__(self, pool: Pool):
        self.pool = pool
        self.price_calls = 0

    def market_for(self, _token_mint: str) -> Pool:
        return self.pool

    def price_at(self, _token_mint: str, _timestamp: int) -> float:
        self.price_calls += 1
        return 1.0


class SignalEligibilityTests(unittest.TestCase):
    def _settings(self, directory: str):
        return SimpleNamespace(
            database_path=Path(directory) / "eligibility.db",
            max_signatures=30,
            copy_size_usd=25,
            slippage_bps=100,
            copy_delay_seconds=15,
            min_signal_liquidity_usd=50_000,
            min_signal_volume_24h_usd=10_000,
        )

    def _prepare(self, directory: str) -> None:
        initialize_database()
        add_wallet(DEMO_WALLET_ADDRESS, DEMO_WALLET_LABEL)
        sync_wallet(DEMO_WALLET_ADDRESS, client=DemoSolanaClient())
        generate_paper_trades(DEMO_WALLET_ADDRESS)

    def test_illiquid_signals_are_recorded_but_never_priced(self):
        with tempfile.TemporaryDirectory() as directory:
            test_settings = self._settings(directory)
            provider = MarketProvider(Pool("pool", "base", 20_000, 100_000))
            with (
                patch.object(database, "settings", test_settings),
                patch.object(services, "settings", test_settings),
            ):
                self._prepare(directory)
                result = price_paper_trades(DEMO_WALLET_ADDRESS, provider=provider)
                statuses = rows(
                    "SELECT status, price_error FROM paper_trades ORDER BY id"
                )

        self.assertEqual(result["skipped_illiquid"], 10)
        self.assertEqual(result["priced"], 0)
        self.assertEqual(provider.price_calls, 0)
        self.assertTrue(all(item["status"] == "skipped_illiquid" for item in statuses))
        self.assertTrue(all("liquidez atual" in item["price_error"] for item in statuses))

    def test_low_volume_signals_are_skipped_after_liquidity_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            test_settings = self._settings(directory)
            provider = MarketProvider(Pool("pool", "base", 200_000, 1_000))
            with (
                patch.object(database, "settings", test_settings),
                patch.object(services, "settings", test_settings),
            ):
                self._prepare(directory)
                result = price_paper_trades(DEMO_WALLET_ADDRESS, provider=provider)

        self.assertEqual(result["skipped_low_volume"], 10)
        self.assertEqual(result["priced"], 0)
        self.assertEqual(provider.price_calls, 0)


if __name__ == "__main__":
    unittest.main()
