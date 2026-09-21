from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from benchmarks.holder_ownership_rpc_v2.preflight import run_preflight
from benchmarks.holder_ownership_rpc_v2.protocol import (
    DEFAULT_PROTOCOL,
    EXPECTED_PROTOCOL_HASH,
    canonical_json,
    read_json,
    validate_protocol,
)
from benchmarks.holder_ownership_rpc_v2.rpc_endpoint import (
    PUBLIC_MAINNET_RPC,
    _is_helius,
    rpc_candidates,
)
from benchmarks.holder_ownership_rpc_v2.run import (
    _association,
    _recompute_hhi,
    _validate_fresh_capture,
)
from benchmarks.holder_ownership_rpc_v2.runtime_enrichment import (
    FEATURE_ID,
    _collect_rpc_holder_evidence_sync,
)


class HolderOwnershipRpcV2Tests(unittest.TestCase):
    def test_protocol_hash_is_frozen(self):
        protocol = read_json(DEFAULT_PROTOCOL)
        validate_protocol(protocol)
        expected = protocol["protocol_hash_sha256"]
        shadow = {k: v for k, v in protocol.items() if k != "protocol_hash_sha256"}
        actual = hashlib.sha256(canonical_json(shadow).encode("utf-8")).hexdigest()
        self.assertEqual(expected, EXPECTED_PROTOCOL_HASH)
        self.assertEqual(actual, EXPECTED_PROTOCOL_HASH)
        self.assertEqual(
            protocol["feature_contract"]["coverage_scope"],
            "top 20 token accounts returned by getTokenLargestAccounts only; this is not full-holder HHI",
        )
        self.assertFalse(protocol["guardrails"]["helius_holder_dependency"])
        self.assertFalse(protocol["guardrails"]["gmgn_holder_dependency"])

    def test_rpc_candidates_exclude_helius_and_keep_public_fallback(self):
        with patch.dict(
            os.environ,
            {
                "SOLANA_RPC_URL": "https://mainnet.helius-rpc.com/?api-key=secret",
                "SOLANA_RPC_FALLBACK_URLS": "https://example-rpc.test,https://api.helius.xyz/x",
            },
            clear=False,
        ):
            candidates = rpc_candidates()
        self.assertNotIn("https://mainnet.helius-rpc.com/?api-key=secret", candidates)
        self.assertNotIn("https://api.helius.xyz/x", candidates)
        self.assertIn("https://example-rpc.test", candidates)
        self.assertEqual(candidates[-1], PUBLIC_MAINNET_RPC)
        self.assertTrue(_is_helius("https://mainnet.helius-rpc.com/?api-key=x"))

    def test_hhi_aggregates_top20_accounts_by_owner_and_excludes_curve(self):
        now = time.time_ns()
        calls = []

        def fake_rpc_once(*, rpc_url, method, params, timeout_seconds):
            self.assertEqual(rpc_url, "https://rpc.test")
            self.assertGreater(timeout_seconds, 0)
            calls.append(method)
            common = {
                "method": method,
                "request_before_wall_ns": now + 10_000_000,
                "response_after_wall_ns": now + 30_000_000,
                "duration_ms": 20.0,
                "status_code": 200,
                "error": None,
                "rate_limited": False,
                "retry_after": None,
            }
            if method == "getTokenSupply":
                return {**common, "result": {"value": {"amount": "1000"}}}
            if method == "getTokenLargestAccounts":
                return {
                    **common,
                    "result": {
                        "value": [
                            {"address": "TA_CURVE", "amount": "700"},
                            {"address": "TA_A1", "amount": "100"},
                            {"address": "TA_A2", "amount": "50"},
                            {"address": "TA_B", "amount": "50"},
                        ]
                    },
                }
            return {
                **common,
                "result": {
                    "value": [
                        {"data": {"parsed": {"info": {"owner": "CURVE"}}}},
                        {"data": {"parsed": {"info": {"owner": "A"}}}},
                        {"data": {"parsed": {"info": {"owner": "A"}}}},
                        {"data": {"parsed": {"info": {"owner": "B"}}}},
                    ]
                },
            }

        with patch(
            "benchmarks.holder_ownership_rpc_v2.runtime_enrichment.rpc_once",
            side_effect=fake_rpc_once,
        ):
            record = _collect_rpc_holder_evidence_sync(
                rpc_url="https://rpc.test",
                token_mint="TOKEN",
                bonding_curve="CURVE",
                observed_t0_wall_ns=now - 3_100_000_000,
                decision_cutoff_wall_ns=now + 2_000_000_000,
            )

        self.assertEqual(record["status"], "CAUSAL_AVAILABLE")
        self.assertAlmostEqual(record["feature_value"], 0.15**2 + 0.05**2)
        self.assertEqual(record["top_token_account_count"], 4)
        self.assertEqual(record["top20_unique_owner_count"], 3)
        self.assertEqual(record["top20_non_curve_owner_count"], 2)
        self.assertEqual(record["bonding_curve_top20_amount_raw"], 700)
        self.assertEqual(record["coverage_scope"], "top20_token_accounts")
        self.assertEqual(calls, ["getTokenSupply", "getTokenLargestAccounts", "getMultipleAccounts"])
        self.assertAlmostEqual(_recompute_hhi(record), record["feature_value"])

    def test_rpc_rate_limit_fails_closed_without_retry(self):
        now = time.time_ns()
        with patch(
            "benchmarks.holder_ownership_rpc_v2.runtime_enrichment.rpc_once",
            return_value={
                "method": "getTokenSupply",
                "request_before_wall_ns": now,
                "response_after_wall_ns": now + 1,
                "duration_ms": 1.0,
                "status_code": 429,
                "error": "HTTP_429",
                "rate_limited": True,
                "retry_after": "10",
                "result": None,
            },
        ) as mocked:
            record = _collect_rpc_holder_evidence_sync(
                rpc_url="https://rpc.test",
                token_mint="TOKEN",
                bonding_curve="CURVE",
                observed_t0_wall_ns=now - 3_100_000_000,
                decision_cutoff_wall_ns=now + 2_000_000_000,
            )
        self.assertEqual(record["status"], "RPC_RATE_LIMITED")
        self.assertIsNone(record["feature_value"])
        self.assertEqual(mocked.call_count, 1)

    def test_preflight_uses_non_helius_rpc_and_public_wss_without_outcomes(self):
        selected = {
            "rpc_url": "https://rpc.test",
            "safe_host": "rpc.test",
            "probe_method": "getTokenSupply",
            "probe_ok": True,
            "helius_endpoint": False,
        }
        largest = {
            "error": None,
            "result": {
                "value": [
                    {"address": "TA1", "amount": "10"},
                    {"address": "TA2", "amount": "5"},
                ]
            },
        }
        multiple = {
            "error": None,
            "result": {
                "value": [
                    {"data": {"parsed": {"info": {"owner": "A"}}}},
                    {"data": {"parsed": {"info": {"owner": "B"}}}},
                ]
            },
        }
        market = {
            "classification": "PASS_PUBLIC_SOLANA_STANDARD_WSS_PREFLIGHT",
            "source_provider": "solana_public_standard_wss",
            "endpoint_host": "api.mainnet.solana.com",
            "subscription_ack_count": 3,
            "slot_notification_seen": True,
            "http_hydration_used": False,
            "economic_outcomes_opened": False,
            "elapsed_seconds": 0.5,
        }
        with patch(
            "benchmarks.holder_ownership_rpc_v2.preflight.select_standard_rpc_endpoint",
            return_value=selected,
        ), patch(
            "benchmarks.holder_ownership_rpc_v2.preflight.rpc_once",
            side_effect=[largest, multiple],
        ), patch(
            "benchmarks.holder_ownership_rpc_v2.preflight.run_market_ingest_preflight",
            return_value=market,
        ):
            report = run_preflight()

        self.assertEqual(report["classification"], "PASS_HOLDER_OWNERSHIP_RPC_V2_PREFLIGHT")
        self.assertFalse(report["economic_outcomes_opened"])
        self.assertFalse(report["helius_holder_used"])
        self.assertFalse(report["gmgn_holder_used"])
        self.assertEqual(report["holder_rpc"]["safe_host"], "rpc.test")
        self.assertEqual(report["market_ingest"]["source_provider"], "solana_public_standard_wss")

    def test_evaluator_rejects_rate_limited_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            payload = {
                "classification": "PASS_LAUNCH_BURST_HOLDER_OWNERSHIP_RPC_V2",
                "base_v4_report": {
                    "requested_duration_seconds": 900,
                    "capture": {"stop_reason": "duration_elapsed"},
                },
                "guardrails": {
                    "market_ingest_provider": "solana_public_standard_wss",
                    "market_ingest_http_hydration": False,
                    "helius_holder_dependency": False,
                    "gmgn_holder_dependency": False,
                    "holder_rpc_endpoint_fixed_for_run": True,
                    "holder_rpc_safe_host": "api.mainnet.solana.com",
                },
                "holder_ownership_rpc_v2": {
                    "status_counts": {"CAUSAL_AVAILABLE": 20, "RPC_RATE_LIMITED": 1},
                },
            }
            (run_dir / "simulation-report-v4-holder-ownership-rpc-v2.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "systems-invalid"):
                _validate_fresh_capture(run_dir)

    def test_association_remains_descriptive_no_threshold(self):
        rows = [
            {FEATURE_ID: 0.01, "outcome": 10.0},
            {FEATURE_ID: 0.02, "outcome": 5.0},
            {FEATURE_ID: 0.03, "outcome": -5.0},
            {FEATURE_ID: 0.04, "outcome": -10.0},
        ]
        result = _association(rows, feature_key=FEATURE_ID, outcome_key="outcome")
        self.assertLess(result["spearman"], 0)
        self.assertTrue(result["direction_matches_preregistered"])
        self.assertNotIn("threshold", result)
        self.assertNotIn("decision", result)


if __name__ == "__main__":
    unittest.main()
