import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.database import initialize_database
from src.wave_metrics import (
    build_wave_evaluation_report,
    summarize_horizon,
    summarize_slippage_stress,
)
from src.wave_paper import WAVE_STRATEGY_VERSION


class WaveMetricsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "metrics.db"
        self.settings_patch = patch.object(
            database, "settings", SimpleNamespace(database_path=self.path)
        )
        self.settings_patch.start()
        initialize_database()

    def tearDown(self):
        self.settings_patch.stop()
        self.directory.cleanup()

    def test_summary_calculates_net_statistics_and_small_sample_warning(self):
        metrics = summarize_horizon(
            WAVE_STRATEGY_VERSION,
            5,
            [
                {"return_pct": 10, "pnl_usd": 2.5},
                {"return_pct": -4, "pnl_usd": -1},
                {"return_pct": 2, "pnl_usd": 0.5},
            ],
        )

        self.assertEqual(metrics.sample_size, 3)
        self.assertEqual(metrics.wins, 2)
        self.assertAlmostEqual(metrics.win_rate_pct, 66.666, places=2)
        self.assertEqual(metrics.median_return_pct, 2)
        self.assertEqual(metrics.total_pnl_usd, 2)
        self.assertEqual(metrics.profit_factor, 3)
        self.assertEqual(metrics.max_drawdown_usd, 1)
        self.assertIn("INCONCLUSIVA", metrics.evidence_label)

    def test_report_separates_strategy_and_check_statuses(self):
        with database.connection() as conn:
            current_id = conn.execute(
                """INSERT INTO wave_signals
                (token_mint, detected_at, wave_score, entry_market_price_usd,
                entry_execution_price_usd, copy_size_usd, slippage_bps,
                strategy_version, snapshot_json)
                VALUES ('current', 1000, 60, 1, 1.01, 25, 100, ?, '{}')""",
                (WAVE_STRATEGY_VERSION,),
            ).lastrowid
            legacy_id = conn.execute(
                """INSERT INTO wave_signals
                (token_mint, detected_at, wave_score, entry_market_price_usd,
                entry_execution_price_usd, copy_size_usd, slippage_bps,
                strategy_version, snapshot_json)
                VALUES ('legacy', 1001, 50, 1, 1.01, 25, 100,
                'wave_v1_baseline', '{}')"""
            ).lastrowid
            conn.executemany(
                """INSERT INTO wave_signal_checks
                (signal_id, horizon_minutes, target_at, observed_at,
                market_price_usd, return_pct, pnl_usd, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (current_id, 5, 1_300, 1_301, 1.05, 5, 1.25, "completed"),
                    (current_id, 15, 1_900, None, None, None, None, "pending"),
                    (current_id, 60, 4_600, None, None, None, None, "failed"),
                    (legacy_id, 5, 1_301, 1_302, 1.99, 99, 24.75, "completed"),
                ],
            )

        report = build_wave_evaluation_report(WAVE_STRATEGY_VERSION)

        self.assertEqual(report.signal_count, 1)
        self.assertEqual(report.completed_check_count, 1)
        self.assertEqual(report.pending_check_count, 1)
        self.assertEqual(report.failed_check_count, 1)
        self.assertEqual(len(report.horizons), 1)
        self.assertEqual(report.horizons[0].average_return_pct, 5)
        self.assertEqual(len(report.slippage_stress), 4)

    def test_slippage_stress_recalculates_both_sides_from_market_prices(self):
        observations = [
            {
                "entry_market_price_usd": 100,
                "market_price_usd": 110,
                "copy_size_usd": 25,
            }
        ]

        half_percent = summarize_slippage_stress(5, 50, observations)
        two_percent = summarize_slippage_stress(5, 200, observations)

        self.assertAlmostEqual(half_percent.average_return_pct, 8.90547, places=4)
        self.assertAlmostEqual(two_percent.average_return_pct, 5.68627, places=4)
        self.assertGreater(half_percent.total_pnl_usd, two_percent.total_pnl_usd)
        self.assertEqual(half_percent.win_rate_pct, 100)


if __name__ == "__main__":
    unittest.main()
