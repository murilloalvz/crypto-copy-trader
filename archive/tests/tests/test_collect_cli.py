import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

from collect import main, run_collection


class WaveCollectorTests(unittest.TestCase):
    def test_collection_retries_runtime_failure_and_uses_bounded_sleeps(self):
        runner = Mock(side_effect=[0, 1, 0])
        sleeps = []

        with redirect_stdout(io.StringIO()):
            summary = run_collection(
                cycles=3,
                interval_seconds=30,
                radar_args=["--tokens", "1"],
                radar_runner=runner,
                sleeper=sleeps.append,
            )

        self.assertEqual(summary.completed_cycles, 3)
        self.assertEqual(summary.successful_cycles, 2)
        self.assertEqual(summary.failed_cycles, 1)
        self.assertFalse(summary.configuration_error)
        self.assertEqual(sleeps, [30, 30])

    def test_configuration_error_stops_without_waiting(self):
        runner = Mock(return_value=2)
        sleeper = Mock()

        with redirect_stdout(io.StringIO()):
            summary = run_collection(
                cycles=12,
                interval_seconds=300,
                radar_args=[],
                radar_runner=runner,
                sleeper=sleeper,
            )

        self.assertEqual(summary.completed_cycles, 1)
        self.assertTrue(summary.configuration_error)
        sleeper.assert_not_called()

    def test_main_handles_keyboard_interrupt_without_traceback(self):
        output = io.StringIO()
        with patch("collect.run_collection", side_effect=KeyboardInterrupt), redirect_stdout(
            output
        ):
            exit_code = main(["--cycles", "2", "--interval-minutes", "1"])

        self.assertEqual(exit_code, 130)
        self.assertIn("sinais já concluídos continuam no banco", output.getvalue())

    def test_rejects_unbounded_or_too_fast_collection(self):
        errors = io.StringIO()
        with redirect_stderr(errors):
            exit_code = main(["--cycles", "1000", "--interval-minutes", "0.1"])

        self.assertEqual(exit_code, 2)
        self.assertIn("entre 1 e 288", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
