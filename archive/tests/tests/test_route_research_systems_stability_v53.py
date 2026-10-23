from __future__ import annotations

import unittest

import route_research_systems_stability_v53 as v53


_BASE_DIAGNOSTICS = """
V51 STATEFUL-PRIORITY READY-QUEUE DIAGNOSTIC
V52 PUMPSWAP HEDGED RPC WALL-DEADLINE DIAGNOSTIC
hedge_cleanup_ms p50=1.0 p95=2.0 max=3.0
V53 OPPORTUNISTIC PREFETCH / RESOLVER WAIT DIAGNOSTIC
"""


class RouteResearchSystemsStabilityV53Tests(unittest.TestCase):
    def test_full_pass_requires_systems_and_complete_trace(self):
        output = (
            "V43 SAME-RUN SYSTEMS GATE\nresult=11/11\n"
            "V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC\n"
            "barrier_attribution_complete=True\n"
            "causal_clock_attribution_acceptable=True\n"
            "dominant_clock=global_sequence_barrier\n"
            + _BASE_DIAGNOSTICS
        )
        verdict = v53.classify_v53_output(output)
        self.assertTrue(verdict.systems_pass)
        self.assertTrue(verdict.v50_attribution_ok)
        self.assertEqual(
            verdict.classification,
            "PASS_V53_OPPORTUNISTIC_PREFETCH_SYSTEMS_PROFILE",
        )

    def test_systems_pass_survives_incomplete_v50_trace(self):
        output = (
            "V43 SAME-RUN SYSTEMS GATE\nresult=11/11\n"
            "V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC\n"
            "barrier_attribution_complete=False\n"
            "causal_clock_attribution_acceptable=False\n"
            + _BASE_DIAGNOSTICS
        )
        verdict = v53.classify_v53_output(output)
        self.assertTrue(verdict.systems_pass)
        self.assertFalse(verdict.v50_attribution_ok)
        self.assertEqual(
            verdict.classification,
            "PASS_V53_OPPORTUNISTIC_PREFETCH_SYSTEMS_PROFILE_DIAGNOSTIC_INCOMPLETE",
        )

    def test_systems_failure_remains_failure_with_incomplete_trace(self):
        output = (
            "V43 SAME-RUN SYSTEMS GATE\nresult=10/11\n"
            "classification=FAIL_V43_SAME_RUN_SYSTEMS_GATE\n"
            "V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC\n"
            "barrier_attribution_complete=False\n"
            "causal_clock_attribution_acceptable=False\n"
            + _BASE_DIAGNOSTICS
        )
        verdict = v53.classify_v53_output(output)
        self.assertFalse(verdict.systems_pass)
        self.assertEqual(
            verdict.classification,
            "FAIL_V53_OPPORTUNISTIC_PREFETCH_SYSTEMS_PROFILE_DIAGNOSTIC_INCOMPLETE",
        )

    def test_missing_v52_cleanup_fails_closed(self):
        output = """
V43 SAME-RUN SYSTEMS GATE
result=11/11
V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC
barrier_attribution_complete=True
causal_clock_attribution_acceptable=True
dominant_clock=global_sequence_barrier
V51 STATEFUL-PRIORITY READY-QUEUE DIAGNOSTIC
V52 PUMPSWAP HEDGED RPC WALL-DEADLINE DIAGNOSTIC
V53 OPPORTUNISTIC PREFETCH / RESOLVER WAIT DIAGNOSTIC
"""
        verdict = v53.classify_v53_output(output)
        self.assertEqual(verdict.classification, "FAIL_V53_DIAGNOSTIC_MISSING")

    def test_missing_v53_instance_fails_closed(self):
        output = (
            "V43 SAME-RUN SYSTEMS GATE\nresult=11/11\n"
            "V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC\n"
            "barrier_attribution_complete=True\n"
            "causal_clock_attribution_acceptable=True\n"
            "dominant_clock=global_sequence_barrier\n"
            + _BASE_DIAGNOSTICS
            + "v53_resolver_instance=missing\n"
        )
        verdict = v53.classify_v53_output(output)
        self.assertEqual(verdict.classification, "FAIL_V53_DIAGNOSTIC_MISSING")

    def test_forward_collector_is_always_fatal(self):
        output = (
            "V43 SAME-RUN SYSTEMS GATE\nresult=11/11\n"
            "V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC\n"
            "barrier_attribution_complete=True\n"
            "causal_clock_attribution_acceptable=True\n"
            "dominant_clock=global_sequence_barrier\n"
            + _BASE_DIAGNOSTICS
            + "V43 FORWARD COLLECTION START\n"
        )
        verdict = v53.classify_v53_output(output)
        self.assertEqual(verdict.classification, "FAIL_V53_SYSTEMS_ONLY_GUARD")


if __name__ == "__main__":
    unittest.main()
