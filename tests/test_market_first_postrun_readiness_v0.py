from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from benchmarks.market_first_live_discovery_v0.contracts import PASS_CLASSIFICATION as LIVE_PASS
from benchmarks.market_first_postrun_readiness_v0 import (
    FAIL_CLASSIFICATION,
    READY_CLASSIFICATION,
    WAITING_CLASSIFICATION,
)
from benchmarks.market_first_postrun_readiness_v0.run import build_postrun_readiness_v0


class MarketFirstPostrunReadinessV0Tests(unittest.TestCase):
    def _database(self, root: Path, statuses: tuple[str, str, str]) -> Path:
        path = root / "copytrader.db"
        conn = sqlite3.connect(path)
        conn.execute(
            """CREATE TABLE opportunity_forward_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                outcome_key TEXT NOT NULL UNIQUE,
                acquisition_run_key TEXT NOT NULL,
                episode_key TEXT NOT NULL,
                token_mint TEXT NOT NULL,
                decision_as_of INTEGER NOT NULL,
                horizon_seconds INTEGER NOT NULL,
                target_at INTEGER NOT NULL,
                status TEXT NOT NULL,
                observed_at INTEGER,
                quote_key TEXT,
                error_type TEXT,
                error_message TEXT
            )"""
        )
        for horizon, status in zip((300, 900, 3600), statuses):
            target = 1000 + horizon
            final = status != "PENDING"
            conn.execute(
                """INSERT INTO opportunity_forward_outcomes(
                    outcome_key, acquisition_run_key, episode_key, token_mint,
                    decision_as_of, horizon_seconds, target_at, status, observed_at,
                    quote_key, error_type, error_message
                ) VALUES (?, 'RUN1', 'EP1', 'MINT1', 1000, ?, ?, ?, ?, ?, NULL, NULL)""",
                (
                    f"OUTCOME-{horizon}",
                    horizon,
                    target,
                    status,
                    target if final else None,
                    f"QUOTE-{horizon}" if status == "AVAILABLE" else None,
                ),
            )
        conn.commit()
        conn.close()
        return path

    def _report(self, root: Path, *, live_pass: bool = True) -> Path:
        report = {
            "classification": LIVE_PASS if live_pass else "FAIL_MARKET_FIRST_LIVE_DISCOVERY_V0",
            "valid_live_discovery": live_pass,
            "coverage_classification": "operational_only_not_chain_complete",
            "chain_complete_coverage_claimed": False,
            "economic_edge_evaluated": False,
            "identity": {"acquisition_run_key": "RUN1"},
            "run": {"status": "CLOSED" if live_pass else "INTERRUPTED"},
            "acquisition": {"chunk_count": 2},
            "pipeline": {
                "chunks_processed": 2,
                "market_trade_statuses": {"ADAPTED": 90, "MISSING_CONTEXT": 10},
                "chunk_errors": [],
                "persistence_errors": [],
                "research_errors": [],
                "semantic_errors": [],
            },
            "audit": {
                "acquisition_run_key": "RUN1",
                "cohort_denominator": 1,
                "analyzable_t0_count": 1,
                "disposition_counts": [["ANALYZABLE_T0", 1]],
                "integrity_ready_for_close_or_analysis": True,
            },
            "gates": {"one": live_pass, "two": live_pass},
        }
        path = root / "report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    def test_pending_outcomes_are_structurally_healthy_but_block_economics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = self._database(root, ("PENDING", "PENDING", "PENDING"))
            report = self._report(root)
            readiness = build_postrun_readiness_v0(
                live_report_path=report, database_path=db, observed_at=2000
            )
        self.assertEqual(readiness["classification"], WAITING_CLASSIFICATION)
        self.assertFalse(readiness["safe_to_start_economic_analysis"])
        self.assertEqual(readiness["forward_outcomes"]["pending_count"], 3)
        self.assertEqual(readiness["forward_outcomes"]["pending_due_count"], 2)
        self.assertEqual(readiness["forward_outcomes"]["pending_not_yet_due_count"], 1)
        self.assertAlmostEqual(readiness["trade_coverage"]["missing_context_rate"], 0.10)

    def test_terminal_explicit_missingness_is_ready_without_requiring_all_available(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = self._database(root, ("AVAILABLE", "UNAVAILABLE", "PROVIDER_ERROR"))
            report = self._report(root)
            readiness = build_postrun_readiness_v0(
                live_report_path=report, database_path=db, observed_at=5000
            )
        self.assertEqual(readiness["classification"], READY_CLASSIFICATION)
        self.assertTrue(readiness["safe_to_start_economic_analysis"])
        self.assertEqual(readiness["forward_outcomes"]["pending_count"], 0)
        self.assertTrue(all(readiness["gates"].values()))

    def test_failed_live_run_fails_closed_even_with_terminal_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = self._database(root, ("AVAILABLE", "UNAVAILABLE", "PROVIDER_ERROR"))
            report = self._report(root, live_pass=False)
            readiness = build_postrun_readiness_v0(
                live_report_path=report, database_path=db, observed_at=5000
            )
        self.assertEqual(readiness["classification"], FAIL_CLASSIFICATION)
        self.assertFalse(readiness["safe_to_start_economic_analysis"])

    def test_schedule_clock_mismatch_is_integrity_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = self._database(root, ("AVAILABLE", "UNAVAILABLE", "PROVIDER_ERROR"))
            conn = sqlite3.connect(db)
            conn.execute("UPDATE opportunity_forward_outcomes SET target_at=9999 WHERE horizon_seconds=900")
            conn.commit()
            conn.close()
            report = self._report(root)
            readiness = build_postrun_readiness_v0(
                live_report_path=report, database_path=db, observed_at=10000
            )
        self.assertEqual(readiness["classification"], FAIL_CLASSIFICATION)
        self.assertFalse(readiness["gates"]["exact_forward_target_clocks"])

    def test_readiness_connection_is_query_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = self._database(root, ("PENDING", "PENDING", "PENDING"))
            report = self._report(root)
            before = db.stat().st_mtime_ns
            build_postrun_readiness_v0(live_report_path=report, database_path=db, observed_at=2000)
            after = db.stat().st_mtime_ns
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
