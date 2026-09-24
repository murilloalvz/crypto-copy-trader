from __future__ import annotations

import unittest
from unittest.mock import patch

from benchmarks.commodity_signal_plane_v0.benchmark import TraceRecord
from src.market_opportunity_radar import (
    MarketLifecycleObservation,
    MarketTradeObservation,
)
from src.market_observation_batch_v0 import MarketObservationBatchResultV0
from src.signal_plane_episode_admission_v0 import SignalPlaneEpisodeAdmissionResult
from src.signal_plane_research_persistence_v0 import (
    SIGNAL_PLANE_RESEARCH_PERSISTENCE_VERSION,
    persist_signal_plane_research_batch,
    persist_signal_plane_research_record,
)


class SignalPlaneResearchPersistenceV0Tests(unittest.TestCase):
    def test_version_is_frozen(self):
        self.assertEqual(
            SIGNAL_PLANE_RESEARCH_PERSISTENCE_VERSION,
            "signal_plane_research_persistence_v0",
        )

    def test_trade_is_persisted_before_episode_admission(self):
        record = TraceRecord(
            sequence=7,
            arrival_offset_ns=10,
            kind="trade",
            event_key="event-7",
            source_provider="provider",
            trade=MarketTradeObservation(
                token_mint="TOKEN",
                side="buy",
                chain_time=100,
                observed_at=101,
                venue="pump",
                transaction_key="tx",
            ),
        )
        order = []

        def persist(**kwargs):
            order.append("persist")
            return True

        def admit(**kwargs):
            order.append("admit")
            return None

        with patch(
            "src.signal_plane_research_persistence_v0.record_market_trade",
            side_effect=persist,
        ), patch(
            "src.signal_plane_research_persistence_v0.admit_signal_plane_trigger_snapshot",
            side_effect=admit,
        ):
            result = persist_signal_plane_research_record(
                acquisition_run_key="run",
                record=record,
                trigger_snapshot={"trigger": "placeholder"},
            )

        self.assertEqual(order, ["persist", "admit"])
        self.assertTrue(result.observation_inserted)
        self.assertEqual(result.sequence, 7)

    def test_trade_threads_injected_admission_callback(self):
        record = TraceRecord(
            sequence=9,
            arrival_offset_ns=20,
            kind="trade",
            event_key="event-9",
            source_provider="provider",
            trade=MarketTradeObservation(
                token_mint="TOKEN",
                side="buy",
                chain_time=109,
                observed_at=110,
                venue="pump",
                transaction_key="tx-9",
            ),
        )
        callback = lambda **kwargs: True

        with patch(
            "src.signal_plane_research_persistence_v0.record_market_trade",
            return_value=True,
        ), patch(
            "src.signal_plane_research_persistence_v0.admit_signal_plane_trigger_snapshot",
            return_value=None,
        ) as admit:
            persist_signal_plane_research_record(
                acquisition_run_key="run",
                record=record,
                trigger_snapshot={"trigger": "placeholder"},
                admit_episode_fn=callback,
            )

        self.assertIs(
            admit.call_args.kwargs["admit_episode_fn"],
            callback,
        )

    def test_lifecycle_never_admits_episode(self):
        record = TraceRecord(
            sequence=3,
            arrival_offset_ns=1,
            kind="lifecycle",
            event_key="lifecycle-3",
            source_provider="provider",
            lifecycle=MarketLifecycleObservation(
                token_mint="TOKEN",
                market_started_at=90,
                observed_at=100,
                venue="pump",
            ),
        )
        with patch(
            "src.signal_plane_research_persistence_v0.record_market_lifecycle",
            return_value=True,
        ) as persist, patch(
            "src.signal_plane_research_persistence_v0.admit_signal_plane_trigger_snapshot"
        ) as admit:
            result = persist_signal_plane_research_record(
                acquisition_run_key="run",
                record=record,
                trigger_snapshot=None,
            )

        persist.assert_called_once()
        admit.assert_not_called()
        self.assertTrue(result.observation_inserted)
        self.assertIsNone(result.episode)


    def test_batch_commits_trigger_observation_before_admission(self):
        first = TraceRecord(
            sequence=0,
            arrival_offset_ns=1,
            kind="trade",
            event_key="event-0",
            source_provider="provider",
            trade=MarketTradeObservation(
                token_mint="TOKEN",
                side="buy",
                chain_time=100,
                observed_at=101,
                venue="pump",
                transaction_key="tx-0",
            ),
        )
        trigger = TraceRecord(
            sequence=1,
            arrival_offset_ns=2,
            kind="trade",
            event_key="event-1",
            source_provider="provider",
            trade=MarketTradeObservation(
                token_mint="TOKEN",
                side="buy",
                chain_time=102,
                observed_at=103,
                venue="pump",
                transaction_key="tx-1",
            ),
        )
        order = []

        def persist_batch(items):
            order.append(("persist", tuple(item.event_key for item in items)))
            return MarketObservationBatchResultV0(
                attempted=len(items),
                inserted=len(items),
                replayed=0,
                conflicts=0,
            )

        def admit(**kwargs):
            order.append(("admit", kwargs["observation"].transaction_key))
            return SignalPlaneEpisodeAdmissionResult(
                episode_key="episode",
                token_mint="TOKEN",
                first_trigger_observed_at=103,
                admitted=True,
            )

        with patch(
            "src.signal_plane_research_persistence_v0.record_market_observations_batch_v0",
            side_effect=persist_batch,
        ), patch(
            "src.signal_plane_research_persistence_v0.admit_signal_plane_trigger_snapshot",
            side_effect=admit,
        ):
            result = persist_signal_plane_research_batch(
                acquisition_run_key="run",
                items=((first, None), (trigger, {"trigger": "placeholder"})),
            )

        self.assertEqual(
            order,
            [("persist", ("event-0", "event-1")), ("admit", "tx-1")],
        )
        self.assertEqual(result.completed, 2)
        self.assertEqual(result.sqlite_transactions, 1)
        self.assertEqual(result.max_transaction_records, 2)
        self.assertEqual(result.trigger_episodes, 1)
        self.assertEqual(result.new_admissions, 1)

    def test_batch_starts_new_transaction_after_trigger_admission(self):
        trigger = TraceRecord(
            sequence=4,
            arrival_offset_ns=1,
            kind="trade",
            event_key="event-4",
            source_provider="provider",
            trade=MarketTradeObservation(
                token_mint="TOKEN",
                side="buy",
                chain_time=104,
                observed_at=105,
                venue="pump",
                transaction_key="tx-4",
            ),
        )
        later = TraceRecord(
            sequence=5,
            arrival_offset_ns=2,
            kind="lifecycle",
            event_key="event-5",
            source_provider="provider",
            lifecycle=MarketLifecycleObservation(
                token_mint="TOKEN",
                market_started_at=100,
                observed_at=106,
                venue="pump",
            ),
        )
        order = []

        def persist_batch(items):
            order.append(("persist", tuple(item.event_key for item in items)))
            return MarketObservationBatchResultV0(
                attempted=len(items),
                inserted=len(items),
                replayed=0,
                conflicts=0,
            )

        def admit(**kwargs):
            order.append(("admit", kwargs["observation"].transaction_key))
            return SignalPlaneEpisodeAdmissionResult(
                episode_key="episode",
                token_mint="TOKEN",
                first_trigger_observed_at=105,
                admitted=False,
            )

        with patch(
            "src.signal_plane_research_persistence_v0.record_market_observations_batch_v0",
            side_effect=persist_batch,
        ), patch(
            "src.signal_plane_research_persistence_v0.admit_signal_plane_trigger_snapshot",
            side_effect=admit,
        ):
            result = persist_signal_plane_research_batch(
                acquisition_run_key="run",
                items=((trigger, {"trigger": "placeholder"}), (later, None)),
            )

        self.assertEqual(
            order,
            [
                ("persist", ("event-4",)),
                ("admit", "tx-4"),
                ("persist", ("event-5",)),
            ],
        )
        self.assertEqual(result.sqlite_transactions, 2)
        self.assertEqual(result.admission_replays, 1)
        self.assertEqual(result.trades_completed, 1)
        self.assertEqual(result.lifecycles_completed, 1)

    def test_batch_rejects_sequence_gap_before_writing(self):
        first = TraceRecord(
            sequence=10,
            arrival_offset_ns=1,
            kind="trade",
            event_key="event-10",
            source_provider="provider",
            trade=MarketTradeObservation(
                token_mint="TOKEN",
                side="buy",
                chain_time=110,
                observed_at=111,
                venue="pump",
                transaction_key="tx-10",
            ),
        )
        gap = TraceRecord(
            sequence=12,
            arrival_offset_ns=2,
            kind="trade",
            event_key="event-12",
            source_provider="provider",
            trade=MarketTradeObservation(
                token_mint="TOKEN",
                side="sell",
                chain_time=112,
                observed_at=113,
                venue="pump",
                transaction_key="tx-12",
            ),
        )

        with patch(
            "src.signal_plane_research_persistence_v0.record_market_observations_batch_v0",
        ) as persist_batch:
            with self.assertRaisesRegex(
                RuntimeError,
                "research persistence batch sequence mismatch",
            ):
                persist_signal_plane_research_batch(
                    acquisition_run_key="run",
                    items=((first, None), (gap, None)),
                )

        persist_batch.assert_not_called()



if __name__ == "__main__":
    unittest.main()
