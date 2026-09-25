from __future__ import annotations

import unittest

from benchmarks.post_transition_reacceleration_v0.dual_stream_transport_soak_v0 import (
    FAIL,
    PASS,
    _classify,
)


class PostTransitionDualStreamTransportSoakV0Tests(unittest.TestCase):
    def test_pass_requires_full_duration_dual_traffic_and_no_idle_timeout(self):
        classification, reason = _classify(
            pump_raw=500,
            pumpswap_raw=2000,
            elapsed_seconds=180.2,
            requested_seconds=180,
            max_idle_seconds=1.5,
            idle_timeout_seconds=15,
        )
        self.assertEqual(classification, PASS)
        self.assertEqual(reason, "dual_stream_transport_soak_completed")

    def test_short_run_fails(self):
        classification, reason = _classify(
            pump_raw=500,
            pumpswap_raw=2000,
            elapsed_seconds=80.0,
            requested_seconds=180,
            max_idle_seconds=1.0,
            idle_timeout_seconds=15,
        )
        self.assertEqual(classification, FAIL)
        self.assertEqual(reason, "duration_not_completed")

    def test_idle_timeout_fails_even_with_large_traffic(self):
        classification, reason = _classify(
            pump_raw=5000,
            pumpswap_raw=20000,
            elapsed_seconds=180.0,
            requested_seconds=180,
            max_idle_seconds=15.0,
            idle_timeout_seconds=15,
        )
        self.assertEqual(classification, FAIL)
        self.assertEqual(reason, "idle_timeout_reached")

    def test_missing_one_stream_fails(self):
        classification, reason = _classify(
            pump_raw=19,
            pumpswap_raw=5000,
            elapsed_seconds=180.0,
            requested_seconds=180,
            max_idle_seconds=2.0,
            idle_timeout_seconds=15,
        )
        self.assertEqual(classification, FAIL)
        self.assertEqual(reason, "insufficient_dual_stream_traffic")


if __name__ == "__main__":
    unittest.main()
