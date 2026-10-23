from __future__ import annotations

import unittest

import route_research_systems_stability_v54 as v54


_BASE_DIAGNOSTICS = """
V51 STATEFUL-PRIORITY READY-QUEUE DIAGNOSTIC
V52 PUMPSWAP HEDGED RPC WALL-DEADLINE DIAGNOSTIC
hedge_cleanup_ms p50=1.0 p95=2.0 max=3.0
V53 OPPORTUNISTIC PREFETCH / RESOLVER WAIT DIAGNOSTIC
V54 DEMAND-ONLY RESOLVER ADMISSION DIAGNOSTIC
notifications_seen=10 candidate_pools=12 scheduled=0 skipped_speculative=12 active_after_drain=0
"""


class RouteResearchSystemsStabilityV54Tests(unittest.TestCase):
    def test_pass_requires_11_of_11_and_demand_only_diagnostic(self):
        output = _BASE_DIAGNOSTICS + "\nresult=11/11\n"
        verdict = v54.classify_v54_output(output)
        self.assertTrue(verdict.systems_pass)
        self.assertTrue(verdict.v54_demand_only_ok)
        self.assertEqual(
            verdict.classification,
            "PASS_V54_DEMAND_ONLY_RESOLUTION_SYSTEMS_PROFILE_DIAGNOSTIC_INCOMPLETE",
        )

    def test_nonzero_speculative_schedule_fails_closed(self):
        output = _BASE_DIAGNOSTICS.replace("scheduled=0", "scheduled=1") + "\nresult=11/11\n"
        verdict = v54.classify_v54_output(output)
        self.assertFalse(verdict.v54_demand_only_ok)
        self.assertEqual(verdict.classification, "FAIL_V54_DIAGNOSTIC_MISSING")

    def test_forward_collector_is_forbidden(self):
        output = _BASE_DIAGNOSTICS + "\nresult=11/11\nV43 FORWARD COLLECTION START\n"
        verdict = v54.classify_v54_output(output)
        self.assertTrue(verdict.collector_started)
        self.assertEqual(verdict.classification, "FAIL_V54_SYSTEMS_ONLY_GUARD")

    def test_systems_failure_is_not_rescued_by_diagnostics(self):
        output = _BASE_DIAGNOSTICS + "\nresult=10/11\nclassification=FAIL_V43_SAME_RUN_SYSTEMS_GATE\n"
        verdict = v54.classify_v54_output(output)
        self.assertFalse(verdict.systems_pass)
        self.assertIn("FAIL_V54_DEMAND_ONLY_RESOLUTION_SYSTEMS_PROFILE", verdict.classification)


if __name__ == "__main__":
    unittest.main()
