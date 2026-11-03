from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.buy_event_acceleration_replication_v0.run import (
    DEFAULT_CONTRACT,
    DEFAULT_PROTOCOL,
    FEATURE_ID,
    _read_json,
    _validate_protocol,
    run_replication,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class BuyEventAccelerationReplicationV0Tests(unittest.TestCase):
    def test_protocol_hash_and_contract_are_frozen(self):
        protocol = _read_json(DEFAULT_PROTOCOL)
        contract = _read_json(DEFAULT_CONTRACT)
        _validate_protocol(protocol, contract)
        self.assertEqual(
            protocol["protocol_hash_sha256"],
            "374e83b274bf39221c3b283ac531f7066796d22faf5ad58228c8e62bc7f9a20f",
        )
        self.assertEqual(protocol["hypothesis"]["feature_id"], FEATURE_ID)
        self.assertTrue(protocol["comparison"]["no_fixed_feature_threshold"])

    def test_strong_negative_fresh_relation_can_keep(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            contract = _read_json(DEFAULT_CONTRACT)
            contract_hash = contract["contract_hash_sha256"]
            discovery = [root / f"discovery-{index}" for index in range(3)]
            for index, run in enumerate(discovery):
                _write(
                    run / "route-input-v2.json",
                    {
                        "contract_hash_sha256": contract_hash,
                        "identity": f"discovery-{index}",
                    },
                )

            fresh = root / "fresh"
            _write(
                fresh / "route-input-v2.json",
                {
                    "contract_hash_sha256": contract_hash,
                    "feature_snapshot_frozen_before_provider_quotes": True,
                    "identity": "fresh",
                },
            )

            rows = []
            decisions = []
            for index in range(32):
                episode_key = f"episode-{index:02d}"
                feature = -3.2 + index * 0.1
                outcome = 48.0 - index * 2.0
                rows.append(
                    {
                        "episode_key": episode_key,
                        "baseline_admitted": True,
                        "route_status": "ROUTE_CLOSED",
                        "is_default_sol_quote": True,
                        "fixed_return_pct": outcome,
                        "features": {FEATURE_ID: feature},
                    }
                )
                decisions.append(
                    {
                        "episode_key": episode_key,
                        "admitted": True,
                        "status": "ROUTE_CLOSED",
                        "gross_route_return_pct": outcome + 2.4,
                    }
                )

            _write(
                fresh / "route-result-v2.json",
                {
                    "contract_hash_sha256": contract_hash,
                    "decisions": decisions,
                },
            )
            _write(
                fresh / "market-first-feature-discovery-v1.json",
                {
                    "classification": "PASS_MARKET_FIRST_FEATURE_DISCOVERY_V1",
                    "source_integrity": {
                        "route_contract_hash_sha256": contract_hash,
                        "feature_snapshot_frozen_before_provider_quotes": True,
                        "exact_reconstruction_parity": True,
                        "causal_quote_asset_identity_emitted": True,
                    },
                    "temporal_contract": {
                        "provider_quote_used_for_features": False,
                        "future_outcome_used_for_features": False,
                    },
                    "rows": rows,
                },
            )

            report = run_replication(
                discovery_run_dirs=discovery,
                fresh_run_dir=fresh,
                output_path=fresh / "report.json",
            )

        self.assertEqual(report["classification"], "PASS_BUY_EVENT_ACCELERATION_REPLICATION_V0")
        self.assertEqual(report["decision"], "KEEP")
        self.assertLess(report["association"]["spearman_feature_vs_fixed_60s_return"], 0)
        self.assertLess(report["association"]["spearman_without_best_trade"], 0)
        self.assertTrue(report["decision_rule_checks"]["lower_half_mean_return_gt_0"])
        self.assertTrue(report["decision_rule_checks"]["lower_half_mean_without_best_gt_0"])
        self.assertTrue(report["decision_rule_checks"]["lower_half_profit_factor_gt_1"])
        self.assertFalse(report["source_integrity"]["fresh_geometry_artifact_required"])
        self.assertEqual(
            report["source_integrity"]["fresh_population_source"],
            "market-first-feature-discovery-v1.json",
        )

    def test_fresh_capture_matching_any_discovery_capture_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            contract = _read_json(DEFAULT_CONTRACT)
            contract_hash = contract["contract_hash_sha256"]
            shared = {
                "contract_hash_sha256": contract_hash,
                "feature_snapshot_frozen_before_provider_quotes": True,
                "identity": "same",
            }
            discovery = [root / f"discovery-{index}" for index in range(3)]
            for index, run in enumerate(discovery):
                _write(
                    run / "route-input-v2.json",
                    shared if index == 0 else {
                        "contract_hash_sha256": contract_hash,
                        "identity": f"discovery-{index}",
                    },
                )

            fresh = root / "fresh"
            _write(fresh / "route-input-v2.json", shared)
            _write(fresh / "route-result-v2.json", {"contract_hash_sha256": contract_hash, "decisions": []})
            _write(
                fresh / "market-first-feature-discovery-v1.json",
                {
                    "classification": "PASS_MARKET_FIRST_FEATURE_DISCOVERY_V1",
                    "source_integrity": {
                        "route_contract_hash_sha256": contract_hash,
                        "feature_snapshot_frozen_before_provider_quotes": True,
                        "exact_reconstruction_parity": True,
                        "causal_quote_asset_identity_emitted": True,
                    },
                    "temporal_contract": {
                        "provider_quote_used_for_features": False,
                        "future_outcome_used_for_features": False,
                    },
                    "rows": [],
                },
            )

            with self.assertRaisesRegex(ValueError, "fresh capture identity matches a discovery capture"):
                run_replication(discovery_run_dirs=discovery, fresh_run_dir=fresh)


if __name__ == "__main__":
    unittest.main()
