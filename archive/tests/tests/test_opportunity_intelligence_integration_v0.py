from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.convergence_v0.join import join_market_social_evidence_v0
from benchmarks.launch_burst_opportunity_lab_v0.discover import discover_compatible_runs
from src.causal_evidence_guardrails_v0 import validate_market_feature_snapshot_v0
from src.social_event_evidence_v0 import social_event_evidence_from_mapping_v0


class OpportunityIntelligenceIntegrationV0Tests(unittest.TestCase):
    def _market_snapshot(self):
        return {
            "type": "market_signal_snapshot_v0",
            "token_mint": "TOKEN",
            "market_anchor_wall_ns": 1_000,
            "decision_cutoff_wall_ns": 6_000,
            "snapshot": {"signed_flow_over_event_reserve": 0.1},
        }

    def _social_snapshot(self):
        return {
            "type": "social_event_snapshot",
            "version": "social_event_snapshot_v0",
            "token_mint": "TOKEN",
            "market_anchor_wall_ns": 1_000,
            "decision_cutoff_wall_ns": 6_000,
            "causal_time_field": "causal_available_wall_ns",
            "features": {"observed_event_count": 3},
            "evidence_keys": ["sev0:a"],
        }

    def test_market_feature_guard_rejects_nested_provider_route_fields(self):
        snapshot = {
            "complete": True,
            "stratum": "pump_launch",
            "evidence_window_seconds": 5,
            "features": {"flow": {"provider_price_impact_pct_points": -2.0}},
        }
        with self.assertRaisesRegex(ValueError, "forbidden"):
            validate_market_feature_snapshot_v0(snapshot)

    def test_market_feature_guard_accepts_causal_market_state(self):
        snapshot = {
            "complete": True,
            "stratum": "pump_launch",
            "evidence_window_seconds": 5,
            "features": {
                "signed_flow_over_event_reserve": 0.08,
                "event_count": 12,
                "buyers": {"unique_count": 7},
            },
        }
        validate_market_feature_snapshot_v0(snapshot)

    def test_social_published_clock_is_metadata_not_causal_availability(self):
        row = {
            "source_kind": "social_post",
            "source_key": "source:alice",
            "source_event_id": "post-1",
            "event_kind": "mention",
            "observed_wall_ns": 1_000,
            "published_at_ns": 9_999,
            "token_mint": "TOKEN",
            "token_mapping_observed_wall_ns": 1_200,
        }
        item = social_event_evidence_from_mapping_v0(row)
        self.assertEqual(item.published_at_ns, 9_999)
        self.assertEqual(item.observed_wall_ns, 1_000)
        self.assertEqual(item.token_mapping_observed_wall_ns, 1_200)
        self.assertEqual(item.causal_available_wall_ns, 1_200)

    def test_social_supplied_causal_clock_must_match_derived_clock(self):
        row = {
            "source_kind": "social_post",
            "source_key": "source:alice",
            "source_event_id": "post-1",
            "event_kind": "mention",
            "observed_wall_ns": 1_000,
            "published_at_ns": 900,
            "token_mint": "TOKEN",
            "token_mapping_observed_wall_ns": 1_200,
            "causal_available_wall_ns": 1_100,
        }
        with self.assertRaisesRegex(ValueError, "causal_available_wall_ns"):
            social_event_evidence_from_mapping_v0(row)

    def test_convergence_rejects_nested_execution_fields(self):
        market = self._market_snapshot()
        market["snapshot"] = {"nested": {"route": {"fill_status": "landed"}}}
        with self.assertRaisesRegex(ValueError, "forbidden"):
            join_market_social_evidence_v0(
                market_snapshot=market,
                social_snapshot=self._social_snapshot(),
            )

    def test_convergence_rejects_social_cutoff_before_anchor(self):
        social = self._social_snapshot()
        social["decision_cutoff_wall_ns"] = 999
        with self.assertRaisesRegex(ValueError, "cutoff"):
            join_market_social_evidence_v0(
                market_snapshot=self._market_snapshot(),
                social_snapshot=social,
            )

    def test_discovery_counts_identical_route_input_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = {
                "contract_hash_sha256": "same",
                "episodes": [{"episode_key": "one"}],
            }
            for name in ("capture-a", "capture-a-replay"):
                run_dir = root / name
                run_dir.mkdir()
                (run_dir / "route-input-v2.json").write_text(
                    json.dumps(payload, sort_keys=True), encoding="utf-8"
                )
            with patch(
                "benchmarks.launch_burst_opportunity_lab_v0.discover.analyze_run",
                return_value={"classification": "PASS_TEST"},
            ):
                report = discover_compatible_runs(artifacts_root=root)
            self.assertEqual(report["compatible_artifact_count_before_capture_dedupe"], 2)
            self.assertEqual(report["independent_causal_capture_count"], 1)
            self.assertEqual(len(report["duplicate_causal_captures"]), 1)


if __name__ == "__main__":
    unittest.main()
