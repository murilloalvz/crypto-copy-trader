import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.helius_standard_wss_shadow_v0.collect import Counters
from benchmarks.launch_burst_prospective_route_live_v3.live import (
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


if __name__ == "__main__":
    unittest.main()
