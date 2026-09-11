import unittest

from benchmarks.market_activity_discovery_v0.smoke import (
    PASS_CLASSIFICATION,
    run_offline_smoke,
)


class MarketActivityDiscoveryOfflineSmokeV0Tests(unittest.TestCase):
    def test_smoke_covers_run_denominator_replay_boundary_and_pending_outcomes(self):
        result = run_offline_smoke()

        self.assertTrue(result["valid_smoke"])
        self.assertEqual(result["classification"], PASS_CLASSIFICATION)
        self.assertEqual(result["run_status"], "CLOSED")
        self.assertEqual(result["duration_seconds"], 21600)
        self.assertEqual(result["cohort_denominator"], 2)
        self.assertEqual(
            result["dispositions"],
            {"ANALYZABLE_T0": 1, "T0_NOT_FROZEN": 1},
        )
        self.assertEqual(result["forward_horizons_seconds"], [300, 900, 3600])
        self.assertEqual(result["forward_statuses"], ["PENDING", "PENDING", "PENDING"])
        self.assertTrue(result["late_boundary_rejected"])
        self.assertTrue(result["exact_replay_idempotent"])
        self.assertEqual(result["provider_calls_performed"], 0)
        self.assertFalse(result["economic_edge_evaluated"])


if __name__ == "__main__":
    unittest.main()
