from __future__ import annotations

import unittest

from benchmarks.convergence_v0.market_export import market_signal_snapshot_from_route_episode_v0


class ConvergenceMarketExportV0Tests(unittest.TestCase):
    def _episode(self, **snapshot_overrides):
        snapshot = {
            "stratum": "pump_launch",
            "complete": True,
            "observed_t0_wall_ns": 1_000,
            "evidence_window_seconds": 5,
            "decision_as_of": 6,
            "decision_cutoff_wall_ns": 5_000_001_000,
            "features": {
                "signed_flow_over_event_reserve": 0.12,
                "event_count": 7,
            },
        }
        snapshot.update(snapshot_overrides)
        return {
            "episode_key": "episode-1",
            "token_mint": "TOKEN",
            "feature_snapshot": snapshot,
            "quotes": [{"future_provider_data": "must_not_be_copied"}],
            "collection": {"entry_status": "ROUTE_CLOSED"},
        }

    def test_export_uses_only_frozen_feature_snapshot(self):
        exported = market_signal_snapshot_from_route_episode_v0(self._episode())
        self.assertEqual(exported["type"], "market_signal_snapshot_v0")
        self.assertEqual(exported["market_anchor_wall_ns"], 1_000)
        self.assertEqual(exported["decision_cutoff_wall_ns"], 5_000_001_000)
        self.assertEqual(exported["snapshot"]["features"]["event_count"], 7)
        self.assertNotIn("quotes", exported)
        self.assertNotIn("collection", exported)
        self.assertTrue(exported["guardrails"]["provider_route_outcomes_not_read"])

    def test_incomplete_snapshot_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "complete"):
            market_signal_snapshot_from_route_episode_v0(self._episode(complete=False))

    def test_wrong_window_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "5-second"):
            market_signal_snapshot_from_route_episode_v0(self._episode(evidence_window_seconds=10))

    def test_missing_causal_anchor_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "observed_t0_wall_ns"):
            market_signal_snapshot_from_route_episode_v0(self._episode(observed_t0_wall_ns=None))


if __name__ == "__main__":
    unittest.main()
