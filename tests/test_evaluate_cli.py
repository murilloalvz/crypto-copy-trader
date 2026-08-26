import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from evaluate import format_evaluation_report, main
from src import database
from src.wave_metrics import (
    SlippageStressMetrics,
    WaveCohortMetrics,
    WaveEvaluationReport,
    WaveHorizonMetrics,
)
from src.wave_paper import WAVE_STRATEGY_VERSION


class WaveEvaluationCLITests(unittest.TestCase):
    def test_empty_report_is_explicitly_inconclusive(self):
        report = WaveEvaluationReport(
            strategy_version=WAVE_STRATEGY_VERSION,
            signal_count=1,
            completed_check_count=0,
            pending_check_count=3,
            failed_check_count=0,
            horizons=(),
        )

        output = format_evaluation_report(report)

        self.assertIn("INCONCLUSIVO", output)
        self.assertIn("3 pendentes", output)

    def test_main_reads_empty_local_database_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with (
                patch.object(
                    database,
                    "settings",
                    SimpleNamespace(database_path=Path(directory) / "empty.db"),
                ),
                redirect_stdout(output),
            ):
                exit_code = main([])

        self.assertEqual(exit_code, 0)
        self.assertIn("PAPER/READ ONLY", output.getvalue())
        self.assertIn("menos de 30 observações", output.getvalue())

    def test_report_displays_slippage_robustness(self):
        report = WaveEvaluationReport(
            strategy_version=WAVE_STRATEGY_VERSION,
            signal_count=1,
            completed_check_count=1,
            pending_check_count=0,
            failed_check_count=0,
            horizons=(
                WaveHorizonMetrics(
                    strategy_version=WAVE_STRATEGY_VERSION,
                    horizon_minutes=5,
                    sample_size=1,
                    wins=1,
                    win_rate_pct=100,
                    win_rate_low_pct=20.7,
                    win_rate_high_pct=100,
                    average_return_pct=5,
                    median_return_pct=5,
                    total_pnl_usd=1.25,
                    average_pnl_usd=1.25,
                    profit_factor=float("inf"),
                    max_drawdown_usd=0,
                    best_return_pct=5,
                    worst_return_pct=5,
                ),
            ),
            slippage_stress=(
                SlippageStressMetrics(
                    horizon_minutes=5,
                    slippage_bps_per_side=200,
                    sample_size=1,
                    win_rate_pct=100,
                    average_return_pct=5,
                    median_return_pct=5,
                    total_pnl_usd=1.25,
                    profit_factor=float("inf"),
                ),
            ),
        )

        output = format_evaluation_report(report)

        self.assertIn("Stress de slippage", output)
        self.assertIn("2.00%", output)

    def test_cohorts_are_hidden_by_default_and_explicit_when_requested(self):
        report = WaveEvaluationReport(
            strategy_version=WAVE_STRATEGY_VERSION,
            signal_count=1,
            completed_check_count=1,
            pending_check_count=0,
            failed_check_count=0,
            horizons=(
                WaveHorizonMetrics(
                    strategy_version=WAVE_STRATEGY_VERSION,
                    horizon_minutes=5,
                    sample_size=1,
                    wins=1,
                    win_rate_pct=100,
                    win_rate_low_pct=20.7,
                    win_rate_high_pct=100,
                    average_return_pct=5,
                    median_return_pct=5,
                    total_pnl_usd=1.25,
                    average_pnl_usd=1.25,
                    profit_factor=float("inf"),
                    max_drawdown_usd=0,
                    best_return_pct=5,
                    worst_return_pct=5,
                ),
            ),
            cohorts=(
                WaveCohortMetrics(
                    horizon_minutes=5,
                    dimension="wave_score",
                    bucket="55–64.9",
                    sample_size=1,
                    win_rate_pct=100,
                    average_return_pct=5,
                    median_return_pct=5,
                    profit_factor=float("inf"),
                ),
            ),
        )

        hidden = format_evaluation_report(report)
        visible = format_evaluation_report(report, show_cohorts=True)

        self.assertNotIn("COORTES EXPLORATÓRIAS", hidden)
        self.assertIn("COORTES EXPLORATÓRIAS", visible)
        self.assertIn("55–64.9", visible)


if __name__ == "__main__":
    unittest.main()
