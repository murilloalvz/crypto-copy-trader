from __future__ import annotations

import copy
import unittest

from benchmarks.convergence_v0.join import join_market_social_evidence_v0


class ConvergenceEvidenceJoinV0Tests(unittest.TestCase):
    def _market(self):
        return {
            "type": "market_signal_snapshot_v0",
            "token_mint": "TOKEN",
            "market_anchor_wall_ns": 1_000,
            "decision_cutoff_wall_ns": 1_500,
            "snapshot": {
                "feature_snapshot": {
                    "signed_flow_over_event_reserve": 0.12,
                    "event_count": 8,
                }
            },
        }

    def _social(self):
        return {
            "type": "social_event_snapshot",
            "version": "social_event_snapshot_v0",
            "classification": "PASS_SOCIAL_EVENT_SNAPSHOT_V0",
            "token_mint": "TOKEN",
            "market_anchor_wall_ns": 1_000,
            "decision_cutoff_wall_ns": 1_500,
            "causal_time_field": "causal_available_wall_ns",
            "features": {"observed_event_count": 3},
            "evidence_keys": ["sev0:abc"],
            "guardrails": {"no_market_outcome_used": True},
        }

    def test_matching_independent_snapshots_join_without_selector(self):
        joined = join_market_social_evidence_v0(
            market_snapshot=self._market(), social_snapshot=self._social()
        )
        self.assertEqual(joined["classification"], "PASS_CONVERGENCE_EVIDENCE_JOIN_V0")
        self.assertEqual(joined["status"], "EVIDENCE_JOIN_ONLY_NO_SELECTOR")
        self.assertTrue(joined["guardrails"]["outcome_blind"])
        self.assertTrue(joined["guardrails"]["no_selector"])
        self.assertTrue(joined["guardrails"]["no_ranking"])
        self.assertTrue(joined["guardrails"]["no_trade_recommendation"])

    def test_token_mismatch_is_rejected(self):
        social = self._social()
        social["token_mint"] = "OTHER"
        with self.assertRaisesRegex(ValueError, "token_mint mismatch"):
            join_market_social_evidence_v0(market_snapshot=self._market(), social_snapshot=social)

    def test_cutoff_mismatch_is_rejected(self):
        social = self._social()
        social["decision_cutoff_wall_ns"] = 1_501
        with self.assertRaisesRegex(ValueError, "decision_cutoff_wall_ns mismatch"):
            join_market_social_evidence_v0(market_snapshot=self._market(), social_snapshot=social)

    def test_anchor_mismatch_is_rejected(self):
        social = self._social()
        social["market_anchor_wall_ns"] = 999
        with self.assertRaisesRegex(ValueError, "market_anchor_wall_ns mismatch"):
            join_market_social_evidence_v0(market_snapshot=self._market(), social_snapshot=social)

    def test_embedded_market_outcome_is_rejected(self):
        market = self._market()
        market["snapshot"]["route_paper_pnl_usd"] = 99.0
        with self.assertRaisesRegex(ValueError, "outcome-bearing key"):
            join_market_social_evidence_v0(market_snapshot=market, social_snapshot=self._social())

    def test_embedded_social_label_is_rejected(self):
        social = self._social()
        social["features"]["label"] = "winner"
        with self.assertRaisesRegex(ValueError, "outcome-bearing key"):
            join_market_social_evidence_v0(market_snapshot=self._market(), social_snapshot=social)


if __name__ == "__main__":
    unittest.main()
