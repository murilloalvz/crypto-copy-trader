from collections import Counter
import unittest

from unified_market_route_research_smoke_v41 import classify_route_research_v41


class RouteResearchSmokeV41AccountingTests(unittest.TestCase):
    def _base(self) -> Counter[str]:
        return Counter(
            {
                "hazard_terminal_provider_error": 1,
                "entry_eligible": 11,
                "entry_status_available": 11,
                "research_decisions_frozen": 11,
                "research_outcomes_scheduled": 33,
            }
        )

    def test_terminal_hazard_provider_error_is_explicit_upstream_disposition_not_missing_entry(self):
        counters = self._base()
        self.assertEqual(
            classify_route_research_v41(selected_count=12, counters=counters),
            "PASS_ROUTE_ONLY_RESEARCH_DECISION_PLUMBING",
        )

    def test_missing_entry_after_available_hazard_still_fails(self):
        counters = self._base()
        counters["entry_eligible"] = 12
        self.assertEqual(
            classify_route_research_v41(selected_count=12, counters=counters),
            "FAIL_ROUTE_ONLY_RESEARCH_DECISION_PLUMBING",
        )

    def test_entry_config_missing_fails_even_when_all_selected_are_terminally_accounted(self):
        counters = Counter(
            {
                "entry_eligible": 12,
                "entry_status_available": 11,
                "entry_status_config_missing": 1,
                "research_decisions_frozen": 11,
                "research_outcomes_scheduled": 33,
            }
        )
        self.assertEqual(
            classify_route_research_v41(selected_count=12, counters=counters),
            "FAIL_ROUTE_ONLY_RESEARCH_DECISION_PLUMBING",
        )

    def test_fully_terminal_but_no_available_entry_is_inconclusive_not_plumbing_failure(self):
        counters = Counter(
            {
                "entry_eligible": 12,
                "entry_status_provider_error": 12,
            }
        )
        self.assertEqual(
            classify_route_research_v41(selected_count=12, counters=counters),
            "INCONCLUSIVE_NO_AVAILABLE_RESEARCH_ENTRY",
        )


if __name__ == "__main__":
    unittest.main()
