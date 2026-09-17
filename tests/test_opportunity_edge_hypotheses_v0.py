from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from src.launch_burst_sniper_v1 import EXPECTED_POLICY_HASH, load_sniper_policy_v1
from src.market_first_bonding_curve_geometry_v1 import FEATURE_IDS as GEOMETRY_FEATURE_IDS
from src.market_first_feature_discovery_v1 import FEATURE_IDS
from src.market_first_liquidity_discovery_v0 import FEATURE_IDS as LIQUIDITY_FEATURE_IDS
from src.opportunity_edge_hypotheses_v0 import (
    EDGE_HYPOTHESES_V0,
    edge_hypothesis_rows_v0,
    validate_edge_hypotheses_v0,
)
from src.opportunity_feature_matrix_v0 import TRACK_MARKET_FIRST, feature_spec_v0


SNIPER_POLICY = Path("benchmarks") / "launch_burst_sniper_v1" / "sniper_policy_v1.frozen.json"
REPLICATION_PROTOCOL = (
    Path("benchmarks") / "launch_burst_sniper_v1" / "replication_protocol_v0.frozen.json"
)
EXPECTED_ROUTE_CONTRACT_HASH = "3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d"
EXPECTED_REPLICATION_PROTOCOL_HASH = "97b3d9f1f38771af46de75f750437c45aa5bd4aec544eb97810a076352c3bfee"


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class OpportunityEdgeHypothesesV0Tests(unittest.TestCase):
    def test_hypothesis_matrix_is_market_first_and_valid(self):
        validate_edge_hypotheses_v0()
        rows = edge_hypothesis_rows_v0()
        self.assertEqual(len(rows), len(EDGE_HYPOTHESES_V0))
        self.assertTrue(rows)
        self.assertTrue(all(row["track"] == TRACK_MARKET_FIRST for row in rows))

    def test_existing_selector_ready_hypotheses_only_reuse_frozen_sniper_features(self):
        policy = load_sniper_policy_v1(SNIPER_POLICY)
        frozen_features = {
            str(predicate["feature"])
            for predicate in policy["primary_selector"]["predicates"]
        }
        ready = [item for item in EDGE_HYPOTHESES_V0.values() if item.selector_ready]
        self.assertTrue(ready)
        for item in ready:
            self.assertEqual(item.threshold_contract, "FROZEN_SNIPER_V1_ONLY_NO_RETUNING")
            self.assertTrue(set(item.selector_feature_ids).issubset(frozen_features))
            for feature_id in item.selector_feature_ids:
                spec = feature_spec_v0(feature_id)
                self.assertTrue(spec.selector_eligible)
                self.assertFalse(spec.future_dependent)
                self.assertFalse(spec.execution_only)
                self.assertFalse(spec.diagnostic_only)

    def test_acceleration_is_diagnostic_only_without_threshold_or_selector_promotion(self):
        item = EDGE_HYPOTHESES_V0["H_ACCELERATION_V0"]
        self.assertFalse(item.selector_ready)
        self.assertEqual(item.selector_feature_ids, ())
        self.assertEqual(set(item.diagnostic_feature_ids), set(FEATURE_IDS))
        self.assertEqual(item.threshold_contract, "NO_THRESHOLD_DEFINED_DO_NOT_SWEEP")
        self.assertEqual(item.blocker, "prospective_selector_rule_not_preregistered")
        for feature_id in item.diagnostic_feature_ids:
            spec = feature_spec_v0(feature_id)
            self.assertEqual(spec.track, TRACK_MARKET_FIRST)
            self.assertTrue(spec.diagnostic_only)
            self.assertFalse(spec.selector_eligible)
            self.assertFalse(spec.execution_only)
            self.assertFalse(spec.future_dependent)

    def test_liquidity_hypothesis_uses_market_diagnostics_and_keeps_provider_execution_only(self):
        item = EDGE_HYPOTHESES_V0["H_LIQUIDITY_EXITABILITY_V0"]
        self.assertFalse(item.selector_ready)
        self.assertEqual(item.selector_feature_ids, ())
        diagnostic_ids = set(item.diagnostic_feature_ids)
        self.assertTrue(set(LIQUIDITY_FEATURE_IDS).issubset(diagnostic_ids))
        self.assertTrue(set(GEOMETRY_FEATURE_IDS).issubset(diagnostic_ids))
        self.assertIn("provider_price_impact_pct_points", diagnostic_ids)
        self.assertEqual(item.blocker, "prospective_liquidity_selector_rule_not_preregistered")
        for feature_id in (*LIQUIDITY_FEATURE_IDS, *GEOMETRY_FEATURE_IDS):
            spec = feature_spec_v0(feature_id)
            self.assertEqual(spec.track, TRACK_MARKET_FIRST)
            self.assertTrue(spec.diagnostic_only)
            self.assertFalse(spec.selector_eligible)
            self.assertFalse(spec.execution_only)
            self.assertFalse(spec.future_dependent)
        provider_feature = feature_spec_v0("provider_price_impact_pct_points")
        self.assertTrue(provider_feature.execution_only)
        self.assertFalse(provider_feature.selector_eligible)

    def test_replication_protocol_hash_and_frozen_contract_references_are_exact(self):
        payload = json.loads(REPLICATION_PROTOCOL.read_text(encoding="utf-8"))
        expected_hash = payload.pop("protocol_hash_sha256")
        actual_hash = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
        self.assertEqual(expected_hash, EXPECTED_REPLICATION_PROTOCOL_HASH)
        self.assertEqual(actual_hash, EXPECTED_REPLICATION_PROTOCOL_HASH)
        self.assertEqual(payload["selector"]["policy_hash_sha256"], EXPECTED_POLICY_HASH)
        self.assertFalse(payload["selector"]["threshold_retuning_permitted"])
        self.assertEqual(
            payload["economic_contract"]["route_contract_hash_sha256"],
            EXPECTED_ROUTE_CONTRACT_HASH,
        )
        self.assertEqual(payload["economic_contract"]["primary_benchmark"], "fixed_plus_60s_route_shadow")
        self.assertEqual(payload["economic_contract"]["smart_ladder_role"], "exploratory_only_not_primary")
        self.assertEqual(payload["sample_contract"]["capture_duration_seconds"], 900)
        self.assertEqual(payload["sample_contract"]["minimum_primary_usable_route_results"], 30)
        self.assertFalse(payload["comparison"]["same_sample_threshold_search_permitted"])
        self.assertFalse(payload["comparison"]["automatic_edge_promotion_from_single_replication"])
        self.assertTrue(payload["guardrails"]["official_v4_economic_verdict_unchanged"])
        self.assertTrue(payload["guardrails"]["no_social_event_features"])
        self.assertTrue(payload["guardrails"]["no_convergence_features"])


if __name__ == "__main__":
    unittest.main()
