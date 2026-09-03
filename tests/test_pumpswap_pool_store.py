import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.pumpswap_pool_store import (
    count_pumpswap_pool_mapping_conflicts,
    load_known_pumpswap_pool_mapping,
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

    def test_earlier_same_identity_replay_updates_first_known_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pumpswap.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_pumpswap_pool_mapping(
                    acquisition_run_key="run",
                    pool_address="P",
                    base_mint="B",
                    quote_mint="Q",
                    observed_at=120,
                    source_provider="rpc",
                )
                self.assertFalse(
                    record_pumpswap_pool_mapping(
                        acquisition_run_key="run",
                        pool_address="P",
                        base_mint="B",
                        quote_mint="Q",
                        observed_at=100,
                        source_provider="create",
                    )
                )
                loaded = load_pumpswap_pool_mapping(
                    acquisition_run_key="run", pool_address="P"
                )
        assert loaded is not None
        self.assertEqual(loaded.observed_at, 100)
        self.assertEqual(loaded.source_provider, "create")

    def test_conflicting_identity_is_audited_and_earliest_mapping_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pumpswap.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_pumpswap_pool_mapping(
                    acquisition_run_key="run",
                    pool_address="P",
                    base_mint="OLD",
                    quote_mint="Q",
                    observed_at=120,
                    source_provider="rpc",
                )
                self.assertFalse(
                    record_pumpswap_pool_mapping(
                        acquisition_run_key="run",
                        pool_address="P",
                        base_mint="NEW",
                        quote_mint="Q",
                        observed_at=100,
                        source_provider="create",
                    )
                )
                loaded = load_pumpswap_pool_mapping(
                    acquisition_run_key="run", pool_address="P"
                )
                conflicts = count_pumpswap_pool_mapping_conflicts(
                    acquisition_run_key="run"
                )
        assert loaded is not None
        self.assertEqual((loaded.base_mint, loaded.quote_mint), ("NEW", "Q"))
        self.assertEqual(loaded.observed_at, 100)
        self.assertEqual(conflicts, 1)

    def test_later_conflicting_identity_is_audited_without_mutating_canonical_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pumpswap.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_pumpswap_pool_mapping(
                    acquisition_run_key="run",
                    pool_address="P",
                    base_mint="B",
                    quote_mint="Q",
                    observed_at=100,
                    source_provider="create",
                )
                self.assertFalse(
                    record_pumpswap_pool_mapping(
                        acquisition_run_key="run",
                        pool_address="P",
                        base_mint="DIFFERENT",
                        quote_mint="Q",
                        observed_at=120,
                        source_provider="rpc",
                    )
                )
                loaded = load_pumpswap_pool_mapping(
                    acquisition_run_key="run", pool_address="P"
                )
                conflicts = count_pumpswap_pool_mapping_conflicts(
                    acquisition_run_key="run"
                )
        assert loaded is not None
        self.assertEqual((loaded.base_mint, loaded.quote_mint), ("B", "Q"))
        self.assertEqual(conflicts, 1)

    def test_conflicting_historical_identities_are_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pumpswap.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_pumpswap_pool_mapping(
                    acquisition_run_key="run-a",
                    pool_address="P",
                    base_mint="B1",
                    quote_mint="Q",
                    observed_at=100,
                    source_provider="create",
                )
                record_pumpswap_pool_mapping(
                    acquisition_run_key="run-b",
                    pool_address="P",
                    base_mint="B2",
                    quote_mint="Q",
                    observed_at=110,
                    source_provider="rpc",
                )
                historical = load_known_pumpswap_pool_mapping(
                    pool_address="P", as_of=120
                )
        self.assertIsNone(historical)


if __name__ == "__main__":
    unittest.main()
