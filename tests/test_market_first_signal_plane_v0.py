from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from benchmarks.market_first_live_discovery_v0.pipeline import LiveDiscoveryPipelineStateV0
from benchmarks.market_first_signal_plane_v0.pipeline import (
    DeferredResearchHandoffV0,
    DurableResearchStateV0,
    SignalPlaneEpisodeTrackerV0,
    drain_deferred_operations_v0,
    process_canonical_chunk_signal_plane_v0,
)
from src import database
from src.database import connection
from src.market_activity_discovery_handoff_v0 import MarketActivityDiscoveryHandoffV0
from src.market_observation_batch_v0 import (
    MarketObservationBatchResultV0,
    MarketTradeWriteV0,
)
from src.market_observation_store import load_market_trades
from src.market_opportunity_episode_batch_v0 import MarketContinuationTriggerWriteV0
from src.market_opportunity_episode_store import load_market_opportunity_episode_triggers
from src.market_opportunity_radar import MarketTradeObservation


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _trigger_fixture(root: Path, *, trade_count: int) -> tuple[Path, Path]:
    canonical = root / "canonical-trigger.jsonl"
    manifest = root / "manifest-trigger.jsonl"
    canonical_rows = [
        {
            "type": "carbon_canonical_event",
            "status": "decoded",
            "event_key": "CREATE",
            "event_type": "pump_create",
            "mint": "TOKEN",
            "timestamp": 100,
        }
    ]
    manifest_rows = [
        {"event_key": "CREATE", "first_received_wall_ns": 100_000_000_000}
    ]
    for index in range(1, trade_count + 1):
        canonical_rows.append(
            {
                "type": "carbon_canonical_event",
                "status": "decoded",
                "event_key": f"E{index}",
                "event_type": "pump_trade",
                "mint": "TOKEN",
                "side": "buy",
                "timestamp": 100 + index,
                "wallet": f"W{index}",
                "signature": f"SIG{index}",
                "quote_mint": "SOL",
                "quote_amount_raw": 10,
                "virtual_quote_reserves_raw": 1000,
            }
        )
        manifest_rows.append(
            {
                "event_key": f"E{index}",
                "first_received_wall_ns": (100 + index) * 1_000_000_000,
            }
        )
    _write_jsonl(canonical, canonical_rows)
    _write_jsonl(manifest, manifest_rows)
    return canonical, manifest


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

    def test_first_trigger_schedules_forward_boundary_before_observation_drain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical, manifest = _trigger_fixture(root, trade_count=6)

            db_path = root / "trigger.db"
            isolated = replace(database.settings, database_path=db_path)
            state = LiveDiscoveryPipelineStateV0()
            with patch.object(database, "settings", isolated):
                result = process_canonical_chunk_signal_plane_v0(
                    state=state,
                    acquisition_run_key="RUN-TRIGGER",
                    carbon_output_path=canonical,
                    target_manifest_path=manifest,
                    discovery_start_wall_ns=99_000_000_000,
                    discovery_close_wall_ns=200_000_000_000,
                )
                self.assertGreaterEqual(result.emitted_trigger_count, 1)
                self.assertEqual(result.first_trigger_count, 1)
                self.assertEqual(state.signal_boundaries_sealed, 1)

                self.assertEqual(
                    load_market_trades(acquisition_run_key="RUN-TRIGGER", token_mint="TOKEN"),
                    (),
                )
                with connection() as conn:
                    forward_count = int(
                        conn.execute(
                            "SELECT COUNT(*) AS n FROM opportunity_forward_outcomes"
                        ).fetchone()["n"]
                    )
                self.assertEqual(forward_count, 3)

            self.assertTrue(
                any(isinstance(item, DeferredResearchHandoffV0) for item in result.deferred_operations)
            )

    def test_continuation_trigger_is_deferred_but_first_trigger_remains_durable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical, manifest = _trigger_fixture(root, trade_count=7)
            db_path = root / "continuation.db"
            isolated = replace(database.settings, database_path=db_path)
            state = LiveDiscoveryPipelineStateV0()
            tracker = SignalPlaneEpisodeTrackerV0()

            with patch.object(database, "settings", isolated):
                result = process_canonical_chunk_signal_plane_v0(
                    state=state,
                    acquisition_run_key="RUN-CONT",
                    carbon_output_path=canonical,
                    target_manifest_path=manifest,
                    discovery_start_wall_ns=99_000_000_000,
                    discovery_close_wall_ns=200_000_000_000,
                    episode_tracker=tracker,
                )
                self.assertEqual(result.first_trigger_count, 1)
                self.assertGreaterEqual(result.emitted_trigger_count, 2)
                self.assertGreaterEqual(state.grouped_trigger_count, 1)
                continuation_ops = [
                    item
                    for item in result.deferred_operations
                    if isinstance(item, MarketContinuationTriggerWriteV0)
                ]
                self.assertTrue(continuation_ops)
                episode = tracker.active_by_token["TOKEN"]
                before = load_market_opportunity_episode_triggers(episode.episode_key)
                self.assertEqual(len(before), 1)
                self.assertEqual(before[0].trigger_key, episode.first_trigger_key)

                durable = drain_deferred_operations_v0(result.deferred_operations)
                after = load_market_opportunity_episode_triggers(episode.episode_key)

            self.assertGreater(len(after), 1)
            self.assertEqual(
                durable.continuation_trigger_writes_attempted,
                len(continuation_ops),
            )
            self.assertEqual(durable.errors, [])

    def test_durable_writes_flush_before_research_handoff(self) -> None:
        order: list[str] = []
        trade = MarketTradeWriteV0(
            acquisition_run_key="RUN",
            event_key="E1",
            source_provider="helius",
            observation=MarketTradeObservation(
                token_mint="TOKEN",
                side="buy",
                chain_time=100,
                observed_at=101,
                wallet_address="W",
                venue="pump",
                transaction_key="SIG",
            ),
        )
        handoff = DeferredResearchHandoffV0(
            handoff=MarketActivityDiscoveryHandoffV0(
                method_version="handoff-v0",
                handoff_key="H1",
                acquisition_run_key="RUN",
                episode_key="EP1",
                token_mint="TOKEN",
                first_trigger_key="TR1",
                decision_as_of=101,
                chain_as_of=100,
            )
        )

        def fake_batch(items):
            order.append("flush")
            return MarketObservationBatchResultV0(
                attempted=len(items), inserted=len(items), replayed=0, conflicts=0
            )

        def fake_research(_handoff):
            order.append("research")
            return SimpleNamespace(provider_calls_performed=0)

        with patch(
            "benchmarks.market_first_signal_plane_v0.pipeline.record_market_observations_batch_v0",
            side_effect=fake_batch,
        ), patch(
            "benchmarks.market_first_signal_plane_v0.pipeline.process_market_activity_discovery_handoff_v0",
            side_effect=fake_research,
        ):
            state = drain_deferred_operations_v0((trade, handoff))

        self.assertEqual(order, ["flush", "research"])
        self.assertEqual(state.research_handoffs_processed, 1)
        self.assertEqual(state.errors, [])

    def test_drain_rejects_nonpositive_batch_size(self) -> None:
        with self.assertRaises(ValueError):
            drain_deferred_operations_v0((), max_observation_batch_size=0)
        with self.assertRaises(ValueError):
            drain_deferred_operations_v0((), max_continuation_trigger_batch_size=0)

    def test_durable_state_summary_is_explicit(self) -> None:
        state = DurableResearchStateV0()
        self.assertEqual(state.summary()["errors"], [])
        self.assertEqual(state.summary()["batches_committed"], 0)
        self.assertEqual(state.summary()["continuation_trigger_batches_committed"], 0)


if __name__ == "__main__":
    unittest.main()
