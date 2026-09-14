import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.launch_burst_feature_redundancy_v0.run import (
    PASS_CLASSIFICATION,
    _spearman,
    run_audit,
)


class LaunchBurstFeatureRedundancyV0Tests(unittest.TestCase):
    def test_spearman_detects_monotonic_relation(self):
        result = _spearman([(1, 10), (2, 20), (3, 30), (4, 40)])
        self.assertEqual(result["n"], 4)
        self.assertAlmostEqual(result["rho"], 1.0)

    def test_outcome_blind_audit_preserves_strata(self):
        def horizon(event_count, signed, gross, wallets, t5):
            return {
                "complete": True,
                "features": {
                    "event_count": event_count,
                    "buy_count": event_count,
                    "sell_count": 0,
                    "buy_sell_count_imbalance": 1.0,
                    "signed_flow_over_event_reserve": signed,
                    "gross_turnover_over_event_reserve": gross,
                    "unique_wallet_count": wallets,
                    "unique_transaction_count": event_count,
                    "wallet_identity_coverage_pct": 100.0 if wallets else 0.0,
                    "transaction_identity_coverage_pct": 100.0,
                    "first_trade_delay_ms": 10.0,
                    "time_to_n_events_ms": {"3": 20.0, "5": t5, "10": None},
                    "reserve_delta_fraction": 0.01,
                },
            }

        launches = []
        for index in range(4):
            launches.append(
                {
                    "token_mint": f"pump-{index}",
                    "venue": "pump",
                    "stratum": "pump_launch",
                    "horizons": {
                        "1": horizon(1 + index, 0.01 + index * 0.01, 0.02 + index * 0.02, 0, None),
                        "5": horizon(5 + index, 0.05 + index * 0.01, 0.10 + index * 0.02, 0, 100.0 + index),
                        "10": horizon(8 + index, 0.07 + index * 0.01, 0.14 + index * 0.02, 0, 100.0 + index),
                        "30": horizon(10 + index, 0.08 + index * 0.01, 0.20 + index * 0.02, 0, 100.0 + index),
                    },
                }
            )
        for index in range(3):
            launches.append(
                {
                    "token_mint": f"ps-{index}",
                    "venue": "pumpswap",
                    "stratum": "pumpswap_liquidity_launch",
                    "horizons": {
                        "1": horizon(3 + index, 0.03, 0.06, 2 + index, 50.0),
                        "5": horizon(8 + index, 0.08, 0.16, 5 + index, 70.0),
                        "10": horizon(12 + index, 0.10, 0.22, 7 + index, 70.0),
                        "30": horizon(20 + index, 0.12, 0.30, 9 + index, 70.0),
                    },
                }
            )

        source = {
            "classification": "PASS_LAUNCH_BURST_LIVE_FEATURE_ANALYSIS_V0",
            "capture_id": "capture-x",
            "research_contract": {
                "outcome_blind": True,
                "future_outcomes_loaded": False,
            },
            "launches": launches,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "analysis.json"
            output_path = root / "audit.json"
            source_path.write_text(json.dumps(source), encoding="utf-8")
            result = run_audit(analysis_report=source_path, output=output_path)

        self.assertEqual(result["classification"], PASS_CLASSIFICATION)
        self.assertEqual(result["strata"]["pump_launch"]["anchor_count"], 4)
        self.assertEqual(result["strata"]["pumpswap_liquidity_launch"]["anchor_count"], 3)
        self.assertTrue(result["outcome_blind"])
        self.assertFalse(result["future_outcomes_loaded"])


if __name__ == "__main__":
    unittest.main()
