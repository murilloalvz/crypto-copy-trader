from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.early_balance_concentration_v0.run import (
    EXPECTED_PROTOCOL_HASH,
    FEATURE_ID,
    _canonical_json,
    _derive_feature,
    _validate_protocol,
    run_discovery,
)


class EarlyBalanceConcentrationV0Tests(unittest.TestCase):
    def test_protocol_hash_and_direction_are_frozen(self):
        path = Path("benchmarks/early_balance_concentration_v0/protocol.frozen.json")
        protocol = json.loads(path.read_text(encoding="utf-8"))
        _validate_protocol(protocol)
        shadow = {k: v for k, v in protocol.items() if k != "protocol_hash_sha256"}
        actual = hashlib.sha256(_canonical_json(shadow).encode("utf-8")).hexdigest()
        self.assertEqual(actual, EXPECTED_PROTOCOL_HASH)
        self.assertEqual(protocol["protocol_hash_sha256"], EXPECTED_PROTOCOL_HASH)
        self.assertEqual(protocol["feature_contract"]["expected_direction"], "negative")
        self.assertFalse(protocol["directional_read"]["promotion_from_this_sample_allowed"])
        self.assertTrue(protocol["guardrails"]["retrospective_discovery_only"])

    def test_hhi_uses_positive_observed_net_balances(self):
        trades = {
            "TOKEN": [
                {
                    "event_key": "e1",
                    "observed_wall_ns": 1_100,
                    "chain_time": 10,
                    "wallet": "A",
                    "side": "buy",
                    "token_amount_raw": 100,
                },
                {
                    "event_key": "e2",
                    "observed_wall_ns": 1_200,
                    "chain_time": 11,
                    "wallet": "A",
                    "side": "sell",
                    "token_amount_raw": 40,
                },
                {
                    "event_key": "e3",
                    "observed_wall_ns": 1_300,
                    "chain_time": 11,
                    "wallet": "B",
                    "side": "buy",
                    "token_amount_raw": 40,
                },
                {
                    "event_key": "e4",
                    "observed_wall_ns": 7_000,
                    "chain_time": 20,
                    "wallet": "C",
                    "side": "buy",
                    "token_amount_raw": 999,
                },
            ]
        }
        result = _derive_feature(
            token_mint="TOKEN",
            anchor_wall_ns=1_000,
            cutoff_wall_ns=6_000,
            chain_t0=10,
            trades=trades,
        )
        self.assertEqual(result["status"], "CAUSAL_AVAILABLE")
        self.assertAlmostEqual(result[FEATURE_ID], 0.6**2 + 0.4**2)
        self.assertEqual(result["positive_wallet_count"], 2)
        self.assertEqual(result["observed_positive_balance_total_raw"], 100)
        self.assertAlmostEqual(result["largest_positive_wallet_share"], 0.6)
        self.assertEqual(result["event_count"], 3)

    def test_single_positive_wallet_is_valid_max_concentration(self):
        trades = {
            "TOKEN": [
                {
                    "event_key": "e1",
                    "observed_wall_ns": 1_100,
                    "chain_time": 10,
                    "wallet": "A",
                    "side": "buy",
                    "token_amount_raw": 100,
                },
                {
                    "event_key": "e2",
                    "observed_wall_ns": 1_200,
                    "chain_time": 10,
                    "wallet": "B",
                    "side": "sell",
                    "token_amount_raw": 10,
                },
            ]
        }
        result = _derive_feature(
            token_mint="TOKEN",
            anchor_wall_ns=1_000,
            cutoff_wall_ns=6_000,
            chain_t0=10,
            trades=trades,
        )
        self.assertEqual(result["status"], "CAUSAL_AVAILABLE")
        self.assertEqual(result[FEATURE_ID], 1.0)
        self.assertEqual(result["positive_wallet_count"], 1)

    def test_no_positive_balance_is_missing(self):
        trades = {
            "TOKEN": [
                {
                    "event_key": "e1",
                    "observed_wall_ns": 1_100,
                    "chain_time": 10,
                    "wallet": "A",
                    "side": "sell",
                    "token_amount_raw": 100,
                }
            ]
        }
        result = _derive_feature(
            token_mint="TOKEN",
            anchor_wall_ns=1_000,
            cutoff_wall_ns=6_000,
            chain_t0=10,
            trades=trades,
        )
        self.assertEqual(result["status"], "MISSING_NO_POSITIVE_OBSERVED_NET_BALANCE")
        self.assertIsNone(result[FEATURE_ID])

    def test_feature_is_scale_invariant(self):
        base = {
            "TOKEN": [
                {"event_key": "e1", "observed_wall_ns": 1100, "chain_time": 10, "wallet": "A", "side": "buy", "token_amount_raw": 3},
                {"event_key": "e2", "observed_wall_ns": 1200, "chain_time": 10, "wallet": "B", "side": "buy", "token_amount_raw": 1},
            ]
        }
        scaled = {
            "TOKEN": [
                {"event_key": "e1", "observed_wall_ns": 1100, "chain_time": 10, "wallet": "A", "side": "buy", "token_amount_raw": 3000},
                {"event_key": "e2", "observed_wall_ns": 1200, "chain_time": 10, "wallet": "B", "side": "buy", "token_amount_raw": 1000},
            ]
        }
        kwargs = dict(token_mint="TOKEN", anchor_wall_ns=1000, cutoff_wall_ns=6000, chain_t0=10)
        left = _derive_feature(trades=base, **kwargs)
        right = _derive_feature(trades=scaled, **kwargs)
        self.assertAlmostEqual(left[FEATURE_ID], right[FEATURE_ID])

    def test_run_set_is_frozen_before_data_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "wrong-run"
            with self.assertRaisesRegex(ValueError, "discovery run set/order changed"):
                run_discovery(run_dirs=[fake])


if __name__ == "__main__":
    unittest.main()
