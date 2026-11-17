from __future__ import annotations

from types import SimpleNamespace
import unittest

import route_research_prospective_holdout_v48 as v48


class RouteResearchProspectiveHoldoutV48V54WiringTests(unittest.TestCase):
    def test_validated_profile_is_v54_demand_only(self):
        self.assertEqual(v48.V48_VALIDATED_SYSTEMS_PROFILE, "v54_demand_only_resolution")
        self.assertIs(v48.v54.run_smoke_v54, v48.v54.run_smoke_v54)
        self.assertEqual(v48.V48_VALIDATED_PUMP_PREPARE_WORKERS, 20)

    def test_run_v46_installs_v54_only_during_acquisition_and_restores_globals(self):
        original_runner = v48.v43.v42.run_smoke_v42
        original_workers = v48.v31.PASS_PUMP_PREPARE_WORKERS
        original_main = v48.v46.main
        observed = {}
        args = SimpleNamespace(
            hazard_start_interval_ms=650,
            entry_start_interval_ms=1000,
            exit_start_interval_ms=250,
        )

        def fake_main():
            observed["runner"] = v48.v43.v42.run_smoke_v42
            observed["workers"] = v48.v31.PASS_PUMP_PREPARE_WORKERS
            return 0

        v48.v46.main = fake_main
        try:
            result = v48._run_v46(args, "fresh-v48-v54")
        finally:
            v48.v46.main = original_main

        self.assertEqual(result, 0)
        self.assertIs(observed["runner"], v48.v54.run_smoke_v54)
        self.assertEqual(observed["workers"], 20)
        self.assertIs(v48.v43.v42.run_smoke_v42, original_runner)
        self.assertEqual(v48.v31.PASS_PUMP_PREPARE_WORKERS, original_workers)

    def test_run_v46_restores_globals_on_failure(self):
        original_runner = v48.v43.v42.run_smoke_v42
        original_workers = v48.v31.PASS_PUMP_PREPARE_WORKERS
        original_main = v48.v46.main
        args = SimpleNamespace(
            hazard_start_interval_ms=650,
            entry_start_interval_ms=1000,
            exit_start_interval_ms=250,
        )

        def fake_main():
            raise RuntimeError("boom")

        v48.v46.main = fake_main
        try:
            with self.assertRaisesRegex(RuntimeError, "boom"):
                v48._run_v46(args, "fresh-v48-v54-fail")
        finally:
            v48.v46.main = original_main

        self.assertIs(v48.v43.v42.run_smoke_v42, original_runner)
        self.assertEqual(v48.v31.PASS_PUMP_PREPARE_WORKERS, original_workers)


if __name__ == "__main__":
    unittest.main()
