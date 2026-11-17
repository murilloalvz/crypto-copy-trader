import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src import database
from src.market_observation_store import record_market_trade
from src.market_opportunity_radar import MarketTradeObservation
from src.pumpswap_normalized_persistence import PumpSwapNormalizedPersistResult
from src.pumpswap_radar_bridge_v3 import process_pumpswap_notification_for_radar_v3
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapTradeEvent


class PumpSwapRadarBridgeV3Tests(unittest.IsolatedAsyncioTestCase):
    def _record(self, run_key: str, key: str, *, chain_time: int, observed_at: int, wallet: str, tx: str):
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

    async def test_bridge_uses_normalized_persisted_identity_without_resolving_again(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge-v3.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                for i in range(3):
                    self._record(
                        "run", f"base-{i}", chain_time=800 + i, observed_at=801 + i,
                        wallet=f"B{i}", tx=f"base-tx-{i}"
                    )
                for i in range(5):
                    self._record(
                        "run", f"fast-{i}", chain_time=976 + i * 4, observed_at=977 + i * 4,
                        wallet=f"F{i}", tx=f"fast-tx-{i}"
                    )
                self._record(
                    "run", "trigger", chain_time=996, observed_at=997,
                    wallet="F5", tx="trigger-tx"
                )

                notification = PumpSwapLogNotification(
                    signature="trigger-tx",
                    slot=1,
                    observed_at=997,
                    trade_events=(
                        PumpSwapTradeEvent(
                            side="buy", pool="POOL", user="F5", timestamp=996,
                            base_amount_raw=1, quote_amount_raw=1, event_index=0
                        ),
                    ),
                )
                resolver = SimpleNamespace(acquisition_run_key="run")
                persisted = PumpSwapNormalizedPersistResult(0, 0, 0, 0, 0, 0)
                with patch(
                    "src.pumpswap_radar_bridge_v3.persist_pumpswap_notification_normalized",
                    new=AsyncMock(return_value=persisted),
                ) as persist_mock:
                    result = await process_pumpswap_notification_for_radar_v3(
                        notification,
                        acquisition_run_key="run",
                        resolver=resolver,
                    )

        persist_mock.assert_awaited_once()
        self.assertEqual(result.affected_tokens, ("TOKEN",))
        self.assertEqual(len(result.hits), 1)
        self.assertEqual(result.hits[0].episode.token_mint, "TOKEN")
        self.assertEqual(result.hits[0].episode.first_trigger_observed_at, 997)


if __name__ == "__main__":
    unittest.main()
