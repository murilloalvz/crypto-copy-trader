from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.early_buyer_churn_v0.run import (
    DEFAULT_PROTOCOL,
    EXPECTED_PROTOCOL_HASH,
    FEATURE_ID,
    _canonical_json,
    _decision,
    _derive_feature,
    _validate_protocol,
    run_discovery,
)


class EarlyBuyerChurnV0Tests(unittest.TestCase):
    def test_protocol_hash_split_and_direction_are_frozen(self):
        protocol = json.loads(DEFAULT_PROTOCOL.read_text(encoding="utf-8"))
        _validate_protocol(protocol)
        shadow = {k: v for k, v in protocol.items() if k != "protocol_hash_sha256"}
        actual = hashlib.sha256(_canonical_json(shadow).encode("utf-8")).hexdigest()
        self.assertEqual(actual, EXPECTED_PROTOCOL_HASH)
        self.assertEqual(protocol["protocol_hash_sha256"], EXPECTED_PROTOCOL_HASH)
        self.assertEqual(len(protocol["discovery_runs"]), 4)
        self.assertEqual(
            protocol["temporal_holdout_run"],
            "launch_burst_prospective_route_live_v4-1789946453-0367216d26",
        )
        self.assertEqual(protocol["feature_contract"]["expected_direction"], "negative")
        self.assertFalse(protocol["decision_rule"]["promotion_from_this_sample_allowed"])

    def test_sellback_matches_only_observed_acquired_inventory(self):
        trades = {
            "TOKEN": [
                {"event_key":"e1","observed_wall_ns":1100,"chain_time":10,"wallet":"A","side":"sell","token_amount_raw":50},
                {"event_key":"e2","observed_wall_ns":1200,"chain_time":10,"wallet":"A","side":"buy","token_amount_raw":100},
                {"event_key":"e3","observed_wall_ns":1300,"chain_time":11,"wallet":"A","side":"sell","token_amount_raw":30},
                {"event_key":"e4","observed_wall_ns":1400,"chain_time":11,"wallet":"B","side":"buy","token_amount_raw":100},
                {"event_key":"e5","observed_wall_ns":1500,"chain_time":12,"wallet":"B","side":"sell","token_amount_raw":150},
            ]
        }
        result = _derive_feature(
            token_mint="TOKEN",
            anchor_wall_ns=1000,
            cutoff_wall_ns=6000,
            chain_t0=10,
            trades=trades,
        )
        self.assertEqual(result["status"], "CAUSAL_AVAILABLE")
        self.assertEqual(result["total_bought_raw"], 200)
        self.assertEqual(result["matched_sellback_raw"], 130)
        self.assertEqual(result["unmatched_sell_raw"], 100)
        self.assertAlmostEqual(result[FEATURE_ID], 0.65)
        self.assertEqual(result["flipper_wallet_count"], 2)

    def test_no_buy_is_missing(self):
        trades = {
            "TOKEN": [
                {"event_key":"e1","observed_wall_ns":1100,"chain_time":10,"wallet":"A","side":"sell","token_amount_raw":50}
            ]
        }
        result = _derive_feature(
            token_mint="TOKEN",
            anchor_wall_ns=1000,
            cutoff_wall_ns=6000,
            chain_t0=10,
            trades=trades,
        )
        self.assertEqual(result["status"], "MISSING_NO_OBSERVED_BUY")
        self.assertIsNone(result[FEATURE_ID])

    def test_feature_is_scale_invariant(self):
        base = {
            "TOKEN": [
                {"event_key":"e1","observed_wall_ns":1100,"chain_time":10,"wallet":"A","side":"buy","token_amount_raw":10},
                {"event_key":"e2","observed_wall_ns":1200,"chain_time":11,"wallet":"A","side":"sell","token_amount_raw":4},
            ]
        }
        scaled = {
            "TOKEN": [
                {"event_key":"e1","observed_wall_ns":1100,"chain_time":10,"wallet":"A","side":"buy","token_amount_raw":10000},
                {"event_key":"e2","observed_wall_ns":1200,"chain_time":11,"wallet":"A","side":"sell","token_amount_raw":4000},
            ]
        }
        kwargs = dict(token_mint="TOKEN", anchor_wall_ns=1000, cutoff_wall_ns=6000, chain_t0=10)
        self.assertAlmostEqual(
            _derive_feature(trades=base, **kwargs)[FEATURE_ID],
            _derive_feature(trades=scaled, **kwargs)[FEATURE_ID],
        )

    def test_decision_requires_discovery_and_holdout_incremental_direction(self):
        protocol = json.loads(DEFAULT_PROTOCOL.read_text(encoding="utf-8"))
        discovery = {
            "primary_signal_quality": {
                "usable_pair_count": 100,
                "spearman": -0.2,
                "spearman_without_best_trade": -0.18,
                "leave_one_out_sign_consistency_fraction": 1.0,
            },
            "incremental_vs_existing_evidence": {"partial_spearman": -0.1},
        }
        holdout = {
            "primary_signal_quality": {
                "usable_pair_count": 25,
                "spearman": -0.15,
            },
            "incremental_vs_existing_evidence": {"partial_spearman": -0.05},
        }
        decision, checks = _decision(discovery=discovery, holdout=holdout, protocol=protocol)
        self.assertEqual(decision, "RETROSPECTIVE_TEMPORAL_REPLICATION_NO_PROMOTION")
        self.assertTrue(all(checks.values()))

        holdout["incremental_vs_existing_evidence"]["partial_spearman"] = 0.01
        decision, checks = _decision(discovery=discovery, holdout=holdout, protocol=protocol)
        self.assertEqual(decision, "NO_REPLICATION_CLOSE_FAMILY")
        self.assertFalse(checks["holdout_incremental_negative"])

    def test_wrong_holdout_identity_fails_before_source_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_discovery = [Path(tmp) / name for name in [
                "launch_burst_prospective_route_live_v4-1789605670-3592832863",
                "launch_burst_prospective_route_live_v4-1789687945-0315e2560c",
                "launch_burst_prospective_route_live_v4-1789692405-6daeedeb29",
                "launch_burst_prospective_route_live_v4-1789698815-b277ffea77",
            ]]
            wrong = Path(tmp) / "wrong-holdout"
            with self.assertRaisesRegex(ValueError, "temporal holdout run changed"):
                run_discovery(
                    discovery_run_dirs=fake_discovery,
                    holdout_run_dir=wrong,
                )


if __name__ == "__main__":
    unittest.main()
