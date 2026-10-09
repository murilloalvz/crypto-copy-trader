from __future__ import annotations

from types import SimpleNamespace
import sys
import unittest

import route_research_early_opportunity_discovery_v55 as v55


class RouteResearchEarlyOpportunityDiscoveryV55Tests(unittest.TestCase):
    def test_frozen_systems_profile_is_v54(self):
        self.assertEqual(v55.V55_SYSTEMS_PROFILE, "v54_demand_only_resolution")
        self.assertEqual(v55.V55_PUMP_PREPARE_WORKERS, 20)

    def test_run_v46_installs_v54_and_restores_globals(self):
        original_runner = v55.v43.v42.run_smoke_v42
        original_workers = v55.v31.PASS_PUMP_PREPARE_WORKERS
        original_main = v55.v46.main
        original_argv = list(sys.argv)
        observed = {}
        args = SimpleNamespace(
            hazard_start_interval_ms=650,
            entry_start_interval_ms=1000,
            exit_start_interval_ms=250,
        )

        def fake_main():
            observed["runner"] = v55.v43.v42.run_smoke_v42
            observed["workers"] = v55.v31.PASS_PUMP_PREPARE_WORKERS
            observed["argv"] = list(sys.argv)
            return 0

        v55.v46.main = fake_main
        try:
            result = v55._run_v46(args, "fresh-v55")
        finally:
            v55.v46.main = original_main

        self.assertEqual(result, 0)
        self.assertIs(observed["runner"], v55.v54.run_smoke_v54)
        self.assertEqual(observed["workers"], 20)
        self.assertEqual(observed["argv"][0], "route_research_forward_cohort_v46.py")
        self.assertIn("fresh-v55", observed["argv"])
        self.assertIs(v55.v43.v42.run_smoke_v42, original_runner)
        self.assertEqual(v55.v31.PASS_PUMP_PREPARE_WORKERS, original_workers)
        self.assertEqual(sys.argv, original_argv)

    def test_run_v46_restores_globals_on_failure(self):
        original_runner = v55.v43.v42.run_smoke_v42
        original_workers = v55.v31.PASS_PUMP_PREPARE_WORKERS
        original_main = v55.v46.main
        original_argv = list(sys.argv)
        args = SimpleNamespace(
            hazard_start_interval_ms=650,
            entry_start_interval_ms=1000,
            exit_start_interval_ms=250,
        )

        def boom():
            raise RuntimeError("synthetic")

        v55.v46.main = boom
        try:
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                v55._run_v46(args, "fresh-v55-fail")
        finally:
            v55.v46.main = original_main

        self.assertIs(v55.v43.v42.run_smoke_v42, original_runner)
        self.assertEqual(v55.v31.PASS_PUMP_PREPARE_WORKERS, original_workers)
        self.assertEqual(sys.argv, original_argv)


if __name__ == "__main__":
    unittest.main()
