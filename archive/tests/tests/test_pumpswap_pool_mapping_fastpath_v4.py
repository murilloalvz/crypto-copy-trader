from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.pumpswap_pool_mapping_fastpath_v4 import (
    pumpswap_pool_mapping_fastpath_snapshot_v4,
    record_pumpswap_pool_mapping_fast_v4,
    reset_pumpswap_pool_mapping_fastpath_metrics_v4,
)
from src.pumpswap_pool_store import (
    count_pumpswap_pool_mapping_conflicts,
    load_pumpswap_pool_mapping,
)


class PumpSwapPoolMappingFastPathV4Tests(unittest.TestCase):
    def setUp(self) -> None:
        reset_pumpswap_pool_mapping_fastpath_metrics_v4()

    def test_fresh_mapping_uses_insert_without_collision_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fast-v4.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                inserted = record_pumpswap_pool_mapping_fast_v4(
                    acquisition_run_key="run",
                    pool_address="P",
                    base_mint="B",
                    quote_mint="Q",
                    observed_at=100,
                    source_provider="rpc",
                )
                loaded = load_pumpswap_pool_mapping(
                    acquisition_run_key="run", pool_address="P"
                )

        self.assertTrue(inserted)
        self.assertIsNotNone(loaded)
        snapshot = pumpswap_pool_mapping_fastpath_snapshot_v4()
        self.assertEqual(snapshot.insert_attempts, 1)
        self.assertEqual(snapshot.collision_reads, 0)

    def test_same_identity_collision_preserves_earliest_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fast-v4.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_pumpswap_pool_mapping_fast_v4(
                    acquisition_run_key="run",
                    pool_address="P",
                    base_mint="B",
                    quote_mint="Q",
                    observed_at=120,
                    source_provider="rpc",
                )
                changed = record_pumpswap_pool_mapping_fast_v4(
                    acquisition_run_key="run",
                    pool_address="P",
                    base_mint="B",
                    quote_mint="Q",
                    observed_at=100,
                    source_provider="create",
                )
                loaded = load_pumpswap_pool_mapping(
                    acquisition_run_key="run", pool_address="P"
                )

        self.assertFalse(changed)
        assert loaded is not None
        self.assertEqual(loaded.observed_at, 100)
        self.assertEqual(loaded.source_provider, "create")
        snapshot = pumpswap_pool_mapping_fastpath_snapshot_v4()
        self.assertEqual(snapshot.insert_attempts, 2)
        self.assertEqual(snapshot.collision_reads, 1)
        self.assertEqual(snapshot.earliest_observed_updates, 1)

    def test_conflicting_identity_keeps_same_audit_and_canonical_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fast-v4.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_pumpswap_pool_mapping_fast_v4(
                    acquisition_run_key="run",
                    pool_address="P",
                    base_mint="OLD",
                    quote_mint="Q",
                    observed_at=120,
                    source_provider="rpc",
                )
                changed = record_pumpswap_pool_mapping_fast_v4(
                    acquisition_run_key="run",
                    pool_address="P",
                    base_mint="NEW",
                    quote_mint="Q",
                    observed_at=100,
                    source_provider="create",
                )
                loaded = load_pumpswap_pool_mapping(
                    acquisition_run_key="run", pool_address="P"
                )
                conflicts = count_pumpswap_pool_mapping_conflicts(
                    acquisition_run_key="run"
                )

        self.assertFalse(changed)
        assert loaded is not None
        self.assertEqual((loaded.base_mint, loaded.quote_mint), ("NEW", "Q"))
        self.assertEqual(loaded.observed_at, 100)
        self.assertEqual(conflicts, 1)
        snapshot = pumpswap_pool_mapping_fastpath_snapshot_v4()
        self.assertEqual(snapshot.identity_conflicts, 1)
        self.assertEqual(snapshot.canonical_replacements, 1)

    def test_equal_time_conflict_preserves_lexical_tie_break(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fast-v4.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_pumpswap_pool_mapping_fast_v4(
                    acquisition_run_key="run",
                    pool_address="P",
                    base_mint="Z",
                    quote_mint="Q",
                    observed_at=100,
                    source_provider="rpc",
                )
                record_pumpswap_pool_mapping_fast_v4(
                    acquisition_run_key="run",
                    pool_address="P",
                    base_mint="A",
                    quote_mint="Q",
                    observed_at=100,
                    source_provider="create",
                )
                loaded = load_pumpswap_pool_mapping(
                    acquisition_run_key="run", pool_address="P"
                )
                conflicts = count_pumpswap_pool_mapping_conflicts(
                    acquisition_run_key="run"
                )

        assert loaded is not None
        self.assertEqual((loaded.base_mint, loaded.quote_mint), ("A", "Q"))
        self.assertEqual(conflicts, 1)
        snapshot = pumpswap_pool_mapping_fastpath_snapshot_v4()
        self.assertEqual(snapshot.identity_conflicts, 1)
        self.assertEqual(snapshot.canonical_replacements, 1)


if __name__ == "__main__":
    unittest.main()
