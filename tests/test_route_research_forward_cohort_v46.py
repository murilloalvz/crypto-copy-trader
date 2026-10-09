from __future__ import annotations

import unittest

import route_research_forward_cohort_v46 as v46


class RouteResearchForwardCohortV46Tests(unittest.TestCase):
    def test_run_keys_are_stable_and_distinct(self):
        self.assertEqual(v46._run_key("cohort", "A"), "cohort-A")
        self.assertEqual(v46._run_key("cohort", "B"), "cohort-B")
        self.assertNotEqual(v46._run_key("cohort", "A"), v46._run_key("cohort", "B"))

    def test_subcohort_gate_requires_full_structural_and_collection_pass(self):
        output = """
V43 SAME-RUN SYSTEMS GATE
coverage_pct=99.9 true_backlog_pct=0.1 pump_p95_ms=1200 pumpswap_p95_ms=3200 result=11/11
V43 FRESH COHORT ADMISSION GATE
research_decisions=39 scheduled_outcomes=117 exact_three_horizons_per_decision=True minimum=30
V43 FORWARD COLLECTION SUMMARY
target_lateness_seconds p50=0 p95=1 max=1
forward_collection_classification=PASS_ROUTE_ONLY_FORWARD_COLLECTION_COMPLETE
V43 DESCRIPTIVE ROUTE-ONLY ECONOMIC EVALUATION
run_key=test lineage_violations=0
"""
        passed, details = v46._subcohort_gate(output)
        self.assertTrue(passed)
        self.assertEqual(details["research_decisions"], 39)
        self.assertEqual(details["target_lateness_p95_seconds"], 1)

    def test_subcohort_gate_fails_if_systems_are_10_of_11(self):
        output = """
V43 SAME-RUN SYSTEMS GATE
coverage_pct=99.7 true_backlog_pct=0.3 pump_p95_ms=2732 pumpswap_p95_ms=9512 result=10/11
classification=FAIL_V43_SAME_RUN_SYSTEMS_GATE
"""
        passed, details = v46._subcohort_gate(output)
        self.assertFalse(passed)
        self.assertFalse(details["systems_11_of_11"])

    def test_subcohort_gate_fails_below_30_decisions(self):
        output = """
V43 SAME-RUN SYSTEMS GATE
result=11/11
V43 FRESH COHORT ADMISSION GATE
research_decisions=29 scheduled_outcomes=87 exact_three_horizons_per_decision=True minimum=30
"""
        passed, details = v46._subcohort_gate(output)
        self.assertFalse(passed)
        self.assertEqual(details["research_decisions"], 29)

    def test_protocol_keeps_each_subcohort_at_v44_size(self):
        self.assertEqual(v46.SUBCOHORT_CAP, 40)
        self.assertEqual(v46.SUBCOHORT_MIN_DECISIONS, 30)
        self.assertEqual(v46.SUBCOHORT_SUFFIXES, ("A", "B"))


if __name__ == "__main__":
    unittest.main()
