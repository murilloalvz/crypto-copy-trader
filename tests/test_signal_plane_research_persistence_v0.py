from __future__ import annotations

import unittest
from unittest.mock import patch

from benchmarks.commodity_signal_plane_v0.benchmark import TraceRecord
from src.market_opportunity_radar import (
    MarketLifecycleObservation,
    MarketTradeObservation,
)
from src.signal_plane_research_persistence_v0 import (
    SIGNAL_PLANE_RESEARCH_PERSISTENCE_VERSION,
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


if __name__ == "__main__":
    unittest.main()
