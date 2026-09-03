import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src import database
from src.market_observation_store import record_market_trade
from src.market_opportunity_radar import MarketTradeObservation
from src.market_transaction_view import load_market_trades_by_transaction
from src.pumpswap_radar_bridge_v2 import process_pumpswap_notification_for_radar_v2
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapPersistResult, PumpSwapTradeEvent


class PumpSwapRadarBridgeV2Tests(unittest.IsolatedAsyncioTestCase):
    def _record(self, run_key: str, index: int, *, chain_time: int, observed_at: int, wallet: str):
        record_market_trade(
            acquisition_run_key=run_key,
            event_key=f"event-{index}",
            source_provider="test",
            observation=MarketTradeObservation(
                token_mint="TOKEN",
                side="buy",
                chain_time=chain_time,
                observed_at=observed_at,
                wallet_address=wallet,
                venue="pumpswap",
                transaction_key="trigger-tx" if index >= 10 else f"base-{index}",
            ),
        )

    async def test_bridge_reuses_persisted_transaction_without_second_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge-v2.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                for i in range(3):
                    self._record("run", i, chain_time=800, observed_at=801, wallet=f"B{i}")
                for i in range(6):
                    self._record(
                        "run", 10 + i, chain_time=975 + i * 4, observed_at=976 + i * 4,
                        wallet=f"F{i}"
                    )

                rows = load_market_trades_by_transaction(
                    acquisition_run_key="run", transaction_key="trigger-tx"
                )
                self.assertEqual(len(rows), 6)

                resolver = SimpleNamespace(acquisition_run_key="run")
                notification = PumpSwapLogNotification(
                    signature="trigger-tx",
                    slot=1,
                    observed_at=996,
                    trade_events=(
                        PumpSwapTradeEvent(
                            side="buy", pool="POOL", user="F5", timestamp=995,
                            base_amount_raw=1, quote_amount_raw=1, event_index=0
                        ),
                    ),
                )
                persisted = PumpSwapPersistResult(0, 0, 0, 0)
                with patch(
                    "src.pumpswap_radar_bridge_v2.persist_pumpswap_notification",
                    new=AsyncMock(return_value=persisted),
                ) as persist_mock:
                    result = await process_pumpswap_notification_for_radar_v2(
                        notification, acquisition_run_key="run", resolver=resolver
                    )

        persist_mock.assert_awaited_once()
        self.assertEqual(result.affected_tokens, ("TOKEN",))
        self.assertEqual(len(result.hits), 1)
        self.assertEqual(result.hits[0].trigger.trigger_kind, "activity_acceleration")
        self.assertEqual(result.hits[0].episode.first_trigger_observed_at, 996)

    async def test_unresolved_transaction_rows_do_not_invent_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge-v2-empty.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                resolver = SimpleNamespace(acquisition_run_key="run")
                notification = PumpSwapLogNotification(
                    signature="missing-tx", slot=1, observed_at=1000, trade_events=()
                )
                persisted = PumpSwapPersistResult(0, 0, 1, 0)
                with patch(
                    "src.pumpswap_radar_bridge_v2.persist_pumpswap_notification",
                    new=AsyncMock(return_value=persisted),
                ):
                    result = await process_pumpswap_notification_for_radar_v2(
                        notification, acquisition_run_key="run", resolver=resolver
                    )
        self.assertEqual(result.affected_tokens, ())
        self.assertEqual(result.hits, ())


if __name__ == "__main__":
    unittest.main()
