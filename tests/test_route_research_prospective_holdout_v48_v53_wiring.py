from __future__ import annotations

import argparse
import sys
import unittest
from unittest.mock import patch

import route_research_prospective_holdout_v48 as v48


class V48V53WiringTests(unittest.TestCase):
    def test_validated_profile_constants_are_frozen(self):
        self.assertEqual(v48.V48_VALIDATED_SYSTEMS_PROFILE, "v53_opportunistic_prefetch")
        self.assertEqual(v48.V48_VALIDATED_PUMP_PREPARE_WORKERS, 20)

    def test_run_v46_installs_v53_only_for_acquisition_and_restores_globals(self):
        args = argparse.Namespace(
            hazard_start_interval_ms=650,
            entry_start_interval_ms=1000,
            exit_start_interval_ms=250,
        )
        original_run = v48.v43.v42.run_smoke_v42
        original_workers = v48.v31.PASS_PUMP_PREPARE_WORKERS
        original_argv = list(sys.argv)

        def fake_main():
            self.assertIs(v48.v43.v42.run_smoke_v42, v48.v53.run_smoke_v53)
            self.assertEqual(v48.v31.PASS_PUMP_PREPARE_WORKERS, 20)
            self.assertEqual(
                sys.argv,
                [
                    "route_research_forward_cohort_v46.py",
                    "--run-key",
                    "fresh-base",
                    "--hazard-start-interval-ms",
                    "650",
                    "--entry-start-interval-ms",
                    "1000",
                    "--exit-start-interval-ms",
                    "250",
                ],
            )
            return 0

        with patch.object(v48.v46, "main", new=fake_main):
            result = v48._run_v46(args, "fresh-base")

        self.assertEqual(result, 0)
        self.assertIs(v48.v43.v42.run_smoke_v42, original_run)
        self.assertEqual(v48.v31.PASS_PUMP_PREPARE_WORKERS, original_workers)
        self.assertEqual(sys.argv, original_argv)

    def test_run_v46_restores_globals_even_when_acquisition_raises(self):
        args = argparse.Namespace(
            hazard_start_interval_ms=650,
            entry_start_interval_ms=1000,
            exit_start_interval_ms=250,
        )
        original_run = v48.v43.v42.run_smoke_v42
        original_workers = v48.v31.PASS_PUMP_PREPARE_WORKERS
        original_argv = list(sys.argv)

        def boom():
            raise RuntimeError("synthetic")

        with patch.object(v48.v46, "main", new=boom):
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                v48._run_v46(args, "fresh-base")

        self.assertIs(v48.v43.v42.run_smoke_v42, original_run)
        self.assertEqual(v48.v31.PASS_PUMP_PREPARE_WORKERS, original_workers)
        self.assertEqual(sys.argv, original_argv)

    def test_frozen_economic_protocol_constants_remain_unchanged(self):
        self.assertEqual(v48.V48_LOW_MAX, 25)
        self.assertEqual(v48.V48_MID_MAX, 47)
        self.assertEqual(v48.V48_PRIMARY_HORIZON_SECONDS, 900)
        self.assertEqual(v48.V48_MIN_GROUP_SUPPORT_PER_SUBCOHORT, 5)
        self.assertEqual(v48.v46.SUBCOHORT_CAP, 40)
        self.assertEqual(v48.v46.SUBCOHORT_MIN_DECISIONS, 30)


if __name__ == "__main__":
    unittest.main()
