from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.human_assisted_exit_v0.run import (
    DEFAULT_POLICY,
    _path_metrics,
    _trigger_exit,
    _validate_policy,
    run_diagnostic,
)


ROUTE_HASH = (
    "3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d"
)


def _obs(*returns: float) -> list[dict]:
    offsets = [5, 10, 20, 30, 45, 60, 90, 120]
    return [
        {
            "offset_seconds": offsets[index],
            "observed_at": 1_000 + offsets[index],
            "net_return_pct": float(value),
        }
        for index, value in enumerate(returns)
    ]


class CausalHumanExitV0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads(
            DEFAULT_POLICY.read_text(encoding="utf-8")
        )

    def test_frozen_policy_hash_and_scientific_guardrails_validate(self):
        _validate_policy(
            self.policy,
            route_contract_hash=ROUTE_HASH,
        )
        self.assertFalse(
            self.policy["censoring"]["forced_time_exit"]
        )
        self.assertFalse(
            self.policy["guardrails"]["same_sample_retuning_allowed"]
        )
        self.assertFalse(
            self.policy["guardrails"][
                "retrospective_result_can_confirm_edge"
            ]
        )

    def test_good_profit_exits_at_first_observed_mark_above_25(self):
        result = _trigger_exit(
            observations=_obs(4, 14, 27, 44),
            policy=self.policy,
        )
        self.assertEqual(result["status"], "CLOSED")
        self.assertEqual(result["reason"], "GOOD_PROFIT")
        self.assertEqual(result["exit_offset_seconds"], 20)
        self.assertEqual(result["simulated_exit_return_pct"], 27.0)

    def test_strong_deceleration_needs_prior_peak_and_observed_giveback(self):
        result = _trigger_exit(
            observations=_obs(4, 13, 16, 5),
            policy=self.policy,
        )
        self.assertEqual(result["status"], "CLOSED")
        self.assertEqual(result["reason"], "STRONG_DECELERATION")
        self.assertEqual(result["exit_offset_seconds"], 30)
        self.assertEqual(
            result["prior_observed_peak_return_pct"],
            16.0,
        )
        self.assertEqual(
            result["giveback_from_prior_peak_pct_points"],
            11.0,
        )

    def test_small_pullback_does_not_fake_deceleration(self):
        result = _trigger_exit(
            observations=_obs(4, 13, 16, 11, 10),
            policy=self.policy,
        )
        self.assertEqual(result["status"], "CENSORED_OPEN")
        self.assertIsNone(result["simulated_exit_return_pct"])

    def test_risk_break_requires_observed_deterioration(self):
        result = _trigger_exit(
            observations=_obs(-8, -23),
            policy=self.policy,
        )
        self.assertEqual(result["status"], "CLOSED")
        self.assertEqual(result["reason"], "RISK_BREAK")
        self.assertEqual(result["simulated_exit_return_pct"], -23.0)

        recovering = _trigger_exit(
            observations=_obs(-30, -19),
            policy=self.policy,
        )
        self.assertEqual(recovering["status"], "CENSORED_OPEN")

    def test_no_trigger_is_censored_not_forced_exit(self):
        result = _trigger_exit(
            observations=_obs(2, 6, 9, 8, 7, 8),
            policy=self.policy,
        )
        self.assertEqual(result["status"], "CENSORED_OPEN")
        self.assertEqual(
            result["reason"],
            "NO_CAUSAL_EXIT_TRIGGER_ON_OBSERVED_PATH",
        )
        self.assertIsNone(result["exit_offset_seconds"])
        self.assertIsNone(result["simulated_exit_return_pct"])
        self.assertEqual(result["last_observed_return_pct"], 8.0)

    def test_path_metrics_keep_mfe_separate_from_exit(self):
        metrics = _path_metrics(_obs(-5, 12, 31, 7, -9))
        self.assertEqual(metrics["observed_mfe_pct"], 31.0)
        self.assertEqual(metrics["time_to_observed_mfe_seconds"], 20)
        self.assertEqual(metrics["observed_mae_pct"], -9.0)
        self.assertEqual(metrics["time_to_observed_mae_seconds"], 45)

    def test_end_to_end_diagnostic_preserves_fixed_benchmark(self):
        contract = {
            "contract_hash_sha256": ROUTE_HASH,
            "position": {"notional_usd": 25.0},
            "route_quality": {
                "max_provider_price_impact_pct_points": 2.0
            },
            "costs": {
                "entry_fee_bps": 20,
                "exit_fee_bps": 20,
                "entry_adverse_slippage_bps": 100,
                "exit_adverse_slippage_bps": 100,
            },
        }
        entry = {
            "price_usd": 1.0,
            "observed_at": 1000,
        }
        route_result = {
            "contract_hash_sha256": ROUTE_HASH,
            "decisions": [
                {
                    "episode_key": "episode-1",
                    "token_mint": "TOKEN",
                    "decision_as_of": 990,
                    "admitted": True,
                    "status": "ROUTE_CLOSED",
                    "route_paper_pnl_usd": -2.5,
                    "entry_quote": entry,
                }
            ],
        }
        market_paths = {
            "route_contract_hash_sha256": ROUTE_HASH,
            "episodes": [
                {
                    "episode_key": "episode-1",
                    "token_mint": "TOKEN",
                    "path": [
                        {
                            "offset_seconds": 5,
                            "quote": {
                                "executable": False,
                                "observed_at": 1005,
                                "price_usd": 1.15,
                                "provider_price_impact_pct_points": 0.1,
                            },
                        },
                        {
                            "offset_seconds": 10,
                            "quote": {
                                "executable": False,
                                "observed_at": 1010,
                                "price_usd": 1.35,
                                "provider_price_impact_pct_points": 0.1,
                            },
                        },
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract_path = root / "contract.json"
            route_path = root / "route.json"
            paths_path = root / "paths.json"
            output = root / "out.json"
            contract_path.write_text(
                json.dumps(contract),
                encoding="utf-8",
            )
            route_path.write_text(
                json.dumps(route_result),
                encoding="utf-8",
            )
            paths_path.write_text(
                json.dumps(market_paths),
                encoding="utf-8",
            )

            report = run_diagnostic(
                contract_path=contract_path,
                policy_path=DEFAULT_POLICY,
                route_result_path=route_path,
                market_paths_path=paths_path,
                output_path=output,
            )

        self.assertEqual(report["paired_path_trade_count"], 1)
        self.assertEqual(report["causal_exit_triggered_count"], 1)
        self.assertEqual(
            report["fixed_60_all_path_entries"]["mean_return_pct"],
            -10.0,
        )
        self.assertEqual(
            report["trades"][0]["human_exit"]["reason"],
            "GOOD_PROFIT",
        )
        self.assertTrue(report["guardrails"]["retrospective_only"])
        self.assertFalse(report["guardrails"]["confirms_human_assisted_edge"])


if __name__ == "__main__":
    unittest.main()
