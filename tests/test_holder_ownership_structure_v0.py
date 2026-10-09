from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from benchmarks.holder_ownership_structure_v0.preflight import run_preflight
from benchmarks.holder_ownership_structure_v0.run import (
    DEFAULT_PROTOCOL,
    _association,
    _validate_fresh_capture,
    _validate_protocol,
)
from benchmarks.holder_ownership_structure_v0.runtime_enrichment import (
    FEATURE_ID,
    MIN_PROVIDER_START_INTERVAL_SECONDS,
    HolderOwnershipRuntimeV0,
    _cli_environment,
    _collect_holder_evidence_sync,
    patched_holder_ownership_structure_v0,
)
from benchmarks.launch_burst_prospective_route_live_v3 import live as live_v3


class HolderOwnershipStructureV0Tests(unittest.TestCase):
    def _runner(self, rows, *, late=False, rate_limited=False):
        calls = []
        now = time.time_ns()

        def runner(*, args, api_key, timeout_seconds):
            self.assertEqual(api_key, "api-key")
            self.assertGreater(timeout_seconds, 0)
            self.assertLessEqual(timeout_seconds, 4.5)
            calls.append(list(args))
            if rate_limited:
                return {
                    "args": list(args),
                    "request_before_wall_ns": now,
                    "response_after_wall_ns": now + 10_000_000,
                    "duration_ms": 10.0,
                    "exit_code": 1,
                    "error": None,
                    "rate_limited": True,
                    "stdout_sha256": "x",
                    "raw_stdout": "",
                    "raw_stderr": "HTTP 429",
                    "payload": None,
                    "private_key_used": False,
                    "capital_used": False,
                    "retry_count": 0,
                }
            return {
                "args": list(args),
                "request_before_wall_ns": now,
                "response_after_wall_ns": now + (6_000_000_000 if late else 100_000_000),
                "duration_ms": 100.0,
                "exit_code": 0,
                "error": None,
                "rate_limited": False,
                "stdout_sha256": "holders",
                "raw_stdout": "{}",
                "raw_stderr": "",
                "payload": {"list": rows},
                "private_key_used": False,
                "capital_used": False,
                "retry_count": 0,
            }

        return now, calls, runner

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
            "1b64a88415ec7815cda87c240234daf9ca21b4a413b6585e87377d67b9ef1dff",
        )
        self.assertEqual(expected, actual)
        protocol["protocol_hash_sha256"] = expected
        _validate_protocol(protocol)
        self.assertEqual(protocol["feature_contract"]["expected_direction"], "negative")
        self.assertFalse(protocol["feature_contract"]["threshold_search_allowed"])
        self.assertFalse(protocol["acquisition"]["private_key_allowed"])
        self.assertFalse(protocol["directional_read"]["promotion_from_this_sample_allowed"])

    def test_hhi_uses_regular_wallets_only_and_total_supply_shares(self):
        rows = [
            {"address": "POOL", "addr_type": 2, "amount_percentage": 0.90},
            {"address": "DEAD", "addr_type": 1, "amount_percentage": 0.03},
            {"address": "A", "addr_type": 0, "amount_percentage": 0.04},
            {"address": "B", "addr_type": 0, "amount_percentage": 0.02},
            {"address": "C", "addr_type": 0, "amount_percentage": 0.01},
        ]
        now, calls, runner = self._runner(rows)
        record = _collect_holder_evidence_sync(
            token_mint="TOKEN",
            observed_t0_wall_ns=now,
            decision_cutoff_wall_ns=now + 5_000_000_000,
            api_key="api-key",
            command_runner=runner,
        )
        self.assertEqual(record["status"], "CAUSAL_AVAILABLE")
        self.assertAlmostEqual(record["feature_value"], 0.04**2 + 0.02**2 + 0.01**2)
        self.assertEqual(record["regular_wallet_count"], 3)
        self.assertEqual(record["burn_dead_count"], 1)
        self.assertEqual(record["dex_pool_count"], 1)
        self.assertAlmostEqual(record["regular_wallet_supply_share_top100"], 0.07)
        self.assertEqual(record["denominator"], "total_supply")
        self.assertEqual(record["excluded_addr_types"], [1, 2])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ["token", "holders"])
        self.assertIn("100", calls[0])

    def test_unknown_addr_type_fails_closed(self):
        rows = [
            {"address": "A", "addr_type": 0, "amount_percentage": 0.03},
            {"address": "UNKNOWN", "addr_type": 9, "amount_percentage": 0.02},
        ]
        now, _, runner = self._runner(rows)
        record = _collect_holder_evidence_sync(
            token_mint="TOKEN",
            observed_t0_wall_ns=now,
            decision_cutoff_wall_ns=now + 5_000_000_000,
            api_key="api-key",
            command_runner=runner,
        )
        self.assertEqual(record["status"], "AMBIGUOUS_ADDR_TYPE")
        self.assertIsNone(record["feature_value"])

    def test_missing_regular_wallet_share_fails_closed(self):
        rows = [{"address": "A", "addr_type": 0, "amount_percentage": None}]
        now, _, runner = self._runner(rows)
        record = _collect_holder_evidence_sync(
            token_mint="TOKEN",
            observed_t0_wall_ns=now,
            decision_cutoff_wall_ns=now + 5_000_000_000,
            api_key="api-key",
            command_runner=runner,
        )
        self.assertEqual(record["status"], "REGULAR_WALLET_SHARE_INVALID")
        self.assertIsNone(record["feature_value"])

    def test_late_response_is_never_backfilled(self):
        rows = [{"address": "A", "addr_type": 0, "amount_percentage": 0.03}]
        now, _, runner = self._runner(rows, late=True)
        record = _collect_holder_evidence_sync(
            token_mint="TOKEN",
            observed_t0_wall_ns=now,
            decision_cutoff_wall_ns=now + 5_000_000_000,
            api_key="api-key",
            command_runner=runner,
        )
        self.assertEqual(record["status"], "LATE_HOLDERS")
        self.assertIsNone(record["feature_value"])
        self.assertAlmostEqual(record["largest_regular_wallet_supply_share"], 0.03)

    def test_rate_limit_is_missing_and_not_retried(self):
        now, calls, runner = self._runner([], rate_limited=True)
        record = _collect_holder_evidence_sync(
            token_mint="TOKEN",
            observed_t0_wall_ns=now,
            decision_cutoff_wall_ns=now + 5_000_000_000,
            api_key="api-key",
            command_runner=runner,
        )
        self.assertEqual(record["status"], "RATE_LIMITED_HOLDERS")
        self.assertIsNone(record["feature_value"])
        self.assertEqual(len(calls), 1)

    def test_private_key_is_removed_from_environment(self):
        env = _cli_environment(
            "api-key",
            {
                "PATH": "x",
                "GMGN_PRIVATE_KEY": "do-not-use",
                "GMGN_API_KEY": "old",
            },
        )
        self.assertEqual(env["GMGN_API_KEY"], "api-key")
        self.assertNotIn("GMGN_PRIVATE_KEY", env)
        self.assertEqual(env["GMGN_RATE_LIMIT_AUTO_RETRY_MAX_WAIT_MS"], "0")

    def test_snapshot_enrichment_preserves_existing_features(self):
        runtime = HolderOwnershipRuntimeV0(api_key="api-key")
        runtime.records["TOKEN"] = {
            "version": "holder_ownership_structure_runtime_v0",
            "status": "CAUSAL_AVAILABLE",
            "feature_id": FEATURE_ID,
            "feature_value": 0.002,
            "denominator": "total_supply",
            "excluded_addr_types": [1, 2],
            "private_key_used": False,
            "capital_used": False,
            "selector_changed": False,
        }
        original = {
            "features": {
                "signed_flow_over_event_reserve": 0.10,
                "event_count": 20,
            }
        }
        enriched = runtime.enrich_snapshot("TOKEN", original)
        self.assertEqual(original["features"]["event_count"], 20)
        self.assertEqual(enriched["features"]["signed_flow_over_event_reserve"], 0.10)
        self.assertEqual(enriched["features"][FEATURE_ID], 0.002)
        self.assertIn("holder_ownership_structure_v0", enriched["external_evidence"])

    def test_patch_restores_live_state(self):
        original_state = live_v3.OnlinePumpFeatureState
        original_run_live = live_v3.run_live
        with patched_holder_ownership_structure_v0(api_key="api-key"):
            self.assertIsNot(live_v3.OnlinePumpFeatureState, original_state)
            self.assertIsNot(live_v3.run_live, original_run_live)
        self.assertIs(live_v3.OnlinePumpFeatureState, original_state)
        self.assertIs(live_v3.run_live, original_run_live)

    def test_runtime_respects_single_provider_slot(self):
        runtime = HolderOwnershipRuntimeV0(api_key="api-key")
        self.assertEqual(runtime.max_concurrent_acquisitions, 1)
        self.assertEqual(
            runtime.min_provider_start_interval_seconds,
            MIN_PROVIDER_START_INTERVAL_SECONDS,
        )


    def test_runtime_paces_provider_starts_and_fails_closed_if_cutoff_too_near(self):
        async def scenario():
            runtime = HolderOwnershipRuntimeV0(api_key="api-key")
            runtime._semaphore = asyncio.Semaphore(1)
            runtime._last_provider_request_started_monotonic = time.monotonic()
            now_ns = time.time_ns()
            await runtime._acquire(
                token_mint="TOKEN",
                observed_t0_wall_ns=now_ns,
                decision_cutoff_wall_ns=now_ns + 100_000_000,
            )
            self.assertEqual(
                runtime.records["TOKEN"]["status"],
                "LATE_WAITING_FOR_RATE_SLOT",
            )

        asyncio.run(scenario())


    def test_finalize_drains_only_until_causal_cutoff(self):
        async def scenario():
            runtime = HolderOwnershipRuntimeV0(api_key="api-key")

            async def complete():
                await asyncio.sleep(0.01)
                runtime.records["TOKEN"] = {
                    "version": "holder_ownership_structure_runtime_v0",
                    "token_mint": "TOKEN",
                    "status": "LATE_BEFORE_HOLDERS",
                    "feature_id": FEATURE_ID,
                    "feature_value": None,
                    "private_key_used": False,
                    "capital_used": False,
                    "selector_changed": False,
                }

            runtime.tasks["TOKEN"] = asyncio.create_task(complete())
            runtime.decision_cutoff_wall_ns_by_token["TOKEN"] = time.time_ns() + 200_000_000
            await runtime.finalize()
            self.assertFalse(runtime.tasks["TOKEN"].cancelled())
            self.assertEqual(runtime.records["TOKEN"]["status"], "LATE_BEFORE_HOLDERS")

        asyncio.run(scenario())

    def test_evaluator_rejects_systems_invalid_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            payload = {
                "classification": "PASS_LAUNCH_BURST_HOLDER_OWNERSHIP_STRUCTURE_V0",
                "base_v4_report": {
                    "requested_duration_seconds": 900,
                    "capture": {"stop_reason": "duration_elapsed"},
                },
                "holder_ownership_structure_v0": {
                    "status_counts": {
                        "CAUSAL_AVAILABLE": 10,
                        "TASK_CANCELLED_AFTER_CAPTURE": 1,
                    },
                    "guardrails": {
                        "gmgn_private_key_used": False,
                        "selector_changed": False,
                        "tradeable_float_rebase_used": False,
                    },
                },
            }
            (run_dir / "simulation-report-v4-holder-ownership-v0.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "systems-invalid"):
                _validate_fresh_capture(run_dir)


    def test_evaluator_rejects_rate_limit_saturated_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            payload = {
                "classification": "PASS_LAUNCH_BURST_HOLDER_OWNERSHIP_STRUCTURE_V0",
                "base_v4_report": {
                    "requested_duration_seconds": 900,
                    "capture": {"stop_reason": "duration_elapsed"},
                },
                "holder_ownership_structure_v0": {
                    "status_counts": {
                        "CAUSAL_AVAILABLE": 4,
                        "RATE_LIMITED_HOLDERS": 419,
                    },
                    "guardrails": {
                        "gmgn_private_key_used": False,
                        "selector_changed": False,
                        "tradeable_float_rebase_used": False,
                    },
                },
            }
            (run_dir / "simulation-report-v4-holder-ownership-v0.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "systems-invalid"):
                _validate_fresh_capture(run_dir)


    def test_preflight_is_read_only_and_redacts_feature_value(self):
        fake_record = {
            "status": "CAUSAL_AVAILABLE",
            "returned_holder_row_count": 4,
            "regular_wallet_count": 2,
            "burn_dead_count": 1,
            "dex_pool_count": 1,
            "denominator": "total_supply",
            "excluded_addr_types": [1, 2],
            "feature_value": 0.0017,
        }
        with patch(
            "benchmarks.holder_ownership_structure_v0.preflight._collect_holder_evidence_sync",
            return_value=fake_record,
        ):
            report = run_preflight(
                protocol_path=DEFAULT_PROTOCOL,
                token_mint="TOKEN",
                api_key="api-key",
            )
        self.assertEqual(report["classification"], "PASS_HOLDER_OWNERSHIP_STRUCTURE_V0_PREFLIGHT")
        self.assertFalse(report["economic_outcomes_opened"])
        self.assertFalse(report["selector_changed"])
        self.assertTrue(report["schema_probe"]["feature_value_redacted"])
        self.assertNotIn("feature_value", report["schema_probe"])
        self.assertEqual(report["schema_probe"]["excluded_addr_types"], [1, 2])


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
