from __future__ import annotations

import unittest

import route_research_systems_stability_v52 as v52


class RouteResearchSystemsStabilityV52Tests(unittest.TestCase):
    def test_full_systems_pass_with_complete_trace(self):
        output = """
V43 SAME-RUN SYSTEMS GATE
result=11/11
V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC
barrier_attribution_complete=True
causal_clock_attribution_acceptable=True
dominant_clock=global_sequence_barrier
V51 STATEFUL-PRIORITY READY-QUEUE DIAGNOSTIC
V52 PUMPSWAP HEDGED RPC WALL-DEADLINE DIAGNOSTIC
"""
        verdict = v52.classify_v52_output(output)
        self.assertTrue(verdict.systems_pass)
        self.assertTrue(verdict.v50_attribution_ok)
        self.assertEqual(
            verdict.classification,
            "PASS_V52_HEDGE_WALL_DEADLINE_SYSTEMS_PROFILE",
        )

    def test_systems_pass_survives_frozen_deadline_trace_incompleteness(self):
        output = """
V43 SAME-RUN SYSTEMS GATE
result=11/11
V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC
barrier_attribution_complete=False
causal_clock_attribution_acceptable=False
V51 STATEFUL-PRIORITY READY-QUEUE DIAGNOSTIC
V52 PUMPSWAP HEDGED RPC WALL-DEADLINE DIAGNOSTIC
"""
        verdict = v52.classify_v52_output(output)
        self.assertTrue(verdict.systems_pass)
        self.assertFalse(verdict.v50_attribution_ok)
        self.assertEqual(
            verdict.classification,
            "PASS_V52_HEDGE_WALL_DEADLINE_SYSTEMS_PROFILE_DIAGNOSTIC_INCOMPLETE",
        )

    def test_systems_failure_is_kept_independent_from_trace_quality(self):
        output = """
V43 SAME-RUN SYSTEMS GATE
result=10/11
classification=FAIL_V43_SAME_RUN_SYSTEMS_GATE
V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC
barrier_attribution_complete=False
causal_clock_attribution_acceptable=False
V51 STATEFUL-PRIORITY READY-QUEUE DIAGNOSTIC
V52 PUMPSWAP HEDGED RPC WALL-DEADLINE DIAGNOSTIC
"""
        verdict = v52.classify_v52_output(output)
        self.assertFalse(verdict.systems_pass)
        self.assertEqual(
            verdict.classification,
            "FAIL_V52_HEDGE_WALL_DEADLINE_SYSTEMS_PROFILE_DIAGNOSTIC_INCOMPLETE",
        )

    def test_forward_collector_is_always_fatal(self):
        output = """
V43 SAME-RUN SYSTEMS GATE
result=11/11
V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC
barrier_attribution_complete=True
causal_clock_attribution_acceptable=True
dominant_clock=global_sequence_barrier
V51 STATEFUL-PRIORITY READY-QUEUE DIAGNOSTIC
V52 PUMPSWAP HEDGED RPC WALL-DEADLINE DIAGNOSTIC
V43 FORWARD COLLECTION START
"""
        verdict = v52.classify_v52_output(output)
        self.assertEqual(verdict.classification, "FAIL_V52_SYSTEMS_ONLY_GUARD")

    def test_missing_v52_diagnostic_fails_closed(self):
        output = """
V43 SAME-RUN SYSTEMS GATE
result=11/11
V51 STATEFUL-PRIORITY READY-QUEUE DIAGNOSTIC
"""
        verdict = v52.classify_v52_output(output)
        self.assertEqual(verdict.classification, "FAIL_V52_DIAGNOSTIC_MISSING")


if __name__ == "__main__":
    unittest.main()
