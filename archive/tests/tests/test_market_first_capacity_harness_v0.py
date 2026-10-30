from __future__ import annotations

import unittest

from benchmarks.market_first_capacity_harness_v0.run import (
    DualClockSamplerV0,
    simulate_single_consumer_queue_v0,
)


class MarketFirstCapacityHarnessV0Tests(unittest.TestCase):
    def test_queue_simulation_stays_bounded_when_service_is_faster_than_arrival(self) -> None:
        result = simulate_single_consumer_queue_v0(
            producer_offsets_seconds=(0.0, 10.0, 20.0, 30.0),
            service_seconds=(4.0, 4.0, 4.0, 4.0),
            multiplier=1.0,
        )
        self.assertTrue(result.stable_service_ratio)
        self.assertEqual(result.max_queue_depth, 0)
        self.assertEqual(result.max_wait_seconds, 0.0)

    def test_queue_simulation_exposes_saturation_at_higher_rate(self) -> None:
        baseline = simulate_single_consumer_queue_v0(
            producer_offsets_seconds=(0.0, 10.0, 20.0, 30.0),
            service_seconds=(8.0, 8.0, 8.0, 8.0),
            multiplier=1.0,
        )
        stressed = simulate_single_consumer_queue_v0(
            producer_offsets_seconds=(0.0, 10.0, 20.0, 30.0),
            service_seconds=(8.0, 8.0, 8.0, 8.0),
            multiplier=1.5,
        )
        self.assertTrue(baseline.stable_service_ratio)
        self.assertFalse(stressed.stable_service_ratio)
        self.assertGreater(stressed.p95_wait_seconds, baseline.p95_wait_seconds)
        self.assertGreater(stressed.final_lag_seconds, baseline.final_lag_seconds)

    def test_queue_simulation_rejects_unaligned_inputs(self) -> None:
        with self.assertRaises(ValueError):
            simulate_single_consumer_queue_v0(
                producer_offsets_seconds=(0.0, 1.0),
                service_seconds=(0.5,),
                multiplier=1.0,
            )

    def test_dual_clock_sampler_records_wall_monotonic_drift(self) -> None:
        sampler = DualClockSamplerV0(interval_seconds=0.01)
        sampler.start()
        samples = sampler.stop()
        self.assertGreaterEqual(len(samples), 2)
        self.assertIn("wall_elapsed_ns", samples[-1])
        self.assertIn("monotonic_elapsed_ns", samples[-1])
        self.assertIn("drift_ns", samples[-1])


if __name__ == "__main__":
    unittest.main()
