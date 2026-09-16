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
        "wallet_gross_flow_coverage_pct": 100.0,
        "unique_buy_wallet_count": 4,
        "top_wallet_gross_flow_share_worst_case_pct": 45.0,
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
            "60a480a90365eae8abfcb55787345b41573fc1d2632d17c344741e93e36f490a",
        )

    def test_primary_selects_distributed_directional_burst(self):
        decision = evaluate_launch_burst_sniper_v1(
            snapshot=_snapshot(), policy=self.policy, selector_name="primary_selector"
        )
        self.assertTrue(decision.selected)
        self.assertEqual(decision.status, "SELECTED")
        self.assertEqual(decision.reasons, ())

    def test_primary_rejects_worst_case_wallet_flow_concentration(self):
        decision = evaluate_launch_burst_sniper_v1(
            snapshot=_snapshot(top_wallet_gross_flow_share_worst_case_pct=78.0),
            policy=self.policy,
            selector_name="primary_selector",
        )
        self.assertFalse(decision.selected)
        self.assertEqual(decision.status, "REJECTED")
        self.assertIn("FAILED:top_wallet_gross_flow_share_worst_case_pct", decision.reasons)

    def test_primary_rejects_low_wallet_flow_coverage(self):
        decision = evaluate_launch_burst_sniper_v1(
            snapshot=_snapshot(wallet_gross_flow_coverage_pct=60.0),
            policy=self.policy,
            selector_name="primary_selector",
        )
        self.assertFalse(decision.selected)
        self.assertEqual(decision.status, "REJECTED")
        self.assertIn("FAILED:wallet_gross_flow_coverage_pct", decision.reasons)

    def test_primary_requires_three_unique_buyers_not_merely_participants(self):
        decision = evaluate_launch_burst_sniper_v1(
            snapshot=_snapshot(unique_buy_wallet_count=2),
            policy=self.policy,
            selector_name="primary_selector",
        )
        self.assertFalse(decision.selected)
        self.assertEqual(decision.status, "REJECTED")
        self.assertIn("FAILED:unique_buy_wallet_count", decision.reasons)

    def test_primary_missing_wallet_evidence_is_not_imputed(self):
        snapshot = _snapshot()
        del snapshot["features"]["top_wallet_gross_flow_share_worst_case_pct"]
        decision = evaluate_launch_burst_sniper_v1(
            snapshot=snapshot, policy=self.policy, selector_name="primary_selector"
        )
        self.assertFalse(decision.selected)
        self.assertEqual(decision.status, "INSUFFICIENT_EVIDENCE")
        self.assertIn("MISSING:top_wallet_gross_flow_share_worst_case_pct", decision.reasons)

    def test_diagnostic_selector_does_not_require_wallet_features(self):
        snapshot = _snapshot()
        for name in (
            "wallet_identity_coverage_pct",
            "wallet_gross_flow_coverage_pct",
            "unique_buy_wallet_count",
            "top_wallet_gross_flow_share_worst_case_pct",
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
