from __future__ import annotations

import unittest

from benchmarks.launch_burst_opportunity_lab_v0.copyability import _feature_stat


class LaunchBurstCopyabilityDiagnosticsV0Tests(unittest.TestCase):
    def test_feature_stat_detects_route_closed_separation(self):
        rows = []
        for value in (8.0, 9.0, 10.0):
            rows.append({"status": "ROUTE_CLOSED", "features": {"x": value}})
        for value in (1.0, 2.0, 3.0, 4.0):
            rows.append({"status": "UNROUTABLE_EXIT:SELL", "features": {"x": value}})
        stat = _feature_stat("x", rows)
        self.assertEqual(stat["direction"], "HIGHER_IN_ROUTE_CLOSED")
        self.assertEqual(stat["auc_probability_higher_value_in_route_closed"], 1.0)
        self.assertEqual(stat["hypothesis_generation_status"], "COPYABILITY_RESEARCH_PRIORITY")
        self.assertIsNone(stat["threshold_recommendation"])

    def test_small_unroutable_sample_cannot_be_priority(self):
        rows = [
            {"status": "ROUTE_CLOSED", "features": {"x": 5.0}},
            {"status": "ROUTE_CLOSED", "features": {"x": 6.0}},
            {"status": "ROUTE_CLOSED", "features": {"x": 7.0}},
            {"status": "UNROUTABLE_EXIT:SELL", "features": {"x": 1.0}},
        ]
        stat = _feature_stat("x", rows)
        self.assertEqual(stat["hypothesis_generation_status"], "INSUFFICIENT_SAMPLE_OR_COVERAGE")


if __name__ == "__main__":
    unittest.main()
