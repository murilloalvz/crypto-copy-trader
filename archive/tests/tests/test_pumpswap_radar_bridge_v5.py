import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import record_market_trade
from src.market_opportunity_episode_store import ensure_market_opportunity_episode_schema
from src.market_opportunity_radar import MarketTradeObservation
from src.pumpswap_normalized_persistence import PumpSwapNormalizedPersistResult
from src.pumpswap_radar_bridge_v4 import evaluate_persisted_pumpswap_notification_for_radar_v4
from src.pumpswap_radar_bridge_v5 import (
    finalize_prepared_pumpswap_radar_v5,
    prepare_persisted_pumpswap_notification_for_radar_v5,
)
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapTradeEvent


class PumpSwapRadarBridgeV5Tests(unittest.TestCase):
    def _record(
        self,
        run_key: str,
        key: str,
        *,
        chain_time: int,
        observed_at: int,
        wallet: str,
        tx: str,
    ) -> None:
        record_market_trade(
            acquisition_run_key=run_key,
            event_key=key,
            source_provider="test",
            observation=MarketTradeObservation(
                token_mint="TOKEN",
                side="buy",
                chain_time=chain_time,
                observed_at=observed_at,
                wallet_address=wallet,
                venue="pumpswap",
                transaction_key=tx,
            ),
        )

    def _seed_trigger_history(self, run_key: str) -> None:
        for i in range(3):
            self._record(
                run_key,
                f"base-{i}",
                chain_time=800 + i,
                observed_at=801 + i,
                wallet=f"B{i}",
                tx=f"base-tx-{i}",
            )
        for i in range(5):
            self._record(
                run_key,
                f"fast-{i}",
                chain_time=976 + i * 4,
                observed_at=977 + i * 4,
                wallet=f"F{i}",
                tx=f"fast-tx-{i}",
            )

    def _notification(self, signature: str, *, chain_time: int, observed_at: int, wallet: str):
        return PumpSwapLogNotification(
            signature=signature,
            slot=1,
            observed_at=observed_at,
            trade_events=(
                PumpSwapTradeEvent(
                    side="buy",
                    pool="POOL",
                    user=wallet,
                    timestamp=chain_time,
                    base_amount_raw=1,
                    quote_amount_raw=1,
                    event_index=0,
                ),
            ),
        )

    def test_prepare_is_read_only_and_finalize_matches_v4_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge-v5.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self._seed_trigger_history("run")
                self._record(
                    "run",
                    "trigger",
                    chain_time=996,
                    observed_at=997,
                    wallet="F5",
                    tx="trigger-tx",
                )
                notification = self._notification(
                    "trigger-tx",
                    chain_time=996,
                    observed_at=997,
                    wallet="F5",
                )
                persisted = PumpSwapNormalizedPersistResult(
                    1, 0, 0, 0, 0, 0, ("TOKEN",)
                )

                prepared = prepare_persisted_pumpswap_notification_for_radar_v5(
                    notification,
                    acquisition_run_key="run",
                    persist_result=persisted,
                )
                ensure_market_opportunity_episode_schema()
                with database.connection() as conn:
                    before = conn.execute(
                        "SELECT COUNT(*) AS n FROM market_opportunity_episodes"
                    ).fetchone()["n"]
                self.assertEqual(before, 0)

                split_result = finalize_prepared_pumpswap_radar_v5(
                    prepared,
                    acquisition_run_key="run",
                )
                legacy_result = evaluate_persisted_pumpswap_notification_for_radar_v4(
                    notification,
                    acquisition_run_key="run",
                    persist_result=persisted,
                )

        self.assertEqual(split_result.affected_tokens, legacy_result.affected_tokens)
        self.assertEqual(len(split_result.hits), 1)
        self.assertEqual(len(legacy_result.hits), 1)
        self.assertEqual(
            split_result.hits[0].episode.episode_key,
            legacy_result.hits[0].episode.episode_key,
        )
        self.assertEqual(split_result.hits[0].episode.first_trigger_observed_at, 997)
        self.assertGreaterEqual(split_result.telemetry.episode_assign_seconds, 0.0)

    def test_no_trigger_finalize_does_not_persist_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge-v5-no-trigger.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self._record(
                    "run",
                    "single",
                    chain_time=996,
                    observed_at=997,
                    wallet="W1",
                    tx="single-tx",
                )
                notification = self._notification(
                    "single-tx",
                    chain_time=996,
                    observed_at=997,
                    wallet="W1",
                )
                persisted = PumpSwapNormalizedPersistResult(
                    1, 0, 0, 0, 0, 0, ("TOKEN",)
                )
                prepared = prepare_persisted_pumpswap_notification_for_radar_v5(
                    notification,
                    acquisition_run_key="run",
                    persist_result=persisted,
                )
                self.assertTrue(all(token.trigger is None for token in prepared.tokens))

                ensure_market_opportunity_episode_schema()
                with database.connection() as conn:
                    before = conn.execute(
                        "SELECT COUNT(*) AS n FROM market_opportunity_episodes"
                    ).fetchone()["n"]

                result = finalize_prepared_pumpswap_radar_v5(
                    prepared,
                    acquisition_run_key="run",
                )

                with database.connection() as conn:
                    after = conn.execute(
                        "SELECT COUNT(*) AS n FROM market_opportunity_episodes"
                    ).fetchone()["n"]

        self.assertEqual(result.hits, ())
        self.assertEqual(before, 0)
        self.assertEqual(after, 0)
        self.assertEqual(result.telemetry.episode_assign_seconds, 0.0)

    def test_prepared_notifications_finalize_in_fifo_into_same_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge-v5-order.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                self._seed_trigger_history("run")
                self._record(
                    "run",
                    "trigger-1",
                    chain_time=996,
                    observed_at=997,
                    wallet="F5",
                    tx="trigger-tx-1",
                )
                self._record(
                    "run",
                    "trigger-2",
                    chain_time=997,
                    observed_at=998,
                    wallet="F6",
                    tx="trigger-tx-2",
                )
                persisted = PumpSwapNormalizedPersistResult(
                    1, 0, 0, 0, 0, 0, ("TOKEN",)
                )
                first = prepare_persisted_pumpswap_notification_for_radar_v5(
                    self._notification(
                        "trigger-tx-1",
                        chain_time=996,
                        observed_at=997,
                        wallet="F5",
                    ),
                    acquisition_run_key="run",
                    persist_result=persisted,
                )
                second = prepare_persisted_pumpswap_notification_for_radar_v5(
                    self._notification(
                        "trigger-tx-2",
                        chain_time=997,
                        observed_at=998,
                        wallet="F6",
                    ),
                    acquisition_run_key="run",
                    persist_result=persisted,
                )

                first_result = finalize_prepared_pumpswap_radar_v5(
                    first,
                    acquisition_run_key="run",
                )
                second_result = finalize_prepared_pumpswap_radar_v5(
                    second,
                    acquisition_run_key="run",
                )

        self.assertEqual(len(first_result.hits), 1)
        self.assertEqual(len(second_result.hits), 1)
        self.assertEqual(
            first_result.hits[0].episode.episode_key,
            second_result.hits[0].episode.episode_key,
        )
        self.assertEqual(
            first_result.hits[0].episode.first_trigger_key,
            "market-radar:pumpswap-v3:trigger-tx-1:TOKEN",
        )


if __name__ == "__main__":
    unittest.main()
