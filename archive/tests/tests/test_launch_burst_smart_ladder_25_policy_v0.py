from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from benchmarks.launch_burst_control_taker_sim_v0.smart_exit import _canonical_json
from benchmarks.launch_burst_control_taker_sim_v0.smart_ladder_25 import (
    EXPECTED_POLICY_HASH,
    _smart_trade,
    _validate_policy,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "benchmarks" / "launch_burst_control_taker_sim_v0" / "smart_ladder_25_policy_v0.frozen.json"
ROUTE_HASH = "3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d"


class LaunchBurstSmartLadder25PolicyV0Tests(unittest.TestCase):
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

    def test_exact_frozen_policy_hash(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        _validate_policy(policy, route_contract_hash=ROUTE_HASH)
        self.assertEqual(policy["policy_hash_sha256"], EXPECTED_POLICY_HASH)
        self.assertEqual(
            EXPECTED_POLICY_HASH,
            "638d6440868c8b0dcbb91fe317be9a5181a11eee2be38ead65adff3ba9bdb818",
        )

    def test_rehashed_metadata_mutation_cannot_replace_frozen_policy(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        mutated = copy.deepcopy(policy)
        mutated["notes"].append("post-freeze mutation")
        shadow = {k: v for k, v in mutated.items() if k != "policy_hash_sha256"}
        mutated["policy_hash_sha256"] = hashlib.sha256(
            _canonical_json(shadow).encode("utf-8")
        ).hexdigest()
        self.assertNotEqual(mutated["policy_hash_sha256"], EXPECTED_POLICY_HASH)
        with self.assertRaisesRegex(ValueError, "frozen V0 policy hash changed"):
            _validate_policy(mutated, route_contract_hash=ROUTE_HASH)

    def test_scale_outs_and_fixed_60s_runner(self):
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
        self.assertAlmostEqual(sum(x["fraction_of_initial_position"] for x in result["realizations"]), 1.0)

    def test_missing_60s_route_penalizes_remaining_fraction(self):
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        path = {
            "episode_key": "e2",
            "token_mint": "MINT2",
            "path": [{"offset_seconds": 5, "quote": self.quote(1.30, 5)}],
        }
        fixed = {"entry_quote": {"price_usd": 1.0}, "status": "UNROUTABLE_EXIT", "decision_as_of": 0}
        result = _smart_trade(path_episode=path, fixed_decision=fixed, contract=self.contract(), policy=policy)
        self.assertEqual(result["runner_exit"]["reason"], "FIXED_60S_UNROUTABLE")
        self.assertEqual(result["smart_status"], "CLOSED")


if __name__ == "__main__":
    unittest.main()
