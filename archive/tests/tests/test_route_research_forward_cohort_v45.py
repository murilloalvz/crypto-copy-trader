from __future__ import annotations

import unittest

import route_research_forward_cohort_v43 as v43
import route_research_forward_cohort_v45 as v45


class RouteResearchForwardCohortV45Tests(unittest.TestCase):
    def test_v45_predeclares_larger_cohort_without_changing_v43_protocol_fields(self):
        argv = v45._v43_argv(run_key="cohort-v45")
        args = v43.build_parser().parse_args(argv[1:])
        self.assertEqual(args.run_key, "cohort-v45")
        self.assertEqual(args.max_research_episodes, 50)
        self.assertEqual(args.min_research_decisions, 40)
        self.assertEqual(args.duration_seconds, 120)
        self.assertEqual(args.research_notional_usd, 25.0)
        self.assertEqual(args.research_slippage_bps, 100)

    def test_v45_defaults_retain_v44_provider_pacing(self):
        args = v45.build_parser().parse_args(["--run-key", "cohort-v45"])
        self.assertEqual(args.hazard_start_interval_ms, 650)
        self.assertEqual(args.entry_start_interval_ms, 1000)
        self.assertEqual(args.exit_start_interval_ms, 250)

    def test_v45_constants_are_predeclared_and_minimum_is_below_cap(self):
        self.assertEqual(v45.V45_MAX_RESEARCH_EPISODES, 50)
        self.assertEqual(v45.V45_MIN_RESEARCH_DECISIONS, 40)
        self.assertLess(v45.V45_MIN_RESEARCH_DECISIONS, v45.V45_MAX_RESEARCH_EPISODES)
        self.assertGreaterEqual(v45.V45_MIN_RESEARCH_DECISIONS, 30)


if __name__ == "__main__":
    unittest.main()
