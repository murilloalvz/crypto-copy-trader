from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import signal_plane_v68_promotion_v0 as promotion


HEAD = "a" * 40


def _write(path: Path, payload: dict) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _live_report(*, duration: float, drops: int = 0) -> dict:
    return {
        "type": "rust_signal_plane_live_shadow_report",
        "version": promotion.REQUIRED_LIVE_VERSION,
        "classification": promotion.REQUIRED_LIVE_CLASSIFICATION,
        "duration_seconds": duration,
        "errors": [],
        "gates": {
            "transport": True,
            "parity": True,
        },
        "trigger_parity": {
            "decision_points": 10,
            "mismatches": 0,
            "parity_pct": 100.0,
        },
        "transport": {
            "reader_errors": [],
            "pump_ingress_drops": drops,
            "pumpswap_ingress_drops": 0,
            "enqueued_total": 100,
            "consumed_total": 100,
            "queue_depth_at_report": 0,
            "queue_high_water": 10,
            "queue_capacity": 8192,
        },
        "latency": {
            "rust_source_to_signal": {
                "p95_ms": 25.0,
            },
        },
    }


class SignalPlaneV68PromotionV0Tests(unittest.TestCase):
    def test_promotion_requires_v7_live_contract(self):
        self.assertEqual(
            promotion.REQUIRED_LIVE_VERSION,
            "rust_signal_plane_live_shadow_v7_rust_hotpath",
        )
        self.assertEqual(
            promotion.REQUIRED_LIVE_CLASSIFICATION,
            "PASS_RUST_SIGNAL_PLANE_LIVE_SHADOW_V7_RUST_HOTPATH",
        )

    def _files(self, root: Path, *, soak_drops: int = 0):
        return {
            "offline_capacity": _write(
                root / "offline-capacity.json",
                {
                    "type": "rust_signal_batch_offline_capacity_report",
                    "version": "v",
                    "classification": promotion.REQUIRED_OFFLINE_CAPACITY,
                    "checks": {"a": True},
                },
            ),
            "offline_bridge": _write(
                root / "offline-bridge.json",
                {
                    "type": "v68_signal_plane_bridge_report",
                    "version": "v",
                    "classification": promotion.REQUIRED_OFFLINE_BRIDGE,
                    "checks": {"a": True},
                },
            ),
            "live_smoke": _write(
                root / "smoke.json",
                _live_report(
                    duration=promotion.SMOKE_MIN_DURATION_SECONDS,
                ),
            ),
            "live_soak": _write(
                root / "soak.json",
                _live_report(
                    duration=promotion.SOAK_MIN_DURATION_SECONDS,
                    drops=soak_drops,
                ),
            ),
            "route_bridge": _write(
                root / "route-bridge.json",
                {
                    "type": "signal_plane_route_research_bridge_report",
                    "version": "v",
                    "classification": promotion.REQUIRED_ROUTE_BRIDGE,
                    "run_key": "systems-bridge-v0",
                    "checks": {"a": True, "b": True},
                    "downstream": {
                        "research_decisions_frozen": 5,
                    },
                },
            ),
        }

    def test_complete_evidence_builds_pass_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            files = self._files(Path(directory))
            with patch.object(promotion, "_git_head", return_value=HEAD):
                report = promotion.build_promotion_report(
                    offline_capacity_path=files["offline_capacity"],
                    offline_bridge_path=files["offline_bridge"],
                    live_smoke_path=files["live_smoke"],
                    live_soak_path=files["live_soak"],
                    route_bridge_path=files["route_bridge"],
                )

        self.assertEqual(
            report["classification"],
            promotion.PASS_CLASSIFICATION,
        )
        self.assertEqual(report["git_head"], HEAD)
        self.assertTrue(all(report["checks"].values()))
        self.assertEqual(len(report["evidence"]), 5)

    def test_live_soak_drop_blocks_promotion(self):
        with tempfile.TemporaryDirectory() as directory:
            files = self._files(Path(directory), soak_drops=1)
            with patch.object(promotion, "_git_head", return_value=HEAD):
                report = promotion.build_promotion_report(
                    offline_capacity_path=files["offline_capacity"],
                    offline_bridge_path=files["offline_bridge"],
                    live_smoke_path=files["live_smoke"],
                    live_soak_path=files["live_soak"],
                    route_bridge_path=files["route_bridge"],
                )

        self.assertEqual(
            report["classification"],
            promotion.FAIL_CLASSIFICATION,
        )
        self.assertFalse(report["checks"]["soak_zero_pump_drops"])

    def test_v68_fresh_key_cannot_be_used_as_route_bridge_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = self._files(root)
            route = json.loads(
                files["route_bridge"].read_text(encoding="utf-8")
            )
            route["run_key"] = "v68-flow60-fresh-20260922-03"
            _write(files["route_bridge"], route)

            with patch.object(promotion, "_git_head", return_value=HEAD):
                report = promotion.build_promotion_report(
                    offline_capacity_path=files["offline_capacity"],
                    offline_bridge_path=files["offline_bridge"],
                    live_smoke_path=files["live_smoke"],
                    live_soak_path=files["live_soak"],
                    route_bridge_path=files["route_bridge"],
                )

        self.assertFalse(
            report["checks"]["route_bridge_not_v68_fresh_key"]
        )
        self.assertEqual(
            report["classification"],
            promotion.FAIL_CLASSIFICATION,
        )


if __name__ == "__main__":
    unittest.main()
