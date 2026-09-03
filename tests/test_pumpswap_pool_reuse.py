import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.pumpswap_pool_store import (
    load_known_pumpswap_pool_mapping,
    load_pumpswap_pool_mapping,
    record_pumpswap_pool_mapping,
)
from src.pumpswap_reusable_resolver import ReusablePumpSwapPoolResolver


class _NoNetworkClient:
    def call(self, method, params):
        raise AssertionError("network hydration should not be called")


class PumpSwapPoolReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_prior_run_identity_is_reused_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reuse.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_pumpswap_pool_mapping(
                    acquisition_run_key="old-run",
                    pool_address="POOL",
                    base_mint="BASE",
                    quote_mint="QUOTE",
                    observed_at=100,
                    source_provider="solana_get_account_info",
                )
                resolver = ReusablePumpSwapPoolResolver(
                    acquisition_run_key="new-run",
                    client=_NoNetworkClient(),
                )
                mapping = await resolver.resolve("POOL", as_of=200)
                copied = load_pumpswap_pool_mapping(
                    acquisition_run_key="new-run",
                    pool_address="POOL",
                    as_of=200,
                )

        self.assertIsNotNone(mapping)
        self.assertIsNotNone(copied)
        assert mapping is not None and copied is not None
        self.assertEqual(mapping.base_mint, "BASE")
        self.assertEqual(mapping.observed_at, 100)
        self.assertEqual(resolver.historical_store_hits, 1)
        self.assertEqual(resolver.hydration_attempts, 0)

    async def test_future_identity_is_not_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "future.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_pumpswap_pool_mapping(
                    acquisition_run_key="future-run",
                    pool_address="POOL",
                    base_mint="BASE",
                    quote_mint="QUOTE",
                    observed_at=300,
                    source_provider="rpc",
                )
                self.assertIsNone(load_known_pumpswap_pool_mapping(pool_address="POOL", as_of=299))

    async def test_conflicting_historical_identity_is_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conflict.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_pumpswap_pool_mapping(
                    acquisition_run_key="run-a",
                    pool_address="POOL",
                    base_mint="BASE-A",
                    quote_mint="QUOTE",
                    observed_at=100,
                    source_provider="a",
                )
                record_pumpswap_pool_mapping(
                    acquisition_run_key="run-b",
                    pool_address="POOL",
                    base_mint="BASE-B",
                    quote_mint="QUOTE",
                    observed_at=110,
                    source_provider="b",
                )
                with self.assertRaises(ValueError):
                    load_known_pumpswap_pool_mapping(pool_address="POOL", as_of=200)


if __name__ == "__main__":
    unittest.main()
