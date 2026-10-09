from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from benchmarks.holder_ownership_native_v1.market_ingest import (
    PUBLIC_SOLANA_WSS_URL,
    patched_public_solana_standard_wss_v1,
)
from benchmarks.holder_ownership_native_v1.preflight import run_preflight
from benchmarks.holder_ownership_native_v1.run import (
    DEFAULT_PROTOCOL,
    _association,
    _recompute_native_hhi,
    _validate_fresh_capture,
    _validate_protocol,
)
from benchmarks.holder_ownership_native_v1.runtime_enrichment import (
    FEATURE_ID,
    HolderOwnershipNativeRuntimeV1,
    _collect_native_holder_evidence_sync,
    patched_holder_ownership_native_v1,
)
from benchmarks.helius_standard_wss_shadow_v0 import collect as helius_collect
from benchmarks.launch_burst_prospective_route_live_v3 import live as live_v3
from benchmarks.launch_burst_prospective_route_paper_v2 import live as paper_v2
from benchmarks.market_first_live_discovery_v0 import rotating_trace


class HolderOwnershipNativeV1Tests(unittest.TestCase):
    def test_protocol_hash_and_guardrails_are_frozen(self):
        protocol = json.loads(DEFAULT_PROTOCOL.read_text(encoding="utf-8"))
        expected = protocol.pop("protocol_hash_sha256")
        actual = hashlib.sha256(
            json.dumps(
                protocol,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(
            expected,
            "90132a6656738dceb4662b4701091f5290c2f7c85c9c3896c7326c0fec75a565",
        )
        self.assertEqual(expected, actual)
        protocol["protocol_hash_sha256"] = expected
        _validate_protocol(protocol)
        self.assertEqual(protocol["feature_contract"]["expected_direction"], "negative")
        self.assertFalse(protocol["feature_contract"]["threshold_search_allowed"])
        self.assertFalse(protocol["guardrails"]["gmgn_holder_dependency"])

    def test_native_hhi_aggregates_owner_accounts_and_excludes_curve(self):
        now = time.time_ns()
        calls = []

        def fake_rpc_once(*, api_key, method, params, timeout_seconds):
            self.assertEqual(api_key, "helius")
            self.assertGreater(timeout_seconds, 0)
            calls.append((method, params))
            common = {
                "method": method,
                "request_before_wall_ns": now + 10_000_000,
                "response_after_wall_ns": now + 50_000_000,
                "duration_ms": 40.0,
                "status_code": 200,
                "error": None,
                "rate_limited": False,
                "private_key_used": False,
                "capital_used": False,
                "retry_count": 0,
            }
            if method == "getTokenSupply":
                return {**common, "result": {"value": {"amount": "1000", "decimals": 6}}}
            return {
                **common,
                "result": {
                    "token_accounts": [
                        {"owner": "CURVE", "amount": "700"},
                        {"owner": "A", "amount": "100"},
                        {"owner": "A", "amount": "50"},
                        {"owner": "B", "amount": "50"},
                    ]
                },
            }

        with patch(
            "benchmarks.holder_ownership_native_v1.runtime_enrichment._rpc_once",
            side_effect=fake_rpc_once,
        ):
            record = _collect_native_holder_evidence_sync(
                token_mint="TOKEN",
                bonding_curve="CURVE",
                observed_t0_wall_ns=now - 3_100_000_000,
                decision_cutoff_wall_ns=now + 2_000_000_000,
                api_key="helius",
            )

        self.assertEqual(record["status"], "CAUSAL_AVAILABLE")
        self.assertAlmostEqual(record["feature_value"], 0.15**2 + 0.05**2)
        self.assertEqual(record["token_account_count"], 4)
        self.assertEqual(record["unique_owner_count"], 3)
        self.assertEqual(record["non_curve_owner_count"], 2)
        self.assertEqual(record["bonding_curve_amount_raw"], 700)
        self.assertEqual(record["denominator"], "total_supply_raw")
        self.assertEqual(record["excluded_market_owner"], "CURVE")
        self.assertEqual([name for name, _ in calls], ["getTokenSupply", "getTokenAccounts"])
        self.assertAlmostEqual(_recompute_native_hhi(record), record["feature_value"])

    def test_native_rate_limit_fails_closed(self):
        now = time.time_ns()
        with patch(
            "benchmarks.holder_ownership_native_v1.runtime_enrichment._rpc_once",
            return_value={
                "method": "getTokenSupply",
                "request_before_wall_ns": now,
                "response_after_wall_ns": now + 10_000_000,
                "duration_ms": 10.0,
                "status_code": 429,
                "error": "HTTP_429",
                "rate_limited": True,
                "result": None,
                "private_key_used": False,
                "capital_used": False,
                "retry_count": 0,
            },
        ):
            record = _collect_native_holder_evidence_sync(
                token_mint="TOKEN",
                bonding_curve="CURVE",
                observed_t0_wall_ns=now - 3_100_000_000,
                decision_cutoff_wall_ns=now + 2_000_000_000,
                api_key="helius",
            )
        self.assertEqual(record["status"], "HELIUS_RATE_LIMITED")
        self.assertIsNone(record["feature_value"])

    def test_mark_graduation_invalidates_existing_snapshot_if_pool_preceded_request(self):
        runtime = HolderOwnershipNativeRuntimeV1(helius_api_key="helius")
        runtime.records["TOKEN"] = {
            "status": "CAUSAL_AVAILABLE",
            "feature_id": FEATURE_ID,
            "feature_value": 0.01,
            "snapshot_request_before_wall_ns": 5_000,
            "private_key_used": False,
            "capital_used": False,
            "selector_changed": False,
        }
        runtime.mark_graduation(token_mint="TOKEN", observed_wall_ns=4_000)
        self.assertEqual(runtime.records["TOKEN"]["status"], "GRADUATED_BEFORE_SNAPSHOT")
        self.assertIsNone(runtime.records["TOKEN"]["feature_value"])

    def test_patch_restores_live_state(self):
        original_state = live_v3.OnlinePumpFeatureState
        original_run_live = live_v3.run_live
        with patched_holder_ownership_native_v1(helius_api_key="helius"):
            self.assertIsNot(live_v3.OnlinePumpFeatureState, original_state)
            self.assertIsNot(live_v3.run_live, original_run_live)
        self.assertIs(live_v3.OnlinePumpFeatureState, original_state)
        self.assertIs(live_v3.run_live, original_run_live)

    def test_evaluator_rejects_systems_invalid_native_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            payload = {
                "classification": "PASS_LAUNCH_BURST_HOLDER_OWNERSHIP_NATIVE_V1",
                "base_v4_report": {
                    "requested_duration_seconds": 900,
                    "capture": {"stop_reason": "duration_elapsed"},
                },
                "guardrails": {
                    "market_ingest_provider": "solana_public_standard_wss",
                    "market_ingest_http_hydration": False,
                    "helius_wss_used_for_market_ingest": False,
                },
                "holder_ownership_native_v1": {
                    "status_counts": {"CAUSAL_AVAILABLE": 10, "HELIUS_RATE_LIMITED": 1},
                    "guardrails": {
                        "gmgn_dependency": False,
                        "private_key_used": False,
                        "selector_changed": False,
                    },
                },
            }
            (run_dir / "simulation-report-v4-holder-ownership-native-v1.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "systems-invalid"):
                _validate_fresh_capture(run_dir)

    def test_preflight_opens_no_outcomes_and_uses_only_helius_methods(self):
        supply = {
            "error": None,
            "result": {"value": {"amount": "1000"}},
        }
        accounts = {
            "error": None,
            "result": {"token_accounts": [{"owner": "A", "amount": "1"}]},
        }
        with patch(
            "benchmarks.holder_ownership_native_v1.preflight._rpc_once",
            side_effect=[supply, accounts],
        ), patch(
            "benchmarks.holder_ownership_native_v1.preflight.run_market_ingest_preflight",
            return_value={
                "classification": "PASS_PUBLIC_SOLANA_STANDARD_WSS_PREFLIGHT",
                "source_provider": "solana_public_standard_wss",
                "endpoint_host": "api.mainnet.solana.com",
                "subscription_ack_count": 3,
                "slot_notification_seen": True,
                "http_hydration_used": False,
                "economic_outcomes_opened": False,
                "elapsed_seconds": 0.5,
            },
        ):
            report = run_preflight(
                protocol_path=DEFAULT_PROTOCOL,
                token_mint="TOKEN",
                helius_api_key="helius",
            )
        self.assertEqual(report["classification"], "PASS_HOLDER_OWNERSHIP_NATIVE_V1_PREFLIGHT")
        self.assertFalse(report["economic_outcomes_opened"])
        self.assertFalse(report["gmgn_used"])
        self.assertEqual(report["schema_probe"]["methods"], ["getTokenSupply", "getTokenAccounts"])
        self.assertEqual(report["market_ingest"]["source_provider"], "solana_public_standard_wss")
        self.assertFalse(report["market_ingest"]["http_hydration_used"])


    def test_public_market_ingest_patch_is_explicit_and_restored(self):
        original_url = paper_v2.helius_wss_url
        original_collect_source = helius_collect.SOURCE_PROVIDER
        original_rotating_source = rotating_trace.SOURCE_PROVIDER
        original_rotating_header = rotating_trace.trace_header

        with patched_public_solana_standard_wss_v1():
            self.assertEqual(paper_v2.helius_wss_url("ignored"), PUBLIC_SOLANA_WSS_URL)
            self.assertEqual(helius_collect.SOURCE_PROVIDER, "solana_public_standard_wss")
            self.assertEqual(rotating_trace.SOURCE_PROVIDER, "solana_public_standard_wss")
            header = rotating_trace.trace_header(
                duration_seconds=1.0,
                max_log_notifications=0,
                started_wall_ns=1,
            )
            self.assertEqual(header["source_provider"], "solana_public_standard_wss")
            self.assertEqual(header["endpoint_host"], "api.mainnet.solana.com")

        self.assertIs(paper_v2.helius_wss_url, original_url)
        self.assertEqual(helius_collect.SOURCE_PROVIDER, original_collect_source)
        self.assertEqual(rotating_trace.SOURCE_PROVIDER, original_rotating_source)
        self.assertIs(rotating_trace.trace_header, original_rotating_header)


    def test_association_has_no_threshold_promotion(self):
        rows = [
            {FEATURE_ID: 0.01, "outcome": 10.0},
            {FEATURE_ID: 0.02, "outcome": 5.0},
            {FEATURE_ID: 0.03, "outcome": -5.0},
            {FEATURE_ID: 0.04, "outcome": -10.0},
        ]
        result = _association(rows, feature_key=FEATURE_ID, outcome_key="outcome")
        self.assertEqual(result["usable_pair_count"], 4)
        self.assertLess(result["spearman"], 0)
        self.assertTrue(result["direction_matches_preregistered"])
        self.assertNotIn("threshold", result)
        self.assertNotIn("decision", result)


if __name__ == "__main__":
    unittest.main()
