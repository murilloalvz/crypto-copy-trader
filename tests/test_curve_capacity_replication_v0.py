from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.curve_capacity_replication_v0.run import (
    DEFAULT_CONTRACT,
    DEFAULT_PROTOCOL,
    FEATURE_ID,
    _read_json,
    _validate_protocol,
    run_replication,
)
from src.market_first_bonding_curve_geometry_v1 import SOL_QUOTE_MINT


EXPECTED_PROTOCOL_HASH = "3697a9acc73753151f49d3d64354c11c355a8eed31cfefbc784209c1957599c1"


class CurveCapacityReplicationV0Tests(unittest.TestCase):
    def test_protocol_hash_and_contract_are_frozen(self):
        protocol = _read_json(DEFAULT_PROTOCOL)
        contract = _read_json(DEFAULT_CONTRACT)
        self.assertEqual(protocol["protocol_hash_sha256"], EXPECTED_PROTOCOL_HASH)
        self.assertEqual(protocol["hypothesis"]["feature_id"], FEATURE_ID)
        self.assertFalse(protocol["comparison"]["same_sample_threshold_search_permitted"])
        self.assertTrue(protocol["causal_contract"]["fresh_independent_causal_capture_required"])
        _validate_protocol(protocol, contract)

    def test_fresh_capture_with_strong_negative_monotonic_relation_can_keep(self):
        contract = _read_json(DEFAULT_CONTRACT)
        route_hash = contract["contract_hash_sha256"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            discovery = root / "discovery"
            fresh = root / "fresh"
            discovery.mkdir()
            fresh.mkdir()

            (discovery / "route-input-v2.json").write_text(
                json.dumps({"contract_hash_sha256": route_hash, "identity": "old"}),
                encoding="utf-8",
            )

            (fresh / "route-input-v2.json").write_text(
                json.dumps({
                    "contract_hash_sha256": route_hash,
                    "feature_snapshot_frozen_before_provider_quotes": True,
                    "identity": "fresh",
                }),
                encoding="utf-8",
            )

            decisions = []
            geometry_rows = []
            for index in range(30):
                key = f"episode-{index:02d}"
                ret = float(30 - index)
                decisions.append({
                    "episode_key": key,
                    "token_mint": f"token-{index:02d}",
                    "decision_as_of": 1000 + index,
                    "admitted": True,
                    "status": "ROUTE_CLOSED",
                    "route_paper_pnl_usd": 25.0 * ret / 100.0,
                    "gross_route_return_pct": ret + 2.4,
                })
                geometry_rows.append({
                    "episode_key": key,
                    "quote_mint": SOL_QUOTE_MINT,
                    "features": {FEATURE_ID: float(index + 1)},
                })

            (fresh / "route-result-v2.json").write_text(
                json.dumps({"contract_hash_sha256": route_hash, "decisions": decisions}),
                encoding="utf-8",
            )
            (fresh / "market-first-bonding-curve-geometry-v1.json").write_text(
                json.dumps({
                    "classification": "PASS_MARKET_FIRST_BONDING_CURVE_GEOMETRY_V1",
                    "source_integrity": {
                        "route_contract_hash_sha256": route_hash,
                        "stored_event_count_parity": True,
                        "geometry_payload_decode_failures": 0,
                    },
                    "rows": geometry_rows,
                }),
                encoding="utf-8",
            )

            report = run_replication(discovery_run_dir=discovery, fresh_run_dir=fresh)

        self.assertEqual(report["classification"], "PASS_CURVE_CAPACITY_REPLICATION_V0")
        self.assertEqual(report["decision"], "KEEP")
        self.assertLess(report["association"]["spearman_feature_vs_fixed_60s_return"], 0)
        self.assertLess(report["association"]["spearman_without_best_trade"], 0)
        self.assertEqual(report["population"]["fresh_feature_route_usable_n"], 30)
        self.assertTrue(report["source_integrity"]["fresh_capture_identity_differs"])
        self.assertFalse(report["guardrails"]["fixed_feature_threshold_used"])

    def test_same_capture_identity_is_rejected(self):
        contract = _read_json(DEFAULT_CONTRACT)
        route_hash = contract["contract_hash_sha256"]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            discovery = root / "discovery"
            fresh = root / "fresh"
            discovery.mkdir()
            fresh.mkdir()
            payload = json.dumps({
                "contract_hash_sha256": route_hash,
                "feature_snapshot_frozen_before_provider_quotes": True,
            })
            (discovery / "route-input-v2.json").write_text(payload, encoding="utf-8")
            (fresh / "route-input-v2.json").write_text(payload, encoding="utf-8")
            (fresh / "route-result-v2.json").write_text(
                json.dumps({"contract_hash_sha256": route_hash, "decisions": []}), encoding="utf-8"
            )
            (fresh / "market-first-bonding-curve-geometry-v1.json").write_text(
                json.dumps({
                    "classification": "PASS_MARKET_FIRST_BONDING_CURVE_GEOMETRY_V1",
                    "source_integrity": {
                        "route_contract_hash_sha256": route_hash,
                        "stored_event_count_parity": True,
                        "geometry_payload_decode_failures": 0,
                    },
                    "rows": [],
                }),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "fresh capture identity matches discovery capture"):
                run_replication(discovery_run_dir=discovery, fresh_run_dir=fresh)


if __name__ == "__main__":
    unittest.main()
