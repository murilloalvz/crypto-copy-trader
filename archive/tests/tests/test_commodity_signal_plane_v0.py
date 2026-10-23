import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.commodity_signal_plane_v0.benchmark import (
    BoundedMemoryRadarState,
    ReferenceRadarState,
    TraceRecord,
    generate_synthetic_trace,
    load_trace,
    run_benchmark,
    simulate_single_worker_queue,
    write_trace,
)
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation


class CommoditySignalPlaneV0Tests(unittest.TestCase):
    def test_trace_roundtrip_preserves_causal_payload(self):
        records = (
            TraceRecord(
                sequence=0,
                arrival_offset_ns=0,
                kind="lifecycle",
                event_key="life:T",
                source_provider="test",
                lifecycle=MarketLifecycleObservation("T", 90, 95, "pump_bonding_curve"),
            ),
            TraceRecord(
                sequence=1,
                arrival_offset_ns=10_000_000,
                kind="trade",
                event_key="trade:T:1",
                source_provider="test",
                trade=MarketTradeObservation(
                    "T", "buy", 100, 101, "W", 5.0, 1.0, "pump_bonding_curve", "TX"
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            header = write_trace(path, records, metadata={"source": "unit"})
            loaded_header, loaded = load_trace(path)
        self.assertEqual(header, loaded_header)
        self.assertEqual(records, loaded)

    def test_synthetic_trace_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.jsonl"
            b = Path(tmp) / "b.jsonl"
            generate_synthetic_trace(out=a, events=300, seed=68)
            generate_synthetic_trace(out=b, events=300, seed=68)
            self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_memory_kernel_has_exact_detector_parity_on_synthetic_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            generate_synthetic_trace(out=path, events=900, seed=68)
            _, records = load_trace(path)
            report = run_benchmark(records, scales=(1.0, 1.5, 2.0))
        self.assertEqual(report["parity"]["mismatches"], 0)
        self.assertEqual(report["parity"]["parity_pct"], 100.0)
        self.assertFalse(report["interpretation"]["carbon_decoder_tested"])
        self.assertGreater(report["shadow_memory_kernel"]["capacity_eps_from_mean_service"], 0)

    def test_late_chain_time_insert_does_not_change_reference_equivalence(self):
        records = []
        seq = 0
        for i in range(3):
            records.append(
                TraceRecord(
                    sequence=seq,
                    arrival_offset_ns=seq * 1_000_000,
                    kind="trade",
                    event_key=f"baseline:{i}",
                    source_provider="test",
                    trade=MarketTradeObservation(
                        "T", "buy", 800 + i, 900 + i, f"B{i}", 5.0, 1.0, "pumpswap", f"B{i}"
                    ),
                )
            )
            seq += 1
        for i in range(6):
            records.append(
                TraceRecord(
                    sequence=seq,
                    arrival_offset_ns=seq * 1_000_000,
                    kind="trade",
                    event_key=f"fast:{i}",
                    source_provider="test",
                    trade=MarketTradeObservation(
                        "T", "buy", 975 + i * 4, 976 + i * 4, f"F{i}", 5.0, 1.0, "pumpswap", f"F{i}"
                    ),
                )
            )
            seq += 1
        # Arrives later but belongs to older chain time. It must not become fresh flow.
        records.append(
            TraceRecord(
                sequence=seq,
                arrival_offset_ns=seq * 1_000_000,
                kind="trade",
                event_key="late-old",
                source_provider="test",
                trade=MarketTradeObservation(
                    "T", "buy", 700, 1001, "LATE", 9.0, 9.0, "pumpswap", "LATE"
                ),
            )
        )
        reference = ReferenceRadarState()
        shadow = BoundedMemoryRadarState()
        for record in records:
            self.assertEqual(
                None if (a := reference.ingest(record)) is None else a,
                None if (b := shadow.ingest(record)) is None else b,
            )
        self.assertGreaterEqual(shadow.late_chain_time_inserts, 1)

    def test_queue_simulator_exposes_overload_and_waiting_depth(self):
        records = tuple(
            TraceRecord(
                sequence=i,
                arrival_offset_ns=i * 10_000_000,  # 100 events/s
                kind="trade",
                event_key=f"e{i}",
                source_provider="test",
                trade=MarketTradeObservation(
                    "T", "buy", 100 + i, 100 + i, f"W{i}", 1.0, 1.0, "pumpswap", f"TX{i}"
                ),
            )
            for i in range(20)
        )
        result = simulate_single_worker_queue(records, [0.020] * len(records), scale=1.0)
        self.assertGreater(result["queue_wait_p95_ms"], 0)
        self.assertGreater(result["queue_depth_high_water"], 0)
        self.assertGreater(result["backlog_at_source_end"], 0)
        self.assertGreater(result["drain_after_source_seconds"], 0)

    def test_invalid_trace_sequence_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            path.write_text(
                json.dumps({"type": "trace_header", "version": "canonical_market_trace_v0", "record_count": 1})
                + "\n"
                + json.dumps(
                    {
                        "type": "trade",
                        "sequence": 5,
                        "arrival_offset_ns": 0,
                        "event_key": "bad",
                        "source_provider": "test",
                        "observation": {
                            "token_mint": "T",
                            "side": "buy",
                            "chain_time": 1,
                            "observed_at": 1,
                            "wallet_address": "W",
                            "notional_usd": 1.0,
                            "price_usd": 1.0,
                            "venue": "pumpswap",
                            "transaction_key": "TX",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_trace(path)


if __name__ == "__main__":
    unittest.main()
