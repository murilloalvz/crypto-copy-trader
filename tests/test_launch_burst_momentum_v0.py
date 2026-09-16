from pathlib import Path
import unittest

from benchmarks.launch_burst_momentum_v0.runtime_enrichment import feature_snapshot_with_momentum_v0
from benchmarks.launch_burst_shadow_v0.run import AdaptedEnvelope
from benchmarks.launch_burst_control_taker_sim_v0.run_v4_momentum_v0 import _screening_preflight
from src.launch_burst_momentum_v0 import (
    EXPECTED_POLICY_HASH,
    evaluate_momentum_v0,
    load_momentum_policy_v0,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks" / "launch_burst_momentum_v0" / "momentum_policy_v0.frozen.json"


def env(*, wall_ns: int, amount: int, reserve: int = 1000, side: str = "buy", key: str = "e") -> AdaptedEnvelope:
    return AdaptedEnvelope(
        token_mint="MINT",
        venue="pump",
        side=side,
        chain_time=1,
        observed_wall_ns=wall_ns,
        event_key=key,
        market_surface_key="surface",
        quote_asset_key="SOL",
        quote_amount_raw=amount,
        quote_reserve_raw=reserve,
        reserve_kind="virtual",
        wallet_key="wallet-" + key,
        transaction_key="tx-" + key,
    )


class LaunchBurstMomentumV0Tests(unittest.TestCase):
    def test_frozen_policy_hash_and_primary_shape(self):
        policy = load_momentum_policy_v0(POLICY)
        self.assertEqual(policy["policy_hash_sha256"], EXPECTED_POLICY_HASH)
        self.assertEqual(
            policy["primary_selector"]["predicates"],
            [
                {"feature": "signed_flow_over_event_reserve", "op": ">=", "value": 0.08},
                {"feature": "gross_flow_acceleration_second_half_over_first_half", "op": ">=", "value": 2.0},
            ],
        )

    def test_causal_half_window_acceleration(self):
        anchor = 10_000_000_000
        rows = [
            env(wall_ns=anchor + 100_000_000, amount=10, key="a"),
            env(wall_ns=anchor + 1_000_000_000, amount=10, key="b"),
            env(wall_ns=anchor + 3_000_000_000, amount=30, key="c"),
            env(wall_ns=anchor + 4_000_000_000, amount=30, key="d"),
        ]
        features = feature_snapshot_with_momentum_v0(rows, anchor_wall_ns=anchor)
        self.assertAlmostEqual(features["gross_flow_acceleration_second_half_over_first_half"], 3.0)
        self.assertAlmostEqual(features["event_rate_acceleration_second_half_over_first_half"], 1.0)
        self.assertAlmostEqual(features["buy_flow_acceleration_second_half_over_first_half"], 3.0)
        self.assertEqual(features["momentum_first_half_event_count"], 2)
        self.assertEqual(features["momentum_second_half_event_count"], 2)

    def test_selector_accepts_baseline_plus_2x_acceleration(self):
        policy = load_momentum_policy_v0(POLICY)
        snapshot = {
            "complete": True,
            "stratum": "pump_launch",
            "evidence_window_seconds": 5,
            "features": {
                "signed_flow_over_event_reserve": 0.10,
                "gross_flow_acceleration_second_half_over_first_half": 2.0,
            },
        }
        decision = evaluate_momentum_v0(snapshot=snapshot, policy=policy)
        self.assertTrue(decision.selected)
        self.assertEqual(decision.status, "SELECTED")

    def test_selector_rejects_nonaccelerating_burst(self):
        policy = load_momentum_policy_v0(POLICY)
        snapshot = {
            "complete": True,
            "stratum": "pump_launch",
            "evidence_window_seconds": 5,
            "features": {
                "signed_flow_over_event_reserve": 0.10,
                "gross_flow_acceleration_second_half_over_first_half": 1.99,
            },
        }
        decision = evaluate_momentum_v0(snapshot=snapshot, policy=policy)
        self.assertFalse(decision.selected)
        self.assertIn("FAILED:gross_flow_acceleration_second_half_over_first_half", decision.reasons)

    def test_missing_acceleration_fails_closed(self):
        policy = load_momentum_policy_v0(POLICY)
        snapshot = {
            "complete": True,
            "stratum": "pump_launch",
            "evidence_window_seconds": 5,
            "features": {"signed_flow_over_event_reserve": 0.10},
        }
        decision = evaluate_momentum_v0(snapshot=snapshot, policy=policy)
        self.assertFalse(decision.selected)
        self.assertEqual(decision.status, "INSUFFICIENT_EVIDENCE")

    def test_screening_duration_is_frozen_at_900s(self):
        report = _screening_preflight(POLICY, 900)
        self.assertEqual(report["screening_run_duration_seconds"], 900)
        with self.assertRaises(ValueError):
            _screening_preflight(POLICY, 600)


if __name__ == "__main__":
    unittest.main()
