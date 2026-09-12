from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src import database
from src.market_observation_batch_v0 import (
    MarketLifecycleWriteV0,
    MarketTradeWriteV0,
    record_market_observations_batch_v0,
)
from src.market_observation_store import (
    count_market_replay_conflicts,
    load_latest_market_lifecycle,
    load_market_trades,
)
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation


class MarketObservationBatchV0Tests(unittest.TestCase):
    def test_mixed_batch_preserves_replay_and_conflict_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "batch.db"
            isolated = replace(database.settings, database_path=db_path)
            trade = MarketTradeObservation(
                token_mint="TOKEN",
                side="buy",
                chain_time=100,
                observed_at=200,
                wallet_address="WALLET",
                venue="pump",
                transaction_key="SIG",
            )
            lifecycle = MarketLifecycleObservation(
                token_mint="TOKEN",
                market_started_at=90,
                observed_at=190,
                venue="pump",
            )
            with patch.object(database, "settings", isolated):
                first = record_market_observations_batch_v0(
                    (
                        MarketLifecycleWriteV0("RUN", "L1", "helius", lifecycle),
                        MarketTradeWriteV0("RUN", "T1", "helius", trade),
                    )
                )
                self.assertEqual(first.attempted, 2)
                self.assertEqual(first.inserted, 2)
                self.assertEqual(first.conflicts, 0)

                replay = record_market_observations_batch_v0(
                    (MarketTradeWriteV0("RUN", "T1", "helius", trade),)
                )
                self.assertEqual(replay.inserted, 0)
                self.assertEqual(replay.replayed, 1)

                conflicting = MarketTradeObservation(
                    token_mint="TOKEN",
                    side="sell",
                    chain_time=100,
                    observed_at=201,
                    wallet_address="WALLET",
                    venue="pump",
                    transaction_key="SIG",
                )
                conflict = record_market_observations_batch_v0(
                    (MarketTradeWriteV0("RUN", "T1", "helius", conflicting),)
                )
                self.assertEqual(conflict.conflicts, 1)
                self.assertEqual(count_market_replay_conflicts(acquisition_run_key="RUN"), 1)

                rows = load_market_trades(acquisition_run_key="RUN", token_mint="TOKEN")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].observation.side, "buy")
                latest = load_latest_market_lifecycle(
                    acquisition_run_key="RUN", token_mint="TOKEN"
                )
                self.assertIsNotNone(latest)
                assert latest is not None
                self.assertEqual(latest.event_key, "L1")

    def test_empty_batch_is_noop(self) -> None:
        result = record_market_observations_batch_v0(())
        self.assertEqual(result.attempted, 0)
        self.assertEqual(result.inserted, 0)
        self.assertEqual(result.replayed, 0)
        self.assertEqual(result.conflicts, 0)


if __name__ == "__main__":
    unittest.main()
