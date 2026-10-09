import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

from monitor import HybridMonitorSummary, build_parser, main, run_hybrid_monitor


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
    def test_default_price_polling_is_one_minute(self):
        args = build_parser().parse_args([])

        self.assertEqual(args.price_interval_minutes, 1)

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
        self.assertEqual(prices.call_count, 4)
        self.assertEqual(summary.successful_discoveries, 2)
        self.assertEqual(summary.settlement_runs, 4)
        self.assertEqual(summary.completed_checks, 4)
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
        self.assertEqual(prices.call_count, 3)
        self.assertEqual(summary.completed_checks, 6)

    def test_unexpected_discovery_exception_is_isolated_and_monitor_continues(self):
        clock = FakeClock()
        radar = Mock(side_effect=[RuntimeError("temporary discovery crash"), 0])
        prices = Mock(
            return_value={"completed": 1, "pending": 0, "failed": 0}
        )
        output = io.StringIO()
        errors = io.StringIO()

        with redirect_stdout(output), redirect_stderr(errors):
            summary = run_hybrid_monitor(
                duration_seconds=601,
                price_interval_seconds=300,
                discovery_interval_seconds=600,
                radar_args=[],
                radar_runner=radar,
                price_updater=prices,
                clock=clock,
                sleeper=clock.sleep,
            )

        self.assertEqual(summary.discovery_runs, 2)
        self.assertEqual(summary.failed_discoveries, 1)
        self.assertEqual(summary.successful_discoveries, 1)
        self.assertEqual(prices.call_count, 3)
        self.assertIn("discovery lançou exceção inesperada", errors.getvalue())
        self.assertIn("RuntimeError: temporary discovery crash", errors.getvalue())

    def test_configuration_error_preserves_due_price_settlement_then_aborts(self):
        clock = FakeClock()
        prices = Mock(return_value={"completed": 0, "pending": 0, "failed": 0})
        with redirect_stdout(io.StringIO()):
            summary = run_hybrid_monitor(
                duration_seconds=3_600,
                price_interval_seconds=300,
                discovery_interval_seconds=1_800,
                radar_args=[],
                radar_runner=Mock(return_value=2),
                price_updater=prices,
                clock=clock,
                sleeper=clock.sleep,
            )

        self.assertTrue(summary.configuration_error)
        self.assertEqual(prices.call_count, 1)
        self.assertEqual(clock.sleeps, [])

    def test_polling_load_warning_is_visible_near_throttle_capacity(self):
        clock = FakeClock()
        output = io.StringIO()
        prices = Mock(
            return_value={
                "completed": 0,
                "pending": 0,
                "failed": 0,
                "exit_closed_positions": 0,
                "exit_open_positions": 125,
                "exit_open_signals": 25,
                "exit_price_failures": 0,
            }
        )

        with redirect_stdout(output):
            run_hybrid_monitor(
                duration_seconds=61,
                price_interval_seconds=60,
                discovery_interval_seconds=300,
                radar_args=[],
                radar_runner=Mock(return_value=1),
                price_updater=prices,
                clock=clock,
                sleeper=clock.sleep,
            )

        self.assertIn("normal 52.5s | sob rate-limit 300.0s/60s (500.0%)", output.getvalue())
        self.assertIn("ALERTA: carga próxima da capacidade", output.getvalue())

    def test_slow_discovery_does_not_push_price_scheduler_to_next_full_minute(self):
        clock = FakeClock()
        price_starts = []

        def prices():
            price_starts.append(clock.value)
            clock.value += 48
            return {"completed": 0, "pending": 0, "failed": 0}

        def radar(_args):
            clock.value += 18
            return 0

        with redirect_stdout(io.StringIO()):
            run_hybrid_monitor(
                duration_seconds=130,
                price_interval_seconds=60,
                discovery_interval_seconds=900,
                radar_args=["--defer-price-update"],
                radar_runner=radar,
                price_updater=prices,
                clock=clock,
                sleeper=clock.sleep,
            )

        self.assertEqual(price_starts[:3], [0.0, 66.0, 120.0])
        self.assertLessEqual(max(b - a for a, b in zip(price_starts, price_starts[1:])), 66)

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

    def test_main_defers_radar_price_update_to_dedicated_scheduler_cycle(self):
        summary = HybridMonitorSummary(0, 0, 0, 0, 0, 0)
        runner = Mock(return_value=summary)
        with (
            patch("monitor.initialize_database"),
            patch("monitor.ensure_exit_experiment", return_value={"id": 1, "activated_at": 1, "start_after_signal_id": 0}),
            patch("monitor.run_hybrid_monitor", runner),
            patch("monitor.evaluate_main", return_value=0),
            redirect_stdout(io.StringIO()),
        ):
            main(["--hours", "1"])

        radar_args = runner.call_args.kwargs["radar_args"]
        self.assertIn("--defer-price-update", radar_args)

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
