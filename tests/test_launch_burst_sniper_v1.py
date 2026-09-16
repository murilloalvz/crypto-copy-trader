from __future__ import annotations

from pathlib import Path
import unittest

from src.launch_burst_sniper_v1 import (
    evaluate_launch_burst_sniper_v1,
    load_sniper_policy_v1,
)


POLICY = Path("benchmarks/launch_burst_sniper_v1/sniper_policy_v1.frozen.json")


def _snapshot(**overrides):
    features = {
        "signed_flow_over_event_reserve": 0.12,
        "event_count": 7,
        "directional_flow_efficiency": 0.70,
        "wallet_identity_coverage_pct": 100.0,
        "unique_wallet_count": 4,
        "top_wallet_gross_flow_share_pct": 45.0,
        "transaction_identity_coverage_pct": 100.0,
        "unique_transaction_count": 7,
    }
    features.update(overrides)
    return {
        "stratum": "pump_launch",
        "complete": True,
        "evidence_window_seconds": 5,
        "features": features,
    }


class LaunchBurstSniperV1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = load_sniper_policy_v1(POLICY)

    def test_frozen_policy_hash_validates(self):
        self.assertEqual(
            self.policy["policy_hash_sha256"],
            "e4b49a7b9cab1720e2f3c302dfdeebed570fed7f44e8e3da4751c77dcd4b5200",
        )

    def test_primary_selects_distributed_directional_burst(self):
        decision = evaluate_launch_burst_sniper_v1(
            snapshot=_snapshot(), policy=self.policy, selector_name="primary_selector"
        )
        self.assertTrue(decision.selected)
        self.assertEqual(decision.status, "SELECTED")
        self.assertEqual(decision.reasons, ())

    def test_primary_rejects_single_wallet_flow_concentration(self):
        decision = evaluate_launch_burst_sniper_v1(
            snapshot=_snapshot(top_wallet_gross_flow_share_pct=78.0),
            policy=self.policy,
            selector_name="primary_selector",
        )
        self.assertFalse(decision.selected)
        self.assertEqual(decision.status, "REJECTED")
        self.assertIn("FAILED:top_wallet_gross_flow_share_pct", decision.reasons)

    def test_primary_missing_wallet_evidence_is_not_imputed(self):
        snapshot = _snapshot()
        del snapshot["features"]["top_wallet_gross_flow_share_pct"]
        decision = evaluate_launch_burst_sniper_v1(
            snapshot=snapshot, policy=self.policy, selector_name="primary_selector"
        )
        self.assertFalse(decision.selected)
        self.assertEqual(decision.status, "INSUFFICIENT_EVIDENCE")
        self.assertIn("MISSING:top_wallet_gross_flow_share_pct", decision.reasons)

    def test_diagnostic_selector_does_not_require_wallet_features(self):
        snapshot = _snapshot()
        for name in (
            "wallet_identity_coverage_pct",
            "unique_wallet_count",
            "top_wallet_gross_flow_share_pct",
            "transaction_identity_coverage_pct",
            "unique_transaction_count",
        ):
            snapshot["features"].pop(name, None)
        decision = evaluate_launch_burst_sniper_v1(
            snapshot=snapshot, policy=self.policy, selector_name="diagnostic_selector"
        )
        self.assertTrue(decision.selected)
        self.assertEqual(decision.status, "SELECTED")

    def test_primary_preserves_frozen_baseline_floor(self):
        decision = evaluate_launch_burst_sniper_v1(
            snapshot=_snapshot(signed_flow_over_event_reserve=0.0799),
            policy=self.policy,
            selector_name="primary_selector",
        )
        self.assertFalse(decision.selected)
        self.assertIn("FAILED:signed_flow_over_event_reserve", decision.reasons)


if __name__ == "__main__":
    unittest.main()
