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
    WaveExposureMetrics,
    WaveOutlierMetrics,
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

    def test_update_prices_does_not_call_solana_tracker(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with (
                patch.object(
                    database,
                    "settings",
                    SimpleNamespace(database_path=Path(directory) / "prices.db"),
                ),
                patch(
                    "evaluate.update_due_paper_checks",
                    return_value={"completed": 2, "pending": 4, "failed": 0},
                ) as update,
                redirect_stdout(output),
            ):
                exit_code = main(["--update-prices"])

        self.assertEqual(exit_code, 0)
        update.assert_called_once_with()
        self.assertIn("2 concluídos | 4 pendentes", output.getvalue())
        self.assertIn("Solana Tracker não consultado", output.getvalue())

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

    def test_report_warns_when_simultaneous_signals_exceed_paper_balance(self):
        report = WaveEvaluationReport(
            strategy_version=WAVE_STRATEGY_VERSION,
            signal_count=2,
            completed_check_count=2,
            pending_check_count=0,
            failed_check_count=0,
            horizons=(
                WaveHorizonMetrics(
                    strategy_version=WAVE_STRATEGY_VERSION,
                    horizon_minutes=60,
                    sample_size=2,
                    wins=1,
                    win_rate_pct=50,
                    win_rate_low_pct=9.5,
                    win_rate_high_pct=90.5,
                    average_return_pct=1,
                    median_return_pct=1,
                    total_pnl_usd=0.5,
                    average_pnl_usd=0.25,
                    profit_factor=1.2,
                    max_drawdown_usd=1,
                    best_return_pct=6,
                    worst_return_pct=-4,
                ),
            ),
            exposures=(
                WaveExposureMetrics(
                    horizon_minutes=60,
                    max_concurrent_positions=3,
                    max_capital_deployed_usd=75,
                    capital_budget_usd=50,
                    capital_utilization_pct=150,
                    budget_exceeded=True,
                ),
            ),
        )

        output = format_evaluation_report(report)

        self.assertIn("Exposição máxima: 3 posições", output)
        self.assertIn("EXCEDEU O SALDO", output)

    def test_report_warns_when_positive_mean_depends_on_best_signal(self):
        report = WaveEvaluationReport(
            strategy_version=WAVE_STRATEGY_VERSION,
            signal_count=2,
            completed_check_count=2,
            pending_check_count=0,
            failed_check_count=0,
            horizons=(
                WaveHorizonMetrics(
                    strategy_version=WAVE_STRATEGY_VERSION,
                    horizon_minutes=5,
                    sample_size=2,
                    wins=1,
                    win_rate_pct=50,
                    win_rate_low_pct=9.5,
                    win_rate_high_pct=90.5,
                    average_return_pct=1.24,
                    median_return_pct=1.24,
                    total_pnl_usd=0.62,
                    average_pnl_usd=0.31,
                    profit_factor=1.41,
                    max_drawdown_usd=1.5,
                    best_return_pct=8.48,
                    worst_return_pct=-6.01,
                ),
            ),
            outlier_diagnostics=(
                WaveOutlierMetrics(
                    horizon_minutes=5,
                    sample_size=2,
                    return_stddev_pct=10.25,
                    mean_ci_low_pct=-90.8,
                    mean_ci_high_pct=93.3,
                    average_without_best_pct=-6.01,
                    top_winner_profit_share_pct=100,
                    positive_mean_depends_on_best=True,
                ),
            ),
        )

        output = format_evaluation_report(report)

        self.assertIn("IC 95% aproximado", output)
        self.assertIn("Média sem o melhor sinal: -6.01%", output)
        self.assertIn("ALERTA: a média positiva desaparece", output)


if __name__ == "__main__":
    unittest.main()
