from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.market_first_routeable_edge_discovery_v2.run import (
    ACCELERATION_FEATURE_IDS,
    GEOMETRY_FEATURE_IDS,
    SNIPER_FEATURE_IDS,
    _feature_association,
    run_discovery_v2,
)
from src.market_first_bonding_curve_geometry_v1 import SOL_QUOTE_MINT


class MarketFirstRouteableEdgeDiscoveryV2Tests(unittest.TestCase):
    def test_feature_association_reports_robustness_without_threshold_search(self):
        rows = [
            {"episode_key": "a", "fixed_return_pct": -10.0, "features": {"x": 1.0}},
            {"episode_key": "b", "fixed_return_pct": 0.0, "features": {"x": 2.0}},
            {"episode_key": "c", "fixed_return_pct": 10.0, "features": {"x": 3.0}},
            {"episode_key": "d", "fixed_return_pct": 20.0, "features": {"x": 4.0}},
        ]
        result = _feature_association(rows, "x")
        self.assertEqual(result["usable_pair_count"], 4)
        self.assertAlmostEqual(result["spearman_with_fixed_60s_return"], 1.0)
        self.assertAlmostEqual(result["spearman_without_best_return_trade"], 1.0)
        self.assertAlmostEqual(result["spearman_without_worst_return_trade"], 1.0)
        self.assertEqual(result["leave_one_out_sign_consistency_fraction"], 1.0)
        self.assertFalse(result["threshold_search_performed"])

    def test_integration_excludes_nonrouteable_entries_and_joins_causal_features(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            contract_hash = "contract-hash"
            contract_path = root / "contract.json"
            contract_path.write_text(
                json.dumps({"contract_hash_sha256": contract_hash, "position": {"notional_usd": 25.0}}),
                encoding="utf-8",
            )

            def snapshot_features(seed: float) -> dict[str, float]:
                return {feature_id: seed + index for index, feature_id in enumerate(SNIPER_FEATURE_IDS)}

            episodes = []
            for index, key in enumerate(("e1", "e2", "e3"), start=1):
                episodes.append(
                    {
                        "episode_key": key,
                        "token_mint": f"mint-{key}",
                        "feature_snapshot": {"complete": True, "features": snapshot_features(float(index))},
                    }
                )
            (root / "route-input-v2.json").write_text(
                json.dumps(
                    {
                        "contract_hash_sha256": contract_hash,
                        "feature_snapshot_frozen_before_provider_quotes": True,
                        "episodes": episodes,
                    }
                ),
                encoding="utf-8",
            )
            (root / "route-result-v2.json").write_text(
                json.dumps(
                    {
                        "contract_hash_sha256": contract_hash,
                        "decisions": [
                            {
                                "episode_key": "e1",
                                "token_mint": "mint-e1",
                                "decision_as_of": 1,
                                "admitted": True,
                                "status": "ROUTE_CLOSED",
                                "route_paper_pnl_usd": 5.0,
                            },
                            {
                                "episode_key": "e2",
                                "token_mint": "mint-e2",
                                "decision_as_of": 2,
                                "admitted": True,
                                "status": "UNROUTABLE_EXIT",
                                "route_paper_pnl_usd": -25.0,
                            },
                            {
                                "episode_key": "e3",
                                "token_mint": "mint-e3",
                                "decision_as_of": 3,
                                "admitted": True,
                                "status": "ENTRY_UNAVAILABLE",
                                "route_paper_pnl_usd": -25.0,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (root / "sniper-comparison-v1.json").write_text(
                json.dumps(
                    {
                        "primary_selector_diagnostics": {
                            "rows": [
                                {"episode_key": "e1", "selected": True},
                                {"episode_key": "e2", "selected": False},
                                {"episode_key": "e3", "selected": True},
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            dynamics_rows = []
            geometry_rows = []
            for index, key in enumerate(("e1", "e2", "e3"), start=1):
                dynamics_rows.append(
                    {
                        "episode_key": key,
                        "features": {
                            feature_id: float(index + offset)
                            for offset, feature_id in enumerate(ACCELERATION_FEATURE_IDS)
                        },
                    }
                )
                geometry_rows.append(
                    {
                        "episode_key": key,
                        "quote_mint": SOL_QUOTE_MINT,
                        "features": {
                            feature_id: float(index + offset)
                            for offset, feature_id in enumerate(GEOMETRY_FEATURE_IDS)
                        },
                    }
                )

            (root / "market-first-feature-discovery-v1.json").write_text(
                json.dumps(
                    {
                        "classification": "PASS_MARKET_FIRST_FEATURE_DISCOVERY_V1",
                        "source_integrity": {
                            "route_contract_hash_sha256": contract_hash,
                            "exact_reconstruction_parity": True,
                        },
                        "rows": dynamics_rows,
                    }
                ),
                encoding="utf-8",
            )
            (root / "market-first-bonding-curve-geometry-v1.json").write_text(
                json.dumps(
                    {
                        "classification": "PASS_MARKET_FIRST_BONDING_CURVE_GEOMETRY_V1",
                        "source_integrity": {
                            "route_contract_hash_sha256": contract_hash,
                            "stored_event_count_parity": True,
                            "geometry_payload_decode_failures": 0,
                        },
                        "rows": geometry_rows,
                    }
                ),
                encoding="utf-8",
            )

            report = run_discovery_v2(run_dir=root, contract_path=contract_path)

        self.assertEqual(report["classification"], "PASS_MARKET_FIRST_ROUTEABLE_EDGE_DISCOVERY_V2")
        self.assertTrue(report["source_integrity"]["exact_routeable_join"])
        self.assertEqual(report["cohorts"]["baseline_route_usable"]["outcomes"]["trade_count"], 2)
        self.assertEqual(report["cohorts"]["sniper_route_usable"]["outcomes"]["trade_count"], 1)
        self.assertEqual({row["episode_key"] for row in report["rows"]}, {"e1", "e2"})
        self.assertFalse(report["threshold_search_performed"])
        self.assertTrue(report["guardrails"]["entry_unavailable_excluded"])


if __name__ == "__main__":
    unittest.main()
