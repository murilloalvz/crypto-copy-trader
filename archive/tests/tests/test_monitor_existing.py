import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from monitor_existing import PriceOnlyMonitorSummary, main, run_price_only_monitor


class FakeClock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class PriceOnlyMonitorTests(unittest.TestCase):
    def test_updates_prices_without_any_discovery_dependency(self):
        clock = FakeClock()
        updater = Mock(return_value={"completed": 1, "pending": 0, "failed": 0})

        with redirect_stdout(io.StringIO()):
            summary = run_price_only_monitor(
                duration_seconds=181,
                price_interval_seconds=60,
                price_updater=updater,
                clock=clock,
                sleeper=clock.sleep,
            )

        self.assertEqual(updater.call_count, 4)
        self.assertEqual(summary.settlement_runs, 4)
        self.assertEqual(summary.completed_checks, 4)
        self.assertEqual(summary.failed_checks, 0)

    def test_slow_update_keeps_absolute_polling_schedule(self):
        clock = FakeClock()
        starts = []

        def updater():
            starts.append(clock.value)
            clock.value += 15
            return {"completed": 0, "pending": 0, "failed": 0}

        with redirect_stdout(io.StringIO()):
            run_price_only_monitor(
                duration_seconds=125,
                price_interval_seconds=60,
                price_updater=updater,
                clock=clock,
                sleeper=clock.sleep,
            )

        self.assertEqual(starts, [0.0, 60.0, 120.0])

    def test_main_can_skip_final_evaluation(self):
        summary = PriceOnlyMonitorSummary(2, 3, 0)
        evaluator = Mock(return_value=0)
        with (
            patch("monitor_existing.initialize_database"),
            patch(
                "monitor_existing.ensure_exit_experiment",
                return_value={"id": 1, "activated_at": 1, "start_after_signal_id": 0},
            ),
            patch("monitor_existing.run_price_only_monitor", return_value=summary),
            patch("monitor_existing.evaluate_main", evaluator),
            redirect_stdout(io.StringIO()),
        ):
            code = main(["--hours", "1", "--skip-final-evaluation"])

        self.assertEqual(code, 0)
        evaluator.assert_not_called()

    def test_main_runs_final_evaluation_by_default(self):
        summary = PriceOnlyMonitorSummary(2, 3, 0)
        evaluator = Mock(return_value=0)
        with (
            patch("monitor_existing.initialize_database"),
            patch(
                "monitor_existing.ensure_exit_experiment",
                return_value={"id": 1, "activated_at": 1, "start_after_signal_id": 0},
            ),
            patch("monitor_existing.run_price_only_monitor", return_value=summary),
            patch("monitor_existing.evaluate_main", evaluator),
            redirect_stdout(io.StringIO()),
        ):
            code = main(["--hours", "1"])

        self.assertEqual(code, 0)
        evaluator.assert_called_once_with(["--update-prices", "--cohorts"])


if __name__ == "__main__":
    unittest.main()
