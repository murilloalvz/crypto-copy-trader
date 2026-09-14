from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.launch_burst_prospective_route_live_v4.preflight import (
    PASS,
    run_preflight,
)
from benchmarks.launch_burst_prospective_route_live_v4.summarize import summarize
from benchmarks.launch_burst_prospective_route_live_v3.live import DEFAULT_CONTRACT


class LaunchBurstV4PreflightAndSummaryTests(unittest.TestCase):
    def test_systems_preflight_requires_only_helius_and_opens_nothing(self):
        env = {
            "HELIUS_API_KEY": "present",
            "JUPITER_API_KEY": "",
            "JUPITER_TAKER_PUBLIC_KEY": "",
            "SOLANA_RPC_URL": "",
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, env, clear=False):
            report = run_preflight(
                contract_path=DEFAULT_CONTRACT,
                cargo="cargo",
                decoder_target_dir=Path(directory) / "decoder",
                systems_only=True,
                build_decoder=False,
            )
        self.assertEqual(report["classification"], PASS)
        self.assertFalse(report["provider_calls_enabled"])
        self.assertFalse(report["economic_outcomes_opened"])
        self.assertTrue(report["gates"]["required_env_present"])

    def test_preflight_build_uses_requested_short_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "short"
            binary = target.resolve() / "release" / (
                "carbon-decoder-parity-v1-runner.exe" if os.name == "nt" else "carbon-decoder-parity-v1-runner"
            )
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_bytes(b"fixture")
            completed = subprocess.CompletedProcess(args=["cargo"], returncode=0, stdout="", stderr="")
            with patch.dict(os.environ, {"HELIUS_API_KEY": "present"}, clear=False), patch(
                "benchmarks.launch_burst_prospective_route_live_v3.live.subprocess.run",
                return_value=completed,
            ) as run:
                report = run_preflight(
                    contract_path=DEFAULT_CONTRACT,
                    cargo="cargo",
                    decoder_target_dir=target,
                    systems_only=True,
                    build_decoder=True,
                )
        self.assertEqual(run.call_count, 1)
        self.assertEqual(report["classification"], PASS)
        self.assertEqual(report["decoder_target_dir"], str(target.resolve()))
        self.assertEqual(report["decoder_build"]["target_dir"], str(target.resolve()))

    def test_summary_keeps_only_decision_metrics(self):
        report = {
            "acquisition_run_key": "run-1",
            "classification": "PASS_LAUNCH_BURST_PROSPECTIVE_ROUTE_SYSTEMS_V4",
            "mode": "systems_only",
            "provider_calls_enabled": False,
            "economic_outcomes_opened": False,
            "capture": {"stop_reason": "duration_elapsed"},
            "chunk_count": 900,
            "empty_watermark_chunk_count": 10,
            "processing": {
                "queue_wait_ms": {"p95": 1.0},
                "total_service_ms": {"p95": 200.0},
                "decoder_service_ms": {"p95": 50.0},
                "max_queue_depth": 0,
                "unused": "drop-me",
            },
            "systems": {
                "snapshot_dispatch_lag_ms": {"p95": 900.0},
                "selected_count": 63,
                "selected_before_entry_ready": 63,
                "selected_before_deadline": 63,
                "selected_missed_deadline": 0,
            },
            "gates": {"selected_missed_deadline_zero": True},
            "large_unused_section": {"x": [1, 2, 3]},
        }
        compact = summarize(report)
        self.assertEqual(compact["run"], "run-1")
        self.assertEqual(compact["systems"]["selected_missed_deadline"], 0)
        self.assertEqual(compact["empty_watermark_chunks"], 10)
        self.assertNotIn("large_unused_section", compact)
        self.assertNotIn("unused", compact["processing"])


if __name__ == "__main__":
    unittest.main()
