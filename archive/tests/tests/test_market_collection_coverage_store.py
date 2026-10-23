import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_collection_coverage_store import (
    count_market_collection_coverage_conflicts,
    load_market_collection_coverage,
    record_market_collection_coverage,
)


class MarketCollectionCoverageStoreTests(unittest.TestCase):
    def _record(self, **overrides):
        values = dict(
            acquisition_run_key="run-a",
            evidence_key="cov-100-110",
            source_provider="helius_standard_wss",
            source_scope="pump_pumpswap_market_stream",
            token_mint=None,
            start_chain_time=100,
            end_chain_time=110,
            available_at=111,
        )
        values.update(overrides)
        return record_market_collection_coverage(**values)

    def test_store_is_run_scoped_and_causal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coverage.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self._record()
                self._record(
                    acquisition_run_key="run-b",
                    evidence_key="cov-b",
                    start_chain_time=200,
                    end_chain_time=210,
                    available_at=211,
                )
                early = load_market_collection_coverage(
                    acquisition_run_key="run-a",
                    source_scope="pump_pumpswap_market_stream",
                    as_of=110,
                )
                ready = load_market_collection_coverage(
                    acquisition_run_key="run-a",
                    source_scope="pump_pumpswap_market_stream",
                    as_of=111,
                )
                other = load_market_collection_coverage(
                    acquisition_run_key="run-b",
                    source_scope="pump_pumpswap_market_stream",
                    as_of=211,
                )
        self.assertEqual(early, ())
        self.assertEqual(len(ready), 1)
        self.assertEqual(len(other), 1)
        self.assertEqual(ready[0].start_chain_time, 100)

    def test_idempotent_replay_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coverage.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self.assertTrue(self._record())
                self.assertFalse(self._record())
                rows = load_market_collection_coverage(
                    acquisition_run_key="run-a",
                    source_scope="pump_pumpswap_market_stream",
                    as_of=111,
                )
                conflicts = count_market_collection_coverage_conflicts(
                    acquisition_run_key="run-a"
                )
        self.assertEqual(len(rows), 1)
        self.assertEqual(conflicts, 0)

    def test_conflicting_replay_keeps_first_and_audits_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coverage.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self.assertTrue(self._record())
                self.assertFalse(self._record(end_chain_time=109))
                self.assertFalse(self._record(end_chain_time=109))
                rows = load_market_collection_coverage(
                    acquisition_run_key="run-a",
                    source_scope="pump_pumpswap_market_stream",
                    as_of=111,
                )
                conflicts = count_market_collection_coverage_conflicts(
                    acquisition_run_key="run-a"
                )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].end_chain_time, 110)
        self.assertEqual(conflicts, 1)

    def test_rejects_assertion_available_before_interval_end(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coverage.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with self.assertRaises(ValueError):
                    self._record(end_chain_time=110, available_at=109)

    def test_rejects_unsupported_coverage_kind(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coverage.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                with self.assertRaises(ValueError):
                    self._record(coverage_kind="inferred_from_no_errors")

    def test_mint_query_includes_global_and_exact_but_not_other_mint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coverage.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self._record(evidence_key="global")
                self._record(evidence_key="a", token_mint="MINT_A")
                self._record(evidence_key="b", token_mint="MINT_B")
                rows = load_market_collection_coverage(
                    acquisition_run_key="run-a",
                    source_scope="pump_pumpswap_market_stream",
                    token_mint="MINT_A",
                    as_of=111,
                )
        self.assertEqual([row.evidence_key for row in rows], ["global", "a"])

    def test_chain_window_filter_returns_overlapping_intervals(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coverage.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self._record(evidence_key="first", start_chain_time=100, end_chain_time=110, available_at=110)
                self._record(evidence_key="second", start_chain_time=110, end_chain_time=120, available_at=120)
                rows = load_market_collection_coverage(
                    acquisition_run_key="run-a",
                    source_scope="pump_pumpswap_market_stream",
                    as_of=120,
                    chain_time_after=105,
                    chain_time_before=115,
                )
        self.assertEqual([row.evidence_key for row in rows], ["first", "second"])


if __name__ == "__main__":
    unittest.main()
