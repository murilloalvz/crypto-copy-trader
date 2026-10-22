from __future__ import annotations

import contextlib
import io
import unittest

import route_research_systems_stability_tailfix_v1 as tailfix_guard


class RouteResearchSystemsStabilityTailfixV1Tests(unittest.TestCase):
    def test_wrapper_injects_tailfix_runner_and_restores_v54_global(self):
        original_guard_main = tailfix_guard.v54_guard.main
        original_run_smoke = tailfix_guard.v54_guard.v54.run_smoke_v54
        observed = {}

        def fake_guard_main() -> int:
            observed["during"] = tailfix_guard.v54_guard.v54.run_smoke_v54
            return 0

        tailfix_guard.v54_guard.main = fake_guard_main
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                result = tailfix_guard.main()
        finally:
            tailfix_guard.v54_guard.main = original_guard_main

        self.assertEqual(result, 0)
        self.assertIs(observed["during"], tailfix_guard.tailfix.run_smoke_tailfix_v1)
        self.assertIs(tailfix_guard.v54_guard.v54.run_smoke_v54, original_run_smoke)
        self.assertIn("PASS_TAILFIX_V1_UNCHANGED_11_GATE", output.getvalue())

    def test_nonzero_inherited_guard_is_not_rescued(self):
        original_guard_main = tailfix_guard.v54_guard.main
        tailfix_guard.v54_guard.main = lambda: 2
        try:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = tailfix_guard.main()
        finally:
            tailfix_guard.v54_guard.main = original_guard_main

        self.assertEqual(result, 2)
        self.assertIn("FAIL_TAILFIX_V1_UNCHANGED_11_GATE", output.getvalue())


if __name__ == "__main__":
    unittest.main()
