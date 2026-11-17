from __future__ import annotations

import unittest

import route_research_systems_stability_v51 as v51


class RouteResearchSystemsStabilityV51Tests(unittest.TestCase):
    def test_systems_pass_is_independent_of_v50_attribution_completeness(self):
        output = """
V43 SAME-RUN SYSTEMS GATE
result=11/11
V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC
barrier_attribution_complete=False
causal_clock_attribution_acceptable=False
V51 STATEFUL-PRIORITY READY-QUEUE DIAGNOSTIC
"""
        verdict = v51.classify_v51_output(output)
        self.assertTrue(verdict.systems_pass)
        self.assertFalse(verdict.v50_attribution_ok)
        self.assertTrue(verdict.v51_present)
        self.assertEqual(
            verdict.classification,
            "PASS_V51_STATEFUL_PRIORITY_SYSTEMS_PROFILE_DIAGNOSTIC_INCOMPLETE",
        )

    def test_systems_failure_is_not_mislabeled_as_diagnostic_failure(self):
        output = """
V43 SAME-RUN SYSTEMS GATE
result=10/11
classification=FAIL_V43_SAME_RUN_SYSTEMS_GATE
V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC
barrier_attribution_complete=False
causal_clock_attribution_acceptable=False
V51 STATEFUL-PRIORITY READY-QUEUE DIAGNOSTIC
"""
        verdict = v51.classify_v51_output(output)
        self.assertFalse(verdict.systems_pass)
        self.assertFalse(verdict.v50_attribution_ok)
        self.assertEqual(
            verdict.classification,
            "FAIL_V51_STATEFUL_PRIORITY_SYSTEMS_PROFILE_DIAGNOSTIC_INCOMPLETE",
        )

    def test_full_pass_requires_both_systems_and_diagnostic_evidence(self):
        output = """
V43 SAME-RUN SYSTEMS GATE
result=11/11
V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC
barrier_attribution_complete=True
causal_clock_attribution_acceptable=True
dominant_clock=global_sequence_barrier
V51 STATEFUL-PRIORITY READY-QUEUE DIAGNOSTIC
"""
        verdict = v51.classify_v51_output(output)
        self.assertEqual(verdict.classification, "PASS_V51_STATEFUL_PRIORITY_SYSTEMS_PROFILE")

    def test_forward_collector_is_always_guard_failure(self):
        output = """
V43 SAME-RUN SYSTEMS GATE
result=11/11
V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC
barrier_attribution_complete=True
causal_clock_attribution_acceptable=True
dominant_clock=global_sequence_barrier
V51 STATEFUL-PRIORITY READY-QUEUE DIAGNOSTIC
V43 FORWARD COLLECTION START
"""
        verdict = v51.classify_v51_output(output)
        self.assertEqual(verdict.classification, "FAIL_V51_SYSTEMS_ONLY_GUARD")


if __name__ == "__main__":
    unittest.main()
