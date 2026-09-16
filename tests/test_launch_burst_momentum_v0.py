from pathlib import Path
import unittest

from benchmarks.launch_burst_control_taker_sim_v0.run_v4_momentum_v0 import _screening_preflight
from benchmarks.launch_burst_momentum_v0.compare import (
    _horizon_300_rows,
    _validate_market_paths_integrity,
)
from benchmarks.launch_burst_momentum_v0.runtime_enrichment import feature_snapshot_with_momentum_v0
from benchmarks.launch_burst_shadow_v0.run import AdaptedEnvelope
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


def route_contract() -> dict:
    return {
        "position": {"notional_usd": 25.0},
        "costs": {
            "entry_fee_bps": 20,
            "exit_fee_bps": 20,
            "entry_adverse_slippage_bps": 100,
            "exit_adverse_slippage_bps": 100,
        },
        "route_quality": {"max_provider_price_impact_pct_points": 2.0},
        "failure_policy": {"unexitable_return_pct": -100.0},
    }


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

    def test_market_paths_require_exact_baseline_and_token_parity(self):
        integrity = _validate_market_paths_integrity(
            market_paths={"episodes": [{"episode_key": "e1", "token_mint": "M1"}]},
            baseline_keys={"e1"},
            input_by_key={"e1": {"episode_key": "e1", "token_mint": "M1"}},
        )
        self.assertTrue(integrity["market_path_exact_baseline_key_parity"])
        with self.assertRaises(ValueError):
            _validate_market_paths_integrity(
                market_paths={"episodes": []},
                baseline_keys={"e1"},
                input_by_key={"e1": {"episode_key": "e1", "token_mint": "M1"}},
            )
        with self.assertRaises(ValueError):
            _validate_market_paths_integrity(
                market_paths={"episodes": [{"episode_key": "e1", "token_mint": "WRONG"}]},
                baseline_keys={"e1"},
                input_by_key={"e1": {"episode_key": "e1", "token_mint": "M1"}},
            )

    def test_missing_300s_mark_is_integrity_error_not_loss(self):
        route_result = {
            "decisions": [{
                "episode_key": "e1",
                "token_mint": "M1",
                "status": "ROUTE_CLOSED",
                "entry_quote": {"price_usd": 1.0},
            }]
        }
        market_paths = {"episodes": [{"episode_key": "e1", "token_mint": "M1", "path": []}]}
        with self.assertRaises(ValueError):
            _horizon_300_rows(
                route_result=route_result,
                market_paths=market_paths,
                contract=route_contract(),
            )

    def test_explicit_300s_provider_error_uses_frozen_failure_return(self):
        route_result = {
            "decisions": [{
                "episode_key": "e1",
                "token_mint": "M1",
                "status": "ROUTE_CLOSED",
                "entry_quote": {"price_usd": 1.0},
            }]
        }
        market_paths = {
            "episodes": [{
                "episode_key": "e1",
                "token_mint": "M1",
                "path": [{"offset_seconds": 300, "status": "ERROR:no route", "quote": None}],
            }]
        }
        rows = _horizon_300_rows(
            route_result=route_result,
            market_paths=market_paths,
            contract=route_contract(),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["return_300_pct"], -100.0)
        self.assertEqual(rows[0]["pnl_300_usd"], -25.0)
        self.assertEqual(rows[0]["status_300"], "ERROR:no route")


if __name__ == "__main__":
    unittest.main()
