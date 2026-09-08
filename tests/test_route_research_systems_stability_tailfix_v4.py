from __future__ import annotations

from types import SimpleNamespace
import unittest

import route_research_systems_stability_tailfix_v4 as wrapper


class RouteResearchSystemsStabilityTailfixV4Tests(unittest.TestCase):
    def setUp(self):
        self.original_latency_report = wrapper.tailfix_v3.last_headroom_report_v3
        self.original_writer_report = wrapper.tailfix_v4.last_writer_pressure_v4
        self.original_writer_warning = wrapper.tailfix_v4.last_writer_pressure_warning_v4
        self.original_writer_share = wrapper.tailfix_v4.last_writer_pressure_share_v4

    def tearDown(self):
        wrapper.tailfix_v3.last_headroom_report_v3 = self.original_latency_report
        wrapper.tailfix_v4.last_writer_pressure_v4 = self.original_writer_report
        wrapper.tailfix_v4.last_writer_pressure_warning_v4 = self.original_writer_warning
        wrapper.tailfix_v4.last_writer_pressure_share_v4 = self.original_writer_share

    def _install_clean_preventive_reports(self):
        wrapper.tailfix_v3.last_headroom_report_v3 = SimpleNamespace(warning_stages=())
        wrapper.tailfix_v4.last_writer_pressure_v4 = SimpleNamespace(queue_high_water=10)
        wrapper.tailfix_v4.last_writer_pressure_warning_v4 = False
        wrapper.tailfix_v4.last_writer_pressure_share_v4 = 0.10

    def test_injects_and_restores_v4_runner_on_clean_pass(self):
        original_runner = wrapper.v54_guard.v54.run_smoke_v54
        original_main = wrapper.v54_guard.main
        observed = {}
        self._install_clean_preventive_reports()

        def fake_main():
            observed["runner"] = wrapper.v54_guard.v54.run_smoke_v54
            return 0

        wrapper.v54_guard.main = fake_main
        try:
            result = wrapper.main()
        finally:
            wrapper.v54_guard.main = original_main

        self.assertEqual(result, 0)
        self.assertIs(observed["runner"], wrapper.tailfix_v4.run_smoke_tailfix_v4)
        self.assertIs(wrapper.v54_guard.v54.run_smoke_v54, original_runner)

    def test_official_pass_is_held_on_latency_warning(self):
        original_main = wrapper.v54_guard.main
        self._install_clean_preventive_reports()
        wrapper.tailfix_v3.last_headroom_report_v3 = SimpleNamespace(
            warning_stages=("reservation_to_submit",)
        )
        wrapper.v54_guard.main = lambda: 0
        try:
            result = wrapper.main()
        finally:
            wrapper.v54_guard.main = original_main

        self.assertEqual(result, wrapper.V4_PROMOTION_HOLD_EXIT)

    def test_official_pass_is_held_on_writer_pressure_warning(self):
        original_main = wrapper.v54_guard.main
        self._install_clean_preventive_reports()
        wrapper.tailfix_v4.last_writer_pressure_warning_v4 = True
        wrapper.tailfix_v4.last_writer_pressure_share_v4 = 0.85
        wrapper.v54_guard.main = lambda: 0
        try:
            result = wrapper.main()
        finally:
            wrapper.v54_guard.main = original_main

        self.assertEqual(result, wrapper.V4_PROMOTION_HOLD_EXIT)

    def test_official_pass_is_held_when_writer_report_is_missing(self):
        original_main = wrapper.v54_guard.main
        self._install_clean_preventive_reports()
        wrapper.tailfix_v4.last_writer_pressure_v4 = None
        wrapper.v54_guard.main = lambda: 0
        try:
            result = wrapper.main()
        finally:
            wrapper.v54_guard.main = original_main

        self.assertEqual(result, wrapper.V4_PROMOTION_HOLD_EXIT)

    def test_nonzero_frozen_guard_is_not_rescued(self):
        original_runner = wrapper.v54_guard.v54.run_smoke_v54
        original_main = wrapper.v54_guard.main
        self._install_clean_preventive_reports()
        wrapper.v54_guard.main = lambda: 9
        try:
            result = wrapper.main()
        finally:
            wrapper.v54_guard.main = original_main

        self.assertEqual(result, 9)
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
