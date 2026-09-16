from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.launch_burst_sniper_v1.compare import run_sniper_comparison_v1


ROUTE_HASH = "3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d"
POLICY = Path("benchmarks/launch_burst_sniper_v1/sniper_policy_v1.frozen.json")


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _snapshot(*, flow: float, top_wallet: float = 40.0) -> dict:
    return {
        "stratum": "pump_launch",
        "complete": True,
        "evidence_window_seconds": 5,
        "features": {
            "signed_flow_over_event_reserve": flow,
            "event_count": 7,
            "directional_flow_efficiency": 0.70,
            "wallet_identity_coverage_pct": 100.0,
            "unique_wallet_count": 4,
            "top_wallet_gross_flow_share_pct": top_wallet,
            "transaction_identity_coverage_pct": 100.0,
            "unique_transaction_count": 7,
        },
    }


class LaunchBurstSniperCompareV1Tests(unittest.TestCase):
    def test_primary_subset_can_avoid_a_baseline_loss(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            contract = root / "contract.json"
            route_input = root / "input.json"
            route_result = root / "result.json"
            smart_result = root / "smart.json"
            output = root / "comparison.json"

            _write(contract, {"contract_hash_sha256": ROUTE_HASH, "position": {"notional_usd": 25.0}})
            _write(
                route_input,
                {
                    "type": "launch_burst_prospective_route_input_v2",
                    "contract_hash_sha256": ROUTE_HASH,
                    "feature_snapshot_frozen_before_provider_quotes": True,
                    "episodes": [
                        {"episode_key": "A", "token_mint": "MintA", "feature_snapshot": _snapshot(flow=0.12)},
                        {"episode_key": "B", "token_mint": "MintB", "feature_snapshot": _snapshot(flow=0.15, top_wallet=85.0)},
                        {"episode_key": "C", "token_mint": "MintC", "feature_snapshot": _snapshot(flow=0.05)},
                    ],
                },
            )
            _write(
                route_result,
                {
                    "contract_hash_sha256": ROUTE_HASH,
                    "decisions": [
                        {
                            "episode_key": "A",
                            "token_mint": "MintA",
                            "decision_as_of": 10,
                            "admitted": True,
                            "status": "ROUTE_CLOSED",
                            "route_paper_pnl_usd": 5.0,
                        },
                        {
                            "episode_key": "B",
                            "token_mint": "MintB",
                            "decision_as_of": 11,
                            "admitted": True,
                            "status": "ROUTE_CLOSED",
                            "route_paper_pnl_usd": -4.0,
                        },
                        {
                            "episode_key": "C",
                            "token_mint": "MintC",
                            "decision_as_of": 12,
                            "admitted": False,
                            "status": "NOT_SELECTED",
                            "route_paper_pnl_usd": None,
                        },
                    ],
                },
            )
            _write(
                smart_result,
                {
                    "route_contract_hash_sha256": ROUTE_HASH,
                    "trades": [
                        {"episode_key": "A", "smart_pnl_usd": 4.0},
                        {"episode_key": "B", "smart_pnl_usd": -2.0},
                    ],
                },
            )

            result = run_sniper_comparison_v1(
                contract_path=contract,
                policy_path=POLICY,
                route_input_path=route_input,
                route_result_path=route_result,
                smart_result_path=smart_result,
                output_path=output,
            )
            self.assertTrue(output.exists())
            self.assertEqual(result["baseline_selected_count"], 2)
            self.assertEqual(result["primary_selected_count"], 1)
            self.assertEqual(result["fixed_60s_primary_benchmark"]["baseline"]["trade_count"], 2)
            self.assertEqual(result["fixed_60s_primary_benchmark"]["primary_sniper"]["trade_count"], 1)
            skip = result["fixed_60s_primary_benchmark"]["counterfactual_skip"]
            self.assertEqual(skip["avoided_negative_trade_count"], 1)
            self.assertEqual(skip["missed_positive_trade_count"], 0)
            self.assertAlmostEqual(skip["counterfactual_value_of_skipping_usd"], 4.0)
            self.assertEqual(result["screening"]["status"], "INSUFFICIENT_PRIMARY_SAMPLE")


if __name__ == "__main__":
    unittest.main()
