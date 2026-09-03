import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.pumpswap_pool_store import (
    load_pumpswap_pool_mapping,
    record_pumpswap_pool_mapping,
)


class PumpSwapPoolStoreTests(unittest.TestCase):
    def test_mapping_is_run_scoped_and_causal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pumpswap.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self.assertTrue(
                    record_pumpswap_pool_mapping(
                        acquisition_run_key="run-a",
                        pool_address="P",
                        base_mint="B",
                        quote_mint="Q",
                        observed_at=105,
                        source_provider="create",
                    )
                )
                self.assertTrue(
                    record_pumpswap_pool_mapping(
                        acquisition_run_key="run-b",
                        pool_address="P",
                        base_mint="B",
                        quote_mint="Q",
                        observed_at=110,
                        source_provider="rpc",
                    )
                )
                self.assertIsNone(
                    load_pumpswap_pool_mapping(
                        acquisition_run_key="run-a", pool_address="P", as_of=104
                    )
                )
                a = load_pumpswap_pool_mapping(
                    acquisition_run_key="run-a", pool_address="P", as_of=105
                )
                b = load_pumpswap_pool_mapping(
                    acquisition_run_key="run-b", pool_address="P", as_of=110
                )
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        assert a is not None and b is not None
        self.assertEqual(a.observed_at, 105)
        self.assertEqual(a.source_provider, "create")
        self.assertEqual(b.source_provider, "rpc")

    def test_later_corroboration_preserves_first_seen_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pumpswap.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self.assertTrue(
                    record_pumpswap_pool_mapping(
                        acquisition_run_key="run",
                        pool_address="P",
                        base_mint="B",
                        quote_mint="Q",
                        observed_at=100,
                        source_provider="rpc",
                    )
                )
                self.assertFalse(
                    record_pumpswap_pool_mapping(
                        acquisition_run_key="run",
                        pool_address="P",
                        base_mint="B",
                        quote_mint="Q",
                        observed_at=120,
                        source_provider="create",
                    )
                )
                loaded = load_pumpswap_pool_mapping(
                    acquisition_run_key="run", pool_address="P"
                )
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.observed_at, 100)
        self.assertEqual(loaded.source_provider, "rpc")

    def test_backdated_replay_and_identity_mutation_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pumpswap.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_pumpswap_pool_mapping(
                    acquisition_run_key="run",
                    pool_address="P",
                    base_mint="B",
                    quote_mint="Q",
                    observed_at=100,
                    source_provider="rpc",
                )
                with self.assertRaises(ValueError):
                    record_pumpswap_pool_mapping(
                        acquisition_run_key="run",
                        pool_address="P",
                        base_mint="B",
                        quote_mint="Q",
                        observed_at=99,
                        source_provider="rpc",
                    )
                with self.assertRaises(ValueError):
                    record_pumpswap_pool_mapping(
                        acquisition_run_key="run",
                        pool_address="P",
                        base_mint="DIFFERENT",
                        quote_mint="Q",
                        observed_at=101,
                        source_provider="rpc",
                    )


if __name__ == "__main__":
    unittest.main()
