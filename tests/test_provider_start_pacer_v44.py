from __future__ import annotations

import unittest
from unittest.mock import patch

from src.provider_start_pacer_v44 import ProviderStartPacerV44
import route_research_forward_cohort_v44 as v44


class ProviderStartPacerV44Tests(unittest.TestCase):
    def test_zero_interval_never_requires_meaningful_wait(self):
        pacer = ProviderStartPacerV44(interval_ms=0)
        with patch("src.provider_start_pacer_v44.time.monotonic", return_value=10.0), patch(
            "src.provider_start_pacer_v44.time.sleep"
        ) as sleeper:
            first = pacer.wait_for_slot()
            second = pacer.wait_for_slot()
        self.assertEqual(first, 0.0)
        self.assertEqual(second, 0.0)
        sleeper.assert_not_called()
        snapshot = pacer.snapshot()
        self.assertEqual(snapshot.starts, 2)
        self.assertEqual(snapshot.waited_starts, 0)

    def test_successive_reservations_are_spaced_without_retry_semantics(self):
        pacer = ProviderStartPacerV44(interval_ms=500)
        monotonic_values = iter([100.0, 100.0])
        sleeps: list[float] = []
        with patch(
            "src.provider_start_pacer_v44.time.monotonic",
            side_effect=lambda: next(monotonic_values),
        ), patch(
            "src.provider_start_pacer_v44.time.sleep",
            side_effect=lambda value: sleeps.append(value),
        ):
            first = pacer.wait_for_slot()
            second = pacer.wait_for_slot()
        self.assertEqual(first, 0.0)
        self.assertAlmostEqual(second, 0.5)
        self.assertEqual(sleeps, [0.5])
        snapshot = pacer.snapshot()
        self.assertEqual(snapshot.starts, 2)
        self.assertEqual(snapshot.waited_starts, 1)
        self.assertAlmostEqual(snapshot.total_wait_seconds, 0.5)
        self.assertAlmostEqual(snapshot.max_wait_seconds, 0.5)

    def test_v44_defaults_are_conservative_for_entry_and_tighter_for_exit(self):
        args = v44.build_parser().parse_args(["--run-key", "cohort"])
        self.assertEqual(args.hazard_start_interval_ms, 650)
        self.assertEqual(args.entry_start_interval_ms, 1000)
        self.assertEqual(args.exit_start_interval_ms, 250)
        self.assertGreater(args.entry_start_interval_ms, args.exit_start_interval_ms)


if __name__ == "__main__":
    unittest.main()
