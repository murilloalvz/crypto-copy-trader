from __future__ import annotations

import unittest
from unittest.mock import patch

import signal_plane_edge_offline_readiness_v0 as readiness


class SignalPlaneEdgeOfflineReadinessV0Tests(unittest.TestCase):
    def test_pass_requires_both_offline_systems_proofs_and_frozen_contracts(self):
        v5 = {
            "classification": readiness.V5_BATCH_PASS,
            "checks": {"a": True},
            "scientific_thresholds_modified": False,
            "economic_hypothesis_modified": False,
            "throughput": {"effective_records_per_second": 9000.0},
            "trigger_parity": {"parity_pct": 100.0},
        }
        bridge = {
            "classification": readiness.EPISODE_BRIDGE_PASS,
            "checks": {"a": True},
            "scientific_thresholds_modified": False,
            "economic_hypothesis_modified": False,
            "rust_python_parity": {"parity_pct": 100.0},
            "episode_bridge": {"failures": 0},
        }
        with patch.object(
            readiness,
            "run_v5_batch_capacity",
            return_value=v5,
        ), patch.object(
            readiness,
            "run_bridge_audit",
            return_value=bridge,
        ):
            report = readiness.run_offline_edge_readiness()

        self.assertEqual(
            report["classification"],
            readiness.PASS_CLASSIFICATION,
        )
        self.assertTrue(all(report["checks"].values()))

    def test_v5_capacity_failure_blocks_offline_readiness(self):
        v5 = {
            "classification": "FAIL",
            "checks": {"a": False},
            "scientific_thresholds_modified": False,
            "economic_hypothesis_modified": False,
        }
        bridge = {
            "classification": readiness.EPISODE_BRIDGE_PASS,
            "checks": {"a": True},
            "scientific_thresholds_modified": False,
            "economic_hypothesis_modified": False,
        }
        with patch.object(
            readiness,
            "run_v5_batch_capacity",
            return_value=v5,
        ), patch.object(
            readiness,
            "run_bridge_audit",
            return_value=bridge,
        ):
            report = readiness.run_offline_edge_readiness()

        self.assertEqual(
            report["classification"],
            readiness.FAIL_CLASSIFICATION,
        )
        self.assertFalse(
            report["checks"]["v5_batch_offline_capacity_pass"]
        )


if __name__ == "__main__":
    unittest.main()
