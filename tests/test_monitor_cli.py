import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

from monitor import HybridMonitorSummary, main, run_hybrid_monitor


class FakeClock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class HybridMonitorTests(unittest.TestCase):
    def test_prices_run_every_five_minutes_and_discovery_every_fifteen(self):
        clock = FakeClock()
        radar = Mock(return_value=0)
        prices = Mock(
            return_value={"completed": 1, "pending": 2, "failed": 0}
        )

        with redirect_stdout(io.StringIO()):
            summary = run_hybrid_monitor(
                duration_seconds=20 * 60,
                price_interval_seconds=5 * 60,
                discovery_interval_seconds=15 * 60,
                radar_args=["--tokens", "1"],
                radar_runner=radar,
                price_updater=prices,
                clock=clock,
                sleeper=clock.sleep,
            )

        self.assertEqual(radar.call_count, 2)
        self.assertEqual(prices.call_count, 2)
        self.assertEqual(summary.successful_discoveries, 2)
        self.assertEqual(summary.settlement_runs, 2)
        self.assertEqual(summary.completed_checks, 2)
        self.assertEqual(clock.value, 20 * 60)

    def test_transient_discovery_failure_still_settles_existing_prices(self):
        clock = FakeClock()
        radar = Mock(side_effect=[1, 0])
        prices = Mock(
            return_value={"completed": 2, "pending": 0, "failed": 0}
        )

        with redirect_stdout(io.StringIO()):
            summary = run_hybrid_monitor(
                duration_seconds=11 * 60,
                price_interval_seconds=5 * 60,
                discovery_interval_seconds=10 * 60,
                radar_args=[],
                radar_runner=radar,
                price_updater=prices,
                clock=clock,
                sleeper=clock.sleep,
            )

        self.assertEqual(summary.discovery_runs, 2)
        self.assertEqual(summary.failed_discoveries, 1)
        self.assertEqual(prices.call_count, 2)
        self.assertEqual(summary.completed_checks, 4)

    def test_configuration_error_aborts_without_sleeping(self):
        clock = FakeClock()
        with redirect_stdout(io.StringIO()):
            summary = run_hybrid_monitor(
                duration_seconds=3_600,
                price_interval_seconds=300,
                discovery_interval_seconds=1_800,
                radar_args=[],
                radar_runner=Mock(return_value=2),
                price_updater=Mock(),
                clock=clock,
                sleeper=clock.sleep,
            )

        self.assertTrue(summary.configuration_error)
        self.assertEqual(clock.sleeps, [])

    def test_main_handles_keyboard_interrupt_safely(self):
        output = io.StringIO()
        with (
            patch("monitor.initialize_database"),
            patch("monitor.ensure_exit_experiment", return_value={"id": 1, "activated_at": 1, "start_after_signal_id": 0}),
            patch("monitor.run_hybrid_monitor", side_effect=KeyboardInterrupt),
            redirect_stdout(output),
        ):
            exit_code = main(["--hours", "1"])

        self.assertEqual(exit_code, 130)
        self.assertIn("permanece no SQLite", output.getvalue())

    def test_rejects_discovery_more_frequent_than_price_updates(self):
        errors = io.StringIO()
        with redirect_stderr(errors):
            exit_code = main(
                [
                    "--hours",
                    "1",
                    "--price-interval-minutes",
                    "10",
                    "--discovery-interval-minutes",
                    "5",
                ]
            )

        self.assertEqual(exit_code, 2)
        self.assertIn("discovery não pode ser mais frequente", errors.getvalue())

    def test_main_runs_final_evaluation_after_successful_monitor(self):
        summary = HybridMonitorSummary(
            discovery_runs=1,
            successful_discoveries=1,
            failed_discoveries=0,
            settlement_runs=2,
            completed_checks=3,
            failed_checks=0,
        )
        evaluator = Mock(return_value=0)
        with (
            patch("monitor.initialize_database"),
            patch("monitor.ensure_exit_experiment", return_value={"id": 1, "activated_at": 1, "start_after_signal_id": 0}),
            patch("monitor.run_hybrid_monitor", return_value=summary),
            patch("monitor.evaluate_main", evaluator),
            redirect_stdout(io.StringIO()),
        ):
            exit_code = main(["--hours", "1"])

        self.assertEqual(exit_code, 0)
        evaluator.assert_called_once_with(["--update-prices", "--cohorts"])

    def test_final_evaluation_can_be_skipped(self):
        summary = HybridMonitorSummary(
            discovery_runs=1,
            successful_discoveries=1,
            failed_discoveries=0,
            settlement_runs=0,
            completed_checks=0,
            failed_checks=0,
        )
        evaluator = Mock(return_value=0)
        with (
            patch("monitor.initialize_database"),
            patch("monitor.ensure_exit_experiment", return_value={"id": 1, "activated_at": 1, "start_after_signal_id": 0}),
            patch("monitor.run_hybrid_monitor", return_value=summary),
            patch("monitor.evaluate_main", evaluator),
            redirect_stdout(io.StringIO()),
        ):
            exit_code = main(["--hours", "1", "--skip-final-evaluation"])

        self.assertEqual(exit_code, 0)
        evaluator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
