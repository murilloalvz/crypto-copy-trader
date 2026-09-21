from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.early_buyer_churn_robustness_v0.run import (
    PASS,
    _run_level,
    run_audit,
)
from benchmarks.early_buyer_churn_v0.run import FEATURE_ID


class EarlyBuyerChurnRobustnessV0Tests(unittest.TestCase):
    def test_run_level_reports_primary_incremental_and_structural_zero_split(self):
        rows = [
            {
                FEATURE_ID: 0.0,
                "current_route_closed_gross_return_pct": 10.0,
                "current_route_closed_net_return_pct": 8.0,
                "current_route_usable_fixed_return_pct": 10.0,
                "mf_early_buyer_prior_route_closed_gross_median_of_wallet_medians_pct": 1.0,
                "mf_buy_event_rate_acceleration_per_s2": 1.0,
                "signed_flow_over_event_reserve": 1.0,
            },
            {
                FEATURE_ID: 0.2,
                "current_route_closed_gross_return_pct": -10.0,
                "current_route_closed_net_return_pct": -12.0,
                "current_route_usable_fixed_return_pct": -10.0,
                "mf_early_buyer_prior_route_closed_gross_median_of_wallet_medians_pct": 2.0,
                "mf_buy_event_rate_acceleration_per_s2": 2.0,
                "signed_flow_over_event_reserve": 2.0,
            },
            {
                FEATURE_ID: 0.3,
                "current_route_closed_gross_return_pct": -20.0,
                "current_route_closed_net_return_pct": -22.0,
                "current_route_usable_fixed_return_pct": -20.0,
                "mf_early_buyer_prior_route_closed_gross_median_of_wallet_medians_pct": 3.0,
                "mf_buy_event_rate_acceleration_per_s2": 3.0,
                "signed_flow_over_event_reserve": 3.0,
            },
            {
                FEATURE_ID: 0.4,
                "current_route_closed_gross_return_pct": -30.0,
                "current_route_closed_net_return_pct": -32.0,
                "current_route_usable_fixed_return_pct": -30.0,
                "mf_early_buyer_prior_route_closed_gross_median_of_wallet_medians_pct": 4.0,
                "mf_buy_event_rate_acceleration_per_s2": 4.0,
                "signed_flow_over_event_reserve": 4.0,
            },
            {
                FEATURE_ID: 0.5,
                "current_route_closed_gross_return_pct": -40.0,
                "current_route_closed_net_return_pct": -42.0,
                "current_route_usable_fixed_return_pct": -40.0,
                "mf_early_buyer_prior_route_closed_gross_median_of_wallet_medians_pct": 5.0,
                "mf_buy_event_rate_acceleration_per_s2": 5.0,
                "signed_flow_over_event_reserve": 5.0,
            },
        ]
        report = _run_level(rows)
        self.assertLess(report["primary"]["spearman"], 0)
        self.assertEqual(report["zero_churn"]["n"], 1)
        self.assertEqual(report["positive_churn"]["n"], 4)

    def test_audit_reuses_exact_run_set_and_never_promotes(self):
        protocol = {
            "discovery_runs": ["r0", "r1", "r2", "r3"],
            "temporal_holdout_run": "r4",
        }
        fake_rows = []
        for i, run_id in enumerate(["r0", "r1", "r2", "r3", "r4"]):
            for j in range(6):
                fake_rows.append(
                    {
                        "run_id": run_id,
                        "episode_key": f"{run_id}:{j}",
                        FEATURE_ID: 0.1 * j,
                        "feature_status": "CAUSAL_AVAILABLE",
                        "unique_buy_wallet_count": 5,
                        "flipper_wallet_count": 1,
                        "flipper_wallet_share": 0.2,
                        "current_route_closed_gross_return_pct": float(10 - j),
                        "current_route_closed_net_return_pct": float(8 - j),
                        "current_route_usable_fixed_return_pct": float(10 - j),
                        "mf_early_buyer_prior_route_closed_gross_median_of_wallet_medians_pct": float(j),
                        "mf_buy_event_rate_acceleration_per_s2": float(j + 1),
                        "signed_flow_over_event_reserve": float(j + 2),
                    }
                )
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / run_id for run_id in ["r0", "r1", "r2", "r3", "r4"]]
            output = Path(tmp) / "report.json"
            with patch(
                "benchmarks.early_buyer_churn_robustness_v0.run._read_json",
                side_effect=[protocol, {"contract_hash_sha256": "hash"}],
            ), patch(
                "benchmarks.early_buyer_churn_robustness_v0.run._validate_protocol"
            ), patch(
                "benchmarks.early_buyer_churn_robustness_v0.run._prepare_rows",
                return_value=(fake_rows, [{"run_id": p.name} for p in paths]),
            ):
                report = run_audit(run_dirs=paths, output_path=output)

        self.assertEqual(report["classification"], PASS)
        self.assertTrue(report["guardrails"]["post_discovery_audit_only"])
        self.assertFalse(report["guardrails"]["promotion_from_this_audit_allowed"])
        self.assertTrue(report["source_integrity"]["exact_feature_reused"])
        self.assertEqual(set(report["per_run"]), {"r0", "r1", "r2", "r3", "r4"})
        self.assertEqual(set(report["leave_one_run_out"]), {"r0", "r1", "r2", "r3", "r4"})

    def test_wrong_run_order_fails_before_feature_reconstruction(self):
        protocol = {
            "discovery_runs": ["r0", "r1", "r2", "r3"],
            "temporal_holdout_run": "r4",
        }
        with patch(
            "benchmarks.early_buyer_churn_robustness_v0.run._read_json",
            side_effect=[protocol],
        ), patch(
            "benchmarks.early_buyer_churn_robustness_v0.run._validate_protocol"
        ):
            with self.assertRaisesRegex(ValueError, "run set/order changed"):
                run_audit(run_dirs=[Path("r1"), Path("r0"), Path("r2"), Path("r3"), Path("r4")])


if __name__ == "__main__":
    unittest.main()
