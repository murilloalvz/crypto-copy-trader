from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.deployer_prior_quality_v0.run import (
    DEFAULT_PROTOCOL,
    _association,
    _validate_fresh_capture,
    _validate_protocol,
)
from benchmarks.deployer_prior_quality_v0.runtime_enrichment import (
    FEATURE_ID,
    DeployerEvidenceRuntimeV0,
    _cli_environment,
    _collect_deployer_evidence_sync,
    _run_cli_command,
    patched_deployer_prior_quality_v0,
)
from benchmarks.launch_burst_prospective_route_live_v3 import live as live_v3


class DeployerPriorQualityV0Tests(unittest.TestCase):
    def _success_runner(self, *, total_inner: int = 4, total_open: int = 1):
        calls = []
        token = "TOKEN"
        creator = "CREATOR"
        now = time.time_ns()

        def runner(*, args, api_key, timeout_seconds):
            self.assertEqual(api_key, "api-key")
            self.assertGreater(timeout_seconds, 0)
            self.assertLessEqual(timeout_seconds, 4.5)
            calls.append(list(args))
            if args[:2] == ["token", "info"]:
                return {
                    "args": list(args),
                    "request_before_wall_ns": now,
                    "response_after_wall_ns": now + 100_000_000,
                    "duration_ms": 100.0,
                    "exit_code": 0,
                    "error": None,
                    "rate_limited": False,
                    "stdout_sha256": "info",
                    "raw_stdout": "{}",
                    "raw_stderr": "",
                    "payload": {
                        "address": token,
                        "dev": {"creator_address": creator},
                        "stat": {"creator_created_count": total_inner + total_open},
                    },
                    "private_key_used": False,
                    "capital_used": False,
                    "retry_count": 0,
                }
            return {
                "args": list(args),
                "request_before_wall_ns": now + 200_000_000,
                "response_after_wall_ns": now + 400_000_000,
                "duration_ms": 200.0,
                "exit_code": 0,
                "error": None,
                "rate_limited": False,
                "stdout_sha256": "created",
                "raw_stdout": "{}",
                "raw_stderr": "",
                "payload": {
                    "inner_count": total_inner,
                    "open_count": total_open,
                    "open_ratio": str(total_open / (total_inner + total_open)),
                    "tokens": [
                        {"token_address": token, "token_ath_mc": "3000"},
                        {"token_address": "OLD", "token_ath_mc": "9000"},
                    ],
                },
                "private_key_used": False,
                "capital_used": False,
                "retry_count": 0,
            }

        return token, now, calls, runner

    def test_protocol_hash_and_discovery_guardrails_are_frozen(self):
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
            "e1fd572b2913eccc174e1536c0e2ff29d8feefa2c740b786f85c62bd7616f179",
        )
        self.assertEqual(expected, actual)
        protocol["protocol_hash_sha256"] = expected
        _validate_protocol(protocol)
        self.assertFalse(protocol["directional_read"]["promotion_from_this_sample_allowed"])
        self.assertFalse(protocol["feature_contract"]["threshold_search_allowed"])
        self.assertFalse(protocol["acquisition"]["private_key_allowed"])

    def test_current_token_is_excluded_from_created_count(self):
        token, now, calls, runner = self._success_runner(total_inner=4, total_open=1)
        record = _collect_deployer_evidence_sync(
            token_mint=token,
            observed_t0_wall_ns=now - 100_000_000,
            decision_cutoff_wall_ns=now + 5_000_000_000,
            api_key="api-key",
            command_runner=runner,
        )
        self.assertEqual(record["status"], "CAUSAL_AVAILABLE")
        self.assertEqual(record["total_created_snapshot"], 5)
        self.assertEqual(record[ "feature_value"], 4)
        self.assertTrue(record["current_token_present_in_returned_rows"])
        self.assertEqual(record["prior_best_ath_mc_returned_rows"], 9000.0)
        self.assertTrue(record["creator_created_count_crosscheck"])
        self.assertEqual(len(calls), 2)

    def test_late_token_info_fails_closed_without_created_tokens_call(self):
        token, now, calls, runner = self._success_runner()

        def late_runner(*, args, api_key, timeout_seconds):
            row = runner(args=args, api_key=api_key, timeout_seconds=timeout_seconds)
            row["response_after_wall_ns"] = now + 6_000_000_000
            return row

        record = _collect_deployer_evidence_sync(
            token_mint=token,
            observed_t0_wall_ns=now,
            decision_cutoff_wall_ns=now + 5_000_000_000,
            api_key="api-key",
            command_runner=late_runner,
        )
        self.assertEqual(record["status"], "LATE_TOKEN_INFO")
        self.assertIsNone(record["feature_value"])
        self.assertEqual(len(calls), 1)

    def test_late_created_tokens_is_never_backfilled(self):
        token, now, calls, runner = self._success_runner()

        def late_created_runner(*, args, api_key, timeout_seconds):
            row = runner(args=args, api_key=api_key, timeout_seconds=timeout_seconds)
            if args[:2] == ["portfolio", "created-tokens"]:
                row["response_after_wall_ns"] = now + 6_000_000_000
            return row

        record = _collect_deployer_evidence_sync(
            token_mint=token,
            observed_t0_wall_ns=now,
            decision_cutoff_wall_ns=now + 5_000_000_000,
            api_key="api-key",
            command_runner=late_created_runner,
        )
        self.assertEqual(record["status"], "LATE_CREATED_TOKENS")
        self.assertIsNone(record["feature_value"])
        self.assertEqual(record["total_created_snapshot"], 5)
        self.assertEqual(len(calls), 2)

    def test_rate_limit_fails_closed_and_is_not_retried(self):
        now = time.time_ns()
        calls = []

        def rate_limited(*, args, api_key, timeout_seconds):
            self.assertGreater(timeout_seconds, 0)
            calls.append(list(args))
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
                "raw_stderr": "HTTP 429 RATE_LIMIT_EXCEEDED",
                "payload": None,
                "private_key_used": False,
                "capital_used": False,
                "retry_count": 0,
            }

        record = _collect_deployer_evidence_sync(
            token_mint="TOKEN",
            observed_t0_wall_ns=now,
            decision_cutoff_wall_ns=now + 5_000_000_000,
            api_key="api-key",
            command_runner=rate_limited,
        )
        self.assertEqual(record["status"], "RATE_LIMITED_TOKEN_INFO")
        self.assertIsNone(record["feature_value"])
        self.assertEqual(len(calls), 1)

    def test_private_key_is_removed_from_cli_environment(self):
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

    def test_snapshot_enrichment_preserves_existing_features_and_selector_inputs(self):
        runtime = DeployerEvidenceRuntimeV0(api_key="api-key")
        runtime.records["TOKEN"] = {
            "version": "deployer_prior_quality_runtime_v0",
            "status": "CAUSAL_AVAILABLE",
            "feature_id": FEATURE_ID,
            "feature_value": 9,
            "total_created_snapshot": 10,
            "private_key_used": False,
            "capital_used": False,
            "selector_changed": False,
        }
        original = {
            "stratum": "pump_launch",
            "complete": True,
            "features": {
                "signed_flow_over_event_reserve": 0.10,
                "event_count": 20,
            },
        }
        enriched = runtime.enrich_snapshot("TOKEN", original)
        self.assertEqual(original["features"], {
            "signed_flow_over_event_reserve": 0.10,
            "event_count": 20,
        })
        self.assertEqual(enriched["features"]["signed_flow_over_event_reserve"], 0.10)
        self.assertEqual(enriched["features"]["event_count"], 20)
        self.assertEqual(enriched["features"][FEATURE_ID], 9)
        self.assertIn("deployer_prior_quality_v0", enriched["external_evidence"])

    def test_patch_restores_online_feature_state_and_run_live(self):
        original_state = live_v3.OnlinePumpFeatureState
        original_run_live = live_v3.run_live
        with patched_deployer_prior_quality_v0(api_key="api-key"):
            self.assertIsNot(live_v3.OnlinePumpFeatureState, original_state)
            self.assertIsNot(live_v3.run_live, original_run_live)
        self.assertIs(live_v3.OnlinePumpFeatureState, original_state)
        self.assertIs(live_v3.run_live, original_run_live)

    def test_runtime_uses_bounded_two_slot_concurrency(self):
        runtime = DeployerEvidenceRuntimeV0(api_key="api-key")
        self.assertEqual(runtime.max_concurrent_acquisitions, 2)

    def test_finalize_drains_pending_task_within_causal_cutoff(self):
        async def scenario():
            runtime = DeployerEvidenceRuntimeV0(api_key="api-key")

            async def complete():
                await asyncio.sleep(0.01)
                runtime.records["TOKEN"] = {
                    "version": "deployer_prior_quality_runtime_v0",
                    "token_mint": "TOKEN",
                    "status": "LATE_BEFORE_TOKEN_INFO",
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
            self.assertEqual(runtime.records["TOKEN"]["status"], "LATE_BEFORE_TOKEN_INFO")

        asyncio.run(scenario())

    def test_finalize_cancels_task_still_pending_after_causal_cutoff(self):
        async def scenario():
            runtime = DeployerEvidenceRuntimeV0(api_key="api-key")

            async def blocked():
                await asyncio.sleep(1.0)

            runtime.tasks["TOKEN"] = asyncio.create_task(blocked())
            runtime.decision_cutoff_wall_ns_by_token["TOKEN"] = time.time_ns() + 1_000_000
            await runtime.finalize()

            self.assertTrue(runtime.tasks["TOKEN"].cancelled())
            self.assertEqual(
                runtime.records["TOKEN"]["status"],
                "TASK_CANCELLED_AFTER_CAPTURE",
            )

        asyncio.run(scenario())

    def test_cli_decodes_non_utf8_bytes_without_reader_thread_failure(self):
        fake = SimpleNamespace(
            returncode=0,
            stdout=b'{"ok":true}\x81',
            stderr=b'warning:\x81',
        )
        with patch(
            "benchmarks.deployer_prior_quality_v0.runtime_enrichment._resolve_gmgn_cli",
            return_value="gmgn-cli.cmd",
        ), patch(
            "benchmarks.deployer_prior_quality_v0.runtime_enrichment.subprocess.run",
            return_value=fake,
        ):
            result = _run_cli_command(
                args=["token", "info", "--chain", "sol", "--address", "TOKEN", "--raw"],
                api_key="api-key",
                timeout_seconds=1.0,
            )
        self.assertEqual(result["exit_code"], -2)
        self.assertEqual(result["error"], "INVALID_JSON")
        self.assertIn("\ufffd", result["raw_stdout"])
        self.assertIn("\ufffd", result["raw_stderr"])

    def test_evaluator_rejects_cancelled_sidecar_acquisition(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            payload = {
                "classification": "PASS_LAUNCH_BURST_CONTROL_TAKER_SIM_V4_SNIPER_V1",
                "base_v4_report": {
                    "requested_duration_seconds": 900,
                    "capture": {"stop_reason": "duration_elapsed"},
                },
                "deployer_prior_quality_v0": {
                    "status_counts": {
                        "CAUSAL_AVAILABLE": 4,
                        "TASK_CANCELLED_AFTER_CAPTURE": 334,
                    },
                    "guardrails": {
                        "gmgn_private_key_used": False,
                        "selector_changed": False,
                    },
                },
            }
            (run_dir / "simulation-report-v4-sniper-v1.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "systems-invalid"):
                _validate_fresh_capture(run_dir)

    def test_association_is_descriptive_and_has_no_threshold_promotion(self):
        rows = [
            {FEATURE_ID: 1, "outcome": 10.0},
            {FEATURE_ID: 2, "outcome": 5.0},
            {FEATURE_ID: 3, "outcome": -5.0},
            {FEATURE_ID: 4, "outcome": -10.0},
        ]
        result = _association(rows, feature_key=FEATURE_ID, outcome_key="outcome")
        self.assertEqual(result["usable_pair_count"], 4)
        self.assertLess(result["spearman"], 0)
        self.assertNotIn("threshold", result)
        self.assertNotIn("decision", result)


if __name__ == "__main__":
    unittest.main()
