import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.helius_standard_wss_shadow_v0.collect import Counters
from benchmarks.launch_burst_prospective_route_paper_v2.live import OnlinePumpFeatureState
from benchmarks.market_first_live_discovery_v0.rotating_trace import RotatingTraceHandleV0


class LaunchBurstProspectiveRouteLiveV2Tests(unittest.TestCase):
    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    def test_online_snapshot_matches_frozen_5s_feature_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            chunk = Path(directory) / "chunk-000001"
            canonical = [
                {
                    "type": "carbon_canonical_event",
                    "status": "decoded",
                    "event_type": "pump_create",
                    "event_key": "create:1",
                    "mint": "MINT_A",
                    "timestamp": 1000,
                },
                {
                    "type": "carbon_canonical_event",
                    "status": "decoded",
                    "event_type": "pump_trade",
                    "event_key": "trade:1",
                    "mint": "MINT_A",
                    "side": "buy",
                    "timestamp": 1004,
                    "quote_mint": "SOL",
                    "quote_amount_raw": 10,
                    "virtual_quote_reserves_raw": 100,
                },
                {
                    "type": "carbon_canonical_event",
                    "status": "decoded",
                    "event_type": "pump_trade",
                    "event_key": "trade:future",
                    "mint": "MINT_A",
                    "side": "sell",
                    "timestamp": 1007,
                    "quote_mint": "SOL",
                    "quote_amount_raw": 50,
                    "virtual_quote_reserves_raw": 100,
                },
            ]
            manifest = [
                {"event_key": "create:1", "first_received_wall_ns": 110_250_000_000},
                {"event_key": "trade:1", "first_received_wall_ns": 114_000_000_000},
                {"event_key": "trade:future", "first_received_wall_ns": 117_000_000_000},
            ]
            self._write_jsonl(chunk / "carbon-canonical.jsonl", canonical)
            self._write_jsonl(chunk / "target-manifest.jsonl", manifest)

            state = OnlinePumpFeatureState()
            state.ingest_processed_chunk(chunk)
            self.assertEqual(state.ready_snapshots(coverage_through_wall_ns=115_249_999_999), [])
            ready = state.ready_snapshots(coverage_through_wall_ns=115_250_000_000)

        self.assertEqual(len(ready), 1)
        token, snapshot = ready[0]
        self.assertEqual(token, "MINT_A")
        self.assertEqual(snapshot["decision_cutoff_wall_ns"], 115_250_000_000)
        self.assertEqual(snapshot["features"]["event_count"], 1)
        self.assertAlmostEqual(snapshot["features"]["signed_flow_over_event_reserve"], 0.1)

    def test_uncovered_anchor_remains_right_censored(self):
        with tempfile.TemporaryDirectory() as directory:
            chunk = Path(directory) / "chunk-000001"
            self._write_jsonl(
                chunk / "carbon-canonical.jsonl",
                [{"type": "carbon_canonical_event", "status": "decoded", "event_type": "pump_create", "event_key": "create:1", "mint": "MINT_A", "timestamp": 1000}],
            )
            self._write_jsonl(
                chunk / "target-manifest.jsonl",
                [{"event_key": "create:1", "first_received_wall_ns": 110_250_000_000}],
            )
            state = OnlinePumpFeatureState()
            state.ingest_processed_chunk(chunk)
            censored = state.right_censored_snapshots()
        self.assertEqual(len(censored), 1)
        self.assertFalse(censored[0][1]["complete"])

    def test_explicit_rotation_records_finalize_clock(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as directory:
                queue = asyncio.Queue()
                active = asyncio.Event()
                handle = RotatingTraceHandleV0(
                    raw_dir=Path(directory),
                    finalized_queue=queue,
                    active_event=active,
                    counters=Counters(),
                    duration_seconds=10.0,
                    max_bytes=1024 * 1024,
                )
                handle.write(json.dumps({"type": "fixture_event"}) + "\n")
                finalized = handle.rotate_if_nonempty(stop_reason="test_rotation")
                self.assertIsNotNone(finalized)
                queued = await queue.get()
                self.assertEqual(queued, finalized)
                finalized_ns = handle.finalized_wall_ns(finalized)
                self.assertIsInstance(finalized_ns, int)
                rows = [json.loads(line) for line in finalized.read_text(encoding="utf-8").splitlines()]
                footer = rows[-1]
                self.assertEqual(footer["stop_reason"], "test_rotation")
                self.assertEqual(footer["finalized_wall_ns"], finalized_ns)
                handle.close(stop_reason="done")
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
