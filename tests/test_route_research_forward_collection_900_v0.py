from __future__ import annotations

import unittest
from unittest.mock import patch

from src.opportunity_route_research_store import RouteResearchForwardOutcome
from src.route_research_forward_collection_900_v0 import (
    TARGET_HORIZONS,
    collect_route_research_forward_through_900_v0,
)


class RouteResearchForwardCollection900V0Tests(unittest.TestCase):
    def test_target_horizons_are_frozen(self):
        self.assertEqual(TARGET_HORIZONS, (300, 900))

    def test_stall_before_first_poll_fails_closed_not_inconclusive(self):
        # Ported from tests/test_route_research_forward_cohort_v43.py's
        # test_stall_before_first_poll_fails_closed_not_inconclusive (commit
        # e4e95e8): a schedule exists, nothing is ever submitted or captured,
        # and the gap between the pre-loop monotonic reading and the first
        # loop check is far larger than one poll interval -- as it was when
        # the collector's print() blocked under Windows console QuickEdit
        # mode (v68-09-A, 2026-10-04).
        outcome = RouteResearchForwardOutcome(
            outcome_key="k1",
            acquisition_run_key="run",
            episode_key="episode-key-0000001",
            token_mint="So11111111111111111111111111111111111111112",
            research_decision_as_of=0,
            horizon_seconds=300,
            target_at=0,
            status="PENDING",
            observed_at=None,
            quote_key=None,
            error_type=None,
            error_message=None,
        )
        with patch(
            "src.route_research_forward_collection_900_v0.load_route_research_outcomes",
            return_value=(outcome,),
        ), patch(
            "src.route_research_forward_collection_900_v0.time.monotonic",
            side_effect=[0.0, 100.0],
        ):
            result = collect_route_research_forward_through_900_v0(
                acquisition_run_key="run",
                api_key=None,
            )
        self.assertTrue(result.stall_detected)
        self.assertEqual(result.stall_gap_seconds, 100.0)
        self.assertEqual(result.submitted, 0)
        self.assertEqual(
            result.classification,
            "FAIL_MEMORY_FORWARD_900_STALL_DETECTED",
        )
        self.assertNotEqual(
            result.classification,
            "INCONCLUSIVE_MEMORY_NO_AVAILABLE_300_900_OUTCOME",
        )


if __name__ == "__main__":
    unittest.main()
