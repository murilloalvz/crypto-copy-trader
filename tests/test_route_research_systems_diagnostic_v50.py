import unittest

from route_research_systems_diagnostic_v50 import diagnostic_capture_complete_v50


class RouteResearchSystemsDiagnosticV50Tests(unittest.TestCase):
    def test_complete_capture_is_accepted(self):
        output = """
V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC
trace_attribution_complete=True
dominant_clock=global_sequence_barrier
"""
        self.assertTrue(diagnostic_capture_complete_v50(output))

    def test_empty_capture_is_rejected_even_with_header(self):
        output = """
V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC
trace_attribution_complete=False
dominant_clock=insufficient_trace
"""
        self.assertFalse(diagnostic_capture_complete_v50(output))

    def test_insufficient_clock_is_rejected_even_if_complete_marker_is_wrongly_present(self):
        output = """
V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC
trace_attribution_complete=True
dominant_clock=insufficient_trace
"""
        self.assertFalse(diagnostic_capture_complete_v50(output))


if __name__ == "__main__":
    unittest.main()
