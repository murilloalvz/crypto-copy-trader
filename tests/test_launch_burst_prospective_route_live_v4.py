import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.helius_standard_wss_shadow_v0.collect import Counters
from benchmarks.launch_burst_prospective_route_live_v3.live import (
    DEFAULT_CONTRACT,
    EXPECTED_ROUTE_CONTRACT_HASH,
    _process_chunk,
    _read_json,
)
from benchmarks.launch_burst_prospective_route_live_v4.live import (
    DEFAULT_DECODER_TARGET_ENV,
    LIVE_VERSION,
    _default_decoder_target,
    _rotation_watermark_loop,
)
from benchmarks.launch_burst_prospective_route_live_v4.preflight import (
    PASS as PREFLIGHT_PASS,
    run_preflight,
)
from benchmarks.launch_burst_prospective_route_live_v4.summarize import summarize
from benchmarks.market_first_live_discovery_v0.rotating_trace import RotatingTraceHandleV0


class LaunchBurstProspectiveRouteLiveV4Tests(unittest.TestCase):
    def test_empty_watermark_chunk_is_fifo_finalized_and_reducer_compatible(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                queue = asyncio.Queue()
                active = asyncio.Event()
                counters = Counters()
                counters.sessions_activated = 1
                handle = RotatingTraceHandleV0(
                    raw_dir=root / "raw",
                    finalized_queue=queue,
                    active_event=active,
                    counters=counters,
                    duration_seconds=10.0,
                    max_bytes=1024 * 1024,
                )

                finalized = handle.rotate_for_watermark(
                    stop_reason="prospective_timed_watermark_v4"
                )
                self.assertIsNotNone(finalized)
                queued = await queue.get()
                self.assertEqual(queued, finalized)
                self.assertIsNotNone(handle.finalized_wall_ns(finalized))

                rows = [
                    json.loads(line)
                    for line in finalized.read_text(encoding="utf-8").splitlines()
                ]
                footer = rows[-1]
                self.assertEqual(footer["type"], "trace_footer")
                self.assertEqual(footer["payload_rows"], 0)
                self.assertEqual(
                    footer["stop_reason"], "prospective_timed_watermark_v4"
                )

                fake_binary = root / ("unused.exe" if os.name == "nt" else "unused")
                report = _process_chunk(
                    raw_path=finalized,
                    processed_root=root / "processed",
                    decoder_binary=fake_binary,
                    finalized_wall_ns=int(handle.finalized_wall_ns(finalized)),
                    queue_depth_at_start=0,
                )
                self.assertEqual(report["status"], "NO_TARGET_EVENTS")
                self.assertEqual(
                    int(report["reducer"].get("accepted_success_target_events") or 0),
                    0,
                )
                handle.close(stop_reason="done")

        asyncio.run(scenario())

    def test_watermark_rotation_loop_finalizes_empty_ticks(self):
        class FakeHandle:
            def __init__(self):
                self.closed = False
                self.calls = 0

            def rotate_for_watermark(self, *, stop_reason):
                self.calls += 1
                self.stop_reason = stop_reason
                return Path(f"chunk-{self.calls:06d}.jsonl")

        async def scenario():
            handle = FakeHandle()
            stop = asyncio.Event()
            task = asyncio.create_task(
                _rotation_watermark_loop(
                    handle,
                    interval_seconds=0.001,
                    stop_event=stop,
                )
            )
            while handle.calls < 2:
                await asyncio.sleep(0.001)
            stop.set()
            await task
            return handle

        handle = asyncio.run(scenario())
        self.assertGreaterEqual(handle.calls, 2)
        self.assertEqual(handle.stop_reason, "prospective_timed_watermark_v4")

    def test_decoder_target_env_override_is_respected(self):
        target = str(Path("custom") / "short-decoder-target")
        with patch.dict(os.environ, {DEFAULT_DECODER_TARGET_ENV: target}, clear=False):
            self.assertEqual(_default_decoder_target(), Path(target))

    def test_v4_preserves_frozen_contract_hash(self):
        contract = _read_json(
            Path("benchmarks")
            / "launch_burst_prospective_economic_v1"
            / "pump_route_paper_contract_v2.frozen.json"
        )
        self.assertEqual(
            contract["contract_hash_sha256"], EXPECTED_ROUTE_CONTRACT_HASH
        )
        predicate = contract["selection_rule"]["predicates"][0]
        self.assertEqual(predicate["feature"], "signed_flow_over_event_reserve")
        self.assertEqual(predicate["op"], ">=")
        self.assertEqual(predicate["value"], 0.08)
        self.assertEqual(contract["primary_evidence"]["window_seconds"], 5)
        self.assertEqual(contract["entry"]["latency_seconds"], 2)
        self.assertEqual(contract["exit"]["horizon_seconds"], 60)
        self.assertEqual(LIVE_VERSION, "launch_burst_prospective_route_live_v4")

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
        self.assertEqual(report["classification"], PREFLIGHT_PASS)
        self.assertFalse(report["provider_calls_enabled"])
        self.assertFalse(report["economic_outcomes_opened"])
        self.assertTrue(report["gates"]["required_env_present"])

    def test_preflight_build_uses_requested_short_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "short"
            binary = target.resolve() / "release" / (
                "carbon-decoder-parity-v1-runner.exe"
                if os.name == "nt"
                else "carbon-decoder-parity-v1-runner"
            )
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_bytes(b"fixture")
            completed = subprocess.CompletedProcess(
                args=["cargo"], returncode=0, stdout="", stderr=""
            )
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
        self.assertEqual(report["classification"], PREFLIGHT_PASS)
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
