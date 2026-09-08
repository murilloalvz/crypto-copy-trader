from __future__ import annotations

import unittest

import route_research_systems_stability_tailfix_v3 as wrapper


class RouteResearchSystemsStabilityTailfixV3Tests(unittest.TestCase):
    def test_injects_and_restores_tailfix_runner_on_success(self):
        original_runner = wrapper.v54_guard.v54.run_smoke_v54
        original_main = wrapper.v54_guard.main
        observed = {}

        def fake_main():
            observed["runner"] = wrapper.v54_guard.v54.run_smoke_v54
            return 0

        wrapper.v54_guard.main = fake_main
        try:
            result = wrapper.main()
        finally:
            wrapper.v54_guard.main = original_main

        self.assertEqual(result, 0)
        self.assertIs(observed["runner"], wrapper.tailfix.run_smoke_tailfix_v3)
        self.assertIs(wrapper.v54_guard.v54.run_smoke_v54, original_runner)

    def test_nonzero_frozen_guard_is_not_rescued(self):
        original_runner = wrapper.v54_guard.v54.run_smoke_v54
        original_main = wrapper.v54_guard.main
        wrapper.v54_guard.main = lambda: 7
        try:
            result = wrapper.main()
        finally:
            wrapper.v54_guard.main = original_main

        self.assertEqual(result, 7)
        self.assertIs(wrapper.v54_guard.v54.run_smoke_v54, original_runner)

    def test_restores_runner_on_exception(self):
        original_runner = wrapper.v54_guard.v54.run_smoke_v54
        original_main = wrapper.v54_guard.main

        def explode():
            raise RuntimeError("boom")

        wrapper.v54_guard.main = explode
        try:
            with self.assertRaisesRegex(RuntimeError, "boom"):
                wrapper.main()
        finally:
            wrapper.v54_guard.main = original_main

        self.assertIs(wrapper.v54_guard.v54.run_smoke_v54, original_runner)


if __name__ == "__main__":
    unittest.main()
