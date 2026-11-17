from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.early_buyer_churn_prospective_v1.parity import (
    FAIL as PARITY_FAIL,
    _same_value,
    run_parity,
)
from benchmarks.early_buyer_churn_prospective_v1.protocol import (
    DEFAULT_PROTOCOL,
    EXPECTED_PROTOCOL_HASH,
    canonical_json,
    validate_protocol,
)
from benchmarks.early_buyer_churn_prospective_v1.runtime_enrichment import (
    EXTERNAL_EVIDENCE_KEY,
    OnlinePumpFeatureStateWithChurnV1,
    patched_early_buyer_churn_prospective_v1,
)
from benchmarks.early_buyer_churn_v0.run import FEATURE_ID
from benchmarks.launch_burst_prospective_route_live_v3 import live as live_v3


class EarlyBuyerChurnProspectiveV1Tests(unittest.TestCase):
    def test_protocol_hash_and_confirmation_contract_are_frozen(self):
        protocol = json.loads(DEFAULT_PROTOCOL.read_text(encoding="utf-8"))
        validate_protocol(protocol)
        shadow = {k: v for k, v in protocol.items() if k != "protocol_hash_sha256"}
        actual = hashlib.sha256(canonical_json(shadow).encode("utf-8")).hexdigest()
        self.assertEqual(actual, EXPECTED_PROTOCOL_HASH)
        self.assertEqual(protocol["protocol_hash_sha256"], EXPECTED_PROTOCOL_HASH)
        self.assertEqual(protocol["status"], "PREREGISTERED_PROSPECTIVE_CONFIRMATION")
        self.assertEqual(protocol["fresh_confirmation"]["requested_duration_seconds"], 900)
        self.assertEqual(protocol["fresh_confirmation"]["minimum_primary_route_closed_pairs"], 30)
        self.assertFalse(protocol["feature_contract"]["feature_redefinition_allowed"])
        self.assertFalse(protocol["guardrails"]["selector_change"])

    def test_snapshot_enrichment_matches_frozen_churn_semantics(self):
        state = OnlinePumpFeatureStateWithChurnV1()
        state.anchors[("TOKEN", "pump")] = {
            "token_mint": "TOKEN",
            "venue": "pump",
            "chain_t0": 10,
            "observed_wall_ns": 1_000,
            "event_key": "create",
        }
        state.churn_trades["TOKEN"] = [
            {
                "event_key": "b1",
                "observed_wall_ns": 1_100,
                "chain_time": 10,
                "wallet": "A",
                "side": "buy",
                "token_amount_raw": 100,
            },
            {
                "event_key": "s1",
                "observed_wall_ns": 1_200,
                "chain_time": 11,
                "wallet": "A",
                "side": "sell",
                "token_amount_raw": 40,
            },
            {
                "event_key": "b2",
                "observed_wall_ns": 1_300,
                "chain_time": 11,
                "wallet": "B",
                "side": "buy",
                "token_amount_raw": 100,
            },
        ]
        snapshot = {
            "complete": True,
            "observed_t0_wall_ns": 1_000,
            "decision_cutoff_wall_ns": 6_000,
            "features": {"existing": 1.0},
        }
        enriched = state._enrich("TOKEN", snapshot)
        self.assertAlmostEqual(enriched["features"][FEATURE_ID], 0.2)
        self.assertEqual(enriched["features"]["existing"], 1.0)
        evidence = enriched["external_evidence"][EXTERNAL_EVIDENCE_KEY]
        self.assertEqual(evidence["status"], "CAUSAL_AVAILABLE")
        self.assertEqual(evidence["matched_sellback_raw"], 40)
        self.assertEqual(evidence["total_bought_raw"], 200)
        self.assertTrue(evidence["computed_before_provider_quotes"])
        self.assertFalse(evidence["external_provider_used"])

    def test_right_censored_snapshot_never_backfills_feature(self):
        state = OnlinePumpFeatureStateWithChurnV1()
        snapshot = {
            "complete": False,
            "features": {},
        }
        enriched = state._enrich("TOKEN", snapshot)
        self.assertIsNone(enriched["features"][FEATURE_ID])
        evidence = enriched["external_evidence"][EXTERNAL_EVIDENCE_KEY]
        self.assertEqual(evidence["status"], "RIGHT_CENSORED")

    def test_patch_is_restored(self):
        original = live_v3.OnlinePumpFeatureState
        with patched_early_buyer_churn_prospective_v1():
            self.assertIs(live_v3.OnlinePumpFeatureState, OnlinePumpFeatureStateWithChurnV1)
        self.assertIs(live_v3.OnlinePumpFeatureState, original)

    def test_parity_value_comparison_is_exact_tolerance_and_none_safe(self):
        self.assertTrue(_same_value(None, None))
        self.assertFalse(_same_value(None, 0.0))
        self.assertTrue(_same_value(0.2, 0.2 + 1e-16))
        self.assertFalse(_same_value(0.2, 0.200000000001))

    def test_parity_run_set_is_frozen_before_audit(self):
        protocol = {
            "instrumentation": {
                "parity_runs": ["r0", "r1", "r2", "r3", "r4"]
            },
            "protocol_hash_sha256": EXPECTED_PROTOCOL_HASH,
        }
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / name for name in ["r1", "r0", "r2", "r3", "r4"]]
            with patch(
                "benchmarks.early_buyer_churn_prospective_v1.parity.read_json",
                return_value=protocol,
            ), patch(
                "benchmarks.early_buyer_churn_prospective_v1.parity.validate_protocol"
            ):
                with self.assertRaisesRegex(ValueError, "parity run set/order changed"):
                    run_parity(run_dirs=paths)


if __name__ == "__main__":
    unittest.main()
