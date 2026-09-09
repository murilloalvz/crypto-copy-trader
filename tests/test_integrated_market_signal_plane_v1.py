import tempfile
from pathlib import Path
import unittest

from benchmarks.commodity_signal_plane_v0.benchmark import (
    TraceRecord,
    generate_synthetic_trace,
    load_trace,
)
from benchmarks.integrated_market_signal_plane_v1.suite import (
    canonical_event_to_record,
    record_to_canonical_event,
    run_integrated,
)
from src.market_opportunity_radar import MarketTradeObservation


class IntegratedMarketSignalPlaneV1Tests(unittest.TestCase):
    def test_canonical_adapter_roundtrip(self):
        record = TraceRecord(
            sequence=3,
            arrival_offset_ns=123,
            kind="trade",
            event_key="e3",
            source_provider="test",
            trade=MarketTradeObservation(
                "MINT", "buy", 100, 101, "W", 4.2, 0.5, "pumpswap", "TX"
            ),
        )
        self.assertEqual(canonical_event_to_record(record_to_canonical_event(record)), record)

    def test_unknown_schema_fails_closed(self):
        with self.assertRaises(ValueError):
            canonical_event_to_record(
                {
                    "schema_version": "future",
                    "sequence": 0,
                    "arrival_offset_ns": 0,
                    "kind": "trade",
                    "event_key": "x",
                    "source_provider": "x",
                    "observation": {},
                }
            )

    def test_integrated_semantics_and_accounting(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            generate_synthetic_trace(out=path, events=1200, seed=68)
            _, records = load_trace(path)
            report = run_integrated(records)

        self.assertEqual(report["adapter"]["parity_pct"], 100.0)
        self.assertEqual(report["detector"]["parity_pct"], 100.0)
        self.assertEqual(report["detector"]["mismatches"], 0)
        self.assertEqual(
            report["burst_research_handoff"]["accounted"], report["record_count"]
        )
        self.assertEqual(
            report["burst_research_handoff"]["worker_completed"],
            report["burst_research_handoff"]["accepted"],
        )


if __name__ == "__main__":
    unittest.main()
