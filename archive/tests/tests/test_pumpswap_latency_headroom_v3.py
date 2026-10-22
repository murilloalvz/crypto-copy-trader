from __future__ import annotations

from types import SimpleNamespace
import unittest

from src.pumpswap_latency_headroom_v3 import (
    EARLY_WARNING_SECONDS,
    OFFICIAL_PIPELINE_P95_SECONDS,
    build_latency_headroom_report_v3,
)


class PumpSwapLatencyHeadroomV3Tests(unittest.TestCase):
    def _row(self, *, normalization=0.2, barrier=0.3, reservation_submit=0.4, submit_ready=0.5):
        return SimpleNamespace(
            self_ingress_to_normalization_seconds=normalization,
            prefix_normalization_barrier_seconds=barrier,
            reservation_to_submit_seconds=reservation_submit,
            submit_to_dependency_ready_seconds=submit_ready,
        )

    def _resolver(self):
        return SimpleNamespace(
            total_resolve_seconds=(0.1, 0.2),
            pool_lock_hold_seconds=(0.1,),
            network_account_wait_seconds=(0.2,),
            durable_mapping_write_seconds=(0.1,),
            canonical_reload_seconds=(0.1,),
        )

    def test_warning_is_early_only_and_does_not_change_official_gate(self):
        self.assertEqual(OFFICIAL_PIPELINE_P95_SECONDS, 5.0)
        self.assertEqual(EARLY_WARNING_SECONDS, 4.0)
        sequence = SimpleNamespace(rows=(self._row(barrier=4.2),) * 20)
        report = build_latency_headroom_report_v3(
            sequence_snapshot=sequence,
            resolver_snapshot=self._resolver(),
        )
        self.assertIn("global_prefix_normalization_barrier", report.warning_stages)
        barrier = next(
            item for item in report.stages
            if item.stage == "global_prefix_normalization_barrier"
        )
        self.assertTrue(barrier.early_warning)
        self.assertAlmostEqual(barrier.share_of_official_gate_pct, 84.0)

    def test_empty_optional_stages_are_safe(self):
        sequence = SimpleNamespace(rows=(self._row(),))
        report = build_latency_headroom_report_v3(
            sequence_snapshot=sequence,
            resolver_snapshot=self._resolver(),
            priority_snapshot=None,
            commit_snapshot=None,
        )
        self.assertFalse(report.warning_stages)
        self.assertGreaterEqual(len(report.stages), 9)


if __name__ == "__main__":
    unittest.main()
