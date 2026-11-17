import unittest

from route_research_systems_diagnostic_v50 import diagnostic_capture_complete_v50


class RouteResearchSystemsDiagnosticV50Tests(unittest.TestCase):
    def test_exact_barrier_with_accepted_lifecycle_coverage_is_accepted(self):
        output = """
V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC
barrier_attribution_complete=True lifecycle_attribution_complete=False lifecycle_submit_coverage_pct=99.643 causal_clock_attribution_acceptable=True
dominant_clock=global_sequence_barrier
"""
        self.assertTrue(diagnostic_capture_complete_v50(output))

    def test_incomplete_barrier_is_rejected(self):
        output = """
V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC
barrier_attribution_complete=False lifecycle_attribution_complete=True lifecycle_submit_coverage_pct=100.000 causal_clock_attribution_acceptable=False
dominant_clock=global_sequence_barrier
"""
        self.assertFalse(diagnostic_capture_complete_v50(output))

    def test_low_lifecycle_coverage_is_rejected(self):
        output = """
V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC
barrier_attribution_complete=True lifecycle_attribution_complete=False lifecycle_submit_coverage_pct=94.000 causal_clock_attribution_acceptable=False
dominant_clock=global_sequence_barrier
"""
        self.assertFalse(diagnostic_capture_complete_v50(output))

    def test_insufficient_clock_is_rejected_even_if_markers_are_wrongly_positive(self):
        output = """
V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC
barrier_attribution_complete=True lifecycle_attribution_complete=True lifecycle_submit_coverage_pct=100.000 causal_clock_attribution_acceptable=True
dominant_clock=insufficient_trace
"""
        self.assertFalse(diagnostic_capture_complete_v50(output))


if __name__ == "__main__":
    unittest.main()
