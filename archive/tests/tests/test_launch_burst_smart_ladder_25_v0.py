import json
from pathlib import Path
import unittest

from benchmarks.launch_burst_control_taker_sim_v0.smart_ladder_25 import (
    _smart_trade,
    _validate_policy,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks" / "launch_burst_control_taker_sim_v0" / "smart_ladder_25_policy_v0.frozen.json"
ROUTE_HASH = "3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d"


class LaunchBurstSmartLadder25V0Tests(unittest.TestCase):
    def contract(self):
        return {
            "contract_hash_sha256": ROUTE_HASH,
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

    def quote(self, price, observed_at):
        return {
            "price_usd": price,
            "observed_at": observed_at,
            "executable": False,
            "provider_price_impact_pct_points": 0.1,
        }

    def test_frozen_policy_hash_and_shape(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        _validate_policy(policy, route_contract_hash=ROUTE_HASH)
        self.assertEqual(policy["sample_offsets_seconds_from_entry"], [5, 10, 20, 30, 45, 60])
        self.assertEqual(policy["runner"]["mode"], "fixed_horizon_close")
        self.assertEqual(policy["runner"]["horizon_seconds_from_entry"], 60)
        self.assertNotIn("trailing_drawdown_fraction_from_best_net_multiplier", policy["runner"])

    def test_scale_out_and_final_25_percent_at_60s(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        path = {
            "episode_key": "e1",
            "token_mint": "MINT",
            "path": [
                {"offset_seconds": 5, "quote": self.quote(1.30, 5)},
                {"offset_seconds": 20, "quote": self.quote(1.60, 20)},
                {"offset_seconds": 45, "quote": self.quote(2.10, 45)},
                {"offset_seconds": 60, "quote": self.quote(2.30, 60)},
            ],
        }
        fixed = {"entry_quote": {"price_usd": 1.0}, "status": "ROUTE_CLOSED", "decision_as_of": 0}
        result = _smart_trade(path_episode=path, fixed_decision=fixed, contract=self.contract(), policy=policy)
        self.assertEqual([x["threshold_return_pct"] for x in result["threshold_hits"]], [20.0, 50.0, 100.0])
        self.assertEqual(result["runner_exit"]["reason"], "FIXED_60S_CLOSE")
        self.assertEqual(result["runner_exit"]["offset_seconds"], 60)
        self.assertAlmostEqual(sum(x["fraction_of_initial_position"] for x in result["realizations"]), 1.0)

    def test_gap_crossing_fills_all_crossed_tranches_at_first_sample(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        path = {
            "episode_key": "e2",
            "token_mint": "MINT2",
            "path": [
                {"offset_seconds": 10, "quote": self.quote(2.20, 10)},
                {"offset_seconds": 60, "quote": self.quote(1.50, 60)},
            ],
        }
        fixed = {"entry_quote": {"price_usd": 1.0}, "status": "ROUTE_CLOSED", "decision_as_of": 0}
        result = _smart_trade(path_episode=path, fixed_decision=fixed, contract=self.contract(), policy=policy)
        self.assertEqual([x["offset_seconds"] for x in result["threshold_hits"]], [10, 10, 10])
        self.assertEqual(result["runner_exit"]["reason"], "FIXED_60S_CLOSE")

    def test_missing_60s_route_penalizes_remaining_fraction(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        path = {
            "episode_key": "e3",
            "token_mint": "MINT3",
            "path": [{"offset_seconds": 5, "quote": self.quote(1.30, 5)}],
        }
        fixed = {"entry_quote": {"price_usd": 1.0}, "status": "UNROUTABLE_EXIT", "decision_as_of": 0}
        result = _smart_trade(path_episode=path, fixed_decision=fixed, contract=self.contract(), policy=policy)
        self.assertEqual(result["runner_exit"]["reason"], "FIXED_60S_UNROUTABLE")
        self.assertEqual(result["smart_status"], "CLOSED")


if __name__ == "__main__":
    unittest.main()
