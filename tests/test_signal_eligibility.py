import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import analytics, database, services
from src.analytics import paper_performance
from src.database import add_wallet, connection, initialize_database, rows
from src.demo import DEMO_WALLET_ADDRESS, DEMO_WALLET_LABEL, DemoSolanaClient
from src.prices import (
    PermanentPriceProviderError,
    Pool,
    TemporaryPriceProviderError,
)
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


class FailingProvider(MarketProvider):
    def __init__(self, error):
        super().__init__(Pool("pool", "base", 200_000, 100_000))
        self.error = error

    def price_at(self, _token_mint: str, _timestamp: int) -> float:
        self.price_calls += 1
        raise self.error


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
            max_price_retry_attempts=3,
            starting_balance_usd=1_000,
        )

    def _prepare(self, directory: str) -> None:
        initialize_database()
        add_wallet(DEMO_WALLET_ADDRESS, DEMO_WALLET_LABEL)
        sync_wallet(DEMO_WALLET_ADDRESS, client=DemoSolanaClient())
        generate_paper_trades(DEMO_WALLET_ADDRESS)

    def _leave_one_trade_unpriced(self) -> None:
        with connection() as conn:
            first_id = conn.execute("SELECT MIN(id) AS id FROM paper_trades").fetchone()["id"]
            conn.execute(
                """UPDATE paper_trades SET market_price_usd=1,
                execution_price_usd=1, status='priced' WHERE id!=?""",
                (first_id,),
            )

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

    def test_permanent_missing_pool_is_classified_and_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            test_settings = self._settings(directory)
            error = PermanentPriceProviderError("Nenhum pool.", code="no_pool")
            first_provider = FailingProvider(error)
            second_provider = FailingProvider(error)
            with (
                patch.object(database, "settings", test_settings),
                patch.object(services, "settings", test_settings),
            ):
                self._prepare(directory)
                self._leave_one_trade_unpriced()
                first = price_paper_trades(
                    DEMO_WALLET_ADDRESS, provider=first_provider
                )
                second = price_paper_trades(
                    DEMO_WALLET_ADDRESS, provider=second_provider
                )
                trade = rows(
                    "SELECT status, price_error_code, price_retry_count FROM paper_trades"
                )[0]

        self.assertEqual(first["permanent_failures"], 1)
        self.assertEqual(second["failed"], 0)
        self.assertEqual(second_provider.price_calls, 0)
        self.assertEqual(trade["status"], "price_no_pool")
        self.assertEqual(trade["price_error_code"], "no_pool")
        self.assertEqual(trade["price_retry_count"], 1)

    def test_temporary_failure_is_retried_and_can_recover(self):
        with tempfile.TemporaryDirectory() as directory:
            test_settings = self._settings(directory)
            failing = FailingProvider(TemporaryPriceProviderError("HTTP 429"))
            recovered = MarketProvider(Pool("pool", "base", 200_000, 100_000))
            with (
                patch.object(database, "settings", test_settings),
                patch.object(services, "settings", test_settings),
            ):
                self._prepare(directory)
                self._leave_one_trade_unpriced()
                first = price_paper_trades(DEMO_WALLET_ADDRESS, provider=failing)
                second = price_paper_trades(DEMO_WALLET_ADDRESS, provider=recovered)
                trade = rows(
                    "SELECT status, price_error_code, market_price_usd FROM paper_trades"
                )[0]

        self.assertEqual(first["retryable_failures"], 1)
        self.assertEqual(second["priced"], 1)
        self.assertIsNotNone(trade["market_price_usd"])
        self.assertIsNone(trade["price_error_code"])

    def test_performance_reports_total_and_eligible_price_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            test_settings = self._settings(directory)
            provider = MarketProvider(Pool("pool", "base", 200_000, 100_000))
            with (
                patch.object(database, "settings", test_settings),
                patch.object(services, "settings", test_settings),
                patch.object(analytics, "settings", test_settings),
            ):
                self._prepare(directory)
                price_paper_trades(DEMO_WALLET_ADDRESS, provider=provider)
                performance = paper_performance(DEMO_WALLET_ADDRESS)

        self.assertEqual(performance["total_signals"], 10)
        self.assertEqual(performance["priced_signals"], 10)
        self.assertEqual(performance["price_coverage_pct"], 100)
        self.assertEqual(performance["eligible_price_coverage_pct"], 100)


if __name__ == "__main__":
    unittest.main()
