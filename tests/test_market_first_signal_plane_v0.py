from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.market_first_live_discovery_v0.pipeline import LiveDiscoveryPipelineStateV0
from benchmarks.market_first_signal_plane_v0.pipeline import (
    DurableResearchStateV0,
    drain_deferred_operations_v0,
    process_canonical_chunk_signal_plane_v0,
)
from src import database
from src.market_observation_store import load_market_trades


class MarketFirstSignalPlaneV0Tests(unittest.TestCase):
    def test_trade_hits_kernel_before_observation_persistence_and_drain_persists_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / "canonical.jsonl"
            manifest = root / "manifest.jsonl"
            canonical.write_text(
                json.dumps(
                    {
                        "type": "carbon_canonical_event",
                        "status": "decoded",
                        "event_key": "E1",
                        "event_type": "pump_trade",
                        "mint": "TOKEN",
                        "side": "buy",
                        "timestamp": 101,
                        "wallet": "WALLET",
                        "signature": "SIG",
                        "quote_mint": "SOL",
                        "quote_amount_raw": 10,
                        "virtual_quote_reserves_raw": 1000,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            manifest.write_text(
                json.dumps(
                    {
                        "event_key": "E1",
                        "first_received_wall_ns": 101_000_000_000,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            state = LiveDiscoveryPipelineStateV0()
            result = process_canonical_chunk_signal_plane_v0(
                state=state,
                acquisition_run_key="RUN",
                carbon_output_path=canonical,
                target_manifest_path=manifest,
                discovery_start_wall_ns=100_000_000_000,
                discovery_close_wall_ns=102_000_000_000,
            )
            self.assertEqual(state.market_trade_adapted_events, 1)
            self.assertEqual(state.kernel.stats().trade_events_ingested, 1)
            self.assertEqual(len(result.deferred_operations), 1)
            self.assertEqual(result.emitted_trigger_count, 0)
            self.assertEqual(result.first_trigger_count, 0)

            db_path = root / "signal-plane.db"
            isolated = replace(database.settings, database_path=db_path)
            with patch.object(database, "settings", isolated):
                before = load_market_trades(acquisition_run_key="RUN", token_mint="TOKEN")
                self.assertEqual(before, ())
                durable = drain_deferred_operations_v0(result.deferred_operations)
                after = load_market_trades(acquisition_run_key="RUN", token_mint="TOKEN")

            self.assertEqual(len(after), 1)
            self.assertEqual(after[0].event_key, "E1")
            self.assertEqual(durable.observation_writes_attempted, 1)
            self.assertEqual(durable.observation_writes_inserted, 1)
            self.assertEqual(durable.errors, [])

    def test_drain_rejects_nonpositive_batch_size(self) -> None:
        with self.assertRaises(ValueError):
            drain_deferred_operations_v0((), max_observation_batch_size=0)

    def test_durable_state_summary_is_explicit(self) -> None:
        state = DurableResearchStateV0()
        self.assertEqual(state.summary()["errors"], [])
        self.assertEqual(state.summary()["batches_committed"], 0)


if __name__ == "__main__":
    unittest.main()
