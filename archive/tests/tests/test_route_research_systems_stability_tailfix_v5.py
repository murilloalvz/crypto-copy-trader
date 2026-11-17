from __future__ import annotations

from types import SimpleNamespace
import unittest

import route_research_systems_stability_tailfix_v5 as wrapper


class RouteResearchSystemsStabilityTailfixV5Tests(unittest.TestCase):
    def setUp(self):
        self.original_latency = wrapper.tailfix_v3.last_headroom_report_v3
        self.original_writer = wrapper.tailfix_v5.last_writer_headroom_v5
        self.original_writer_warning = wrapper.tailfix_v5.last_writer_warning_v5
        self.original_writer_share = wrapper.tailfix_v5.last_writer_queue_p95_share_v5
        self.original_resolver = wrapper.tailfix_v5.last_resolver_snapshot_v5
        self.original_resolver_v3 = wrapper.tailfix_v5.last_resolver_v3_snapshot_v5

    def tearDown(self):
        wrapper.tailfix_v3.last_headroom_report_v3 = self.original_latency
        wrapper.tailfix_v5.last_writer_headroom_v5 = self.original_writer
        wrapper.tailfix_v5.last_writer_warning_v5 = self.original_writer_warning
        wrapper.tailfix_v5.last_writer_queue_p95_share_v5 = self.original_writer_share
        wrapper.tailfix_v5.last_resolver_snapshot_v5 = self.original_resolver
        wrapper.tailfix_v5.last_resolver_v3_snapshot_v5 = self.original_resolver_v3

    def _clean_reports(self):
        wrapper.tailfix_v3.last_headroom_report_v3 = SimpleNamespace(warning_stages=())
        wrapper.tailfix_v5.last_writer_headroom_v5 = SimpleNamespace(
            result_wait_p95_seconds=1.0,
            base=SimpleNamespace(pending_at_close=0),
        )
        wrapper.tailfix_v5.last_writer_warning_v5 = False
        wrapper.tailfix_v5.last_writer_queue_p95_share_v5 = 0.20
        wrapper.tailfix_v5.last_resolver_snapshot_v5 = SimpleNamespace(
            normalization_historical_promotions=2,
            normalization_network_resolutions=2,
            delayed_availability_reuses=10,
            coalesced_after_pool_lock_reuses=20,
        )
        wrapper.tailfix_v5.last_resolver_v3_snapshot_v5 = SimpleNamespace(
            mapping_sync_completed=4
        )

    def test_clean_official_pass_is_promotable(self):
        original_runner = wrapper.v54_guard.v54.run_smoke_v54
        original_main = wrapper.v54_guard.main
        observed = {}
        self._clean_reports()

        def fake_main():
            observed["runner"] = wrapper.v54_guard.v54.run_smoke_v54
            return 0

        wrapper.v54_guard.main = fake_main
        try:
            result = wrapper.main()
        finally:
            wrapper.v54_guard.main = original_main

        self.assertEqual(result, 0)
        self.assertIs(observed["runner"], wrapper.tailfix_v5.run_smoke_tailfix_v5)
        self.assertIs(wrapper.v54_guard.v54.run_smoke_v54, original_runner)

    def test_latency_warning_holds_official_pass(self):
        original_main = wrapper.v54_guard.main
        self._clean_reports()
        wrapper.tailfix_v3.last_headroom_report_v3 = SimpleNamespace(
            warning_stages=("global_prefix_normalization_barrier",)
        )
        wrapper.v54_guard.main = lambda: 0
        try:
            result = wrapper.main()
        finally:
            wrapper.v54_guard.main = original_main
        self.assertEqual(result, wrapper.V5_PROMOTION_HOLD_EXIT)

    def test_sustained_writer_warning_holds_official_pass(self):
        original_main = wrapper.v54_guard.main
        self._clean_reports()
        wrapper.tailfix_v5.last_writer_warning_v5 = True
        wrapper.v54_guard.main = lambda: 0
        try:
            result = wrapper.main()
        finally:
            wrapper.v54_guard.main = original_main
        self.assertEqual(result, wrapper.V5_PROMOTION_HOLD_EXIT)

    def test_missing_resolver_evidence_holds_official_pass(self):
        original_main = wrapper.v54_guard.main
        self._clean_reports()
        wrapper.tailfix_v5.last_resolver_snapshot_v5 = None
        wrapper.v54_guard.main = lambda: 0
        try:
            result = wrapper.main()
        finally:
            wrapper.v54_guard.main = original_main
        self.assertEqual(result, wrapper.V5_PROMOTION_HOLD_EXIT)

    def test_official_system_failure_cannot_be_rescued(self):
        original_runner = wrapper.v54_guard.v54.run_smoke_v54
        original_main = wrapper.v54_guard.main
        self._clean_reports()
        wrapper.v54_guard.main = lambda: 6
        try:
            result = wrapper.main()
        finally:
            wrapper.v54_guard.main = original_main

        self.assertEqual(result, 6)
        self.assertIs(wrapper.v54_guard.v54.run_smoke_v54, original_runner)

    def test_runner_is_restored_on_exception(self):
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
