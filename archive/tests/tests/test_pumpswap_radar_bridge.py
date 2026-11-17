import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import record_market_lifecycle, record_market_trade
from src.market_opportunity_radar import MarketLifecycleObservation, MarketRadarConfig, MarketTradeObservation
from src.pumpswap_radar_bridge import _evaluate_pumpswap_token


class PumpSwapRadarBridgeTests(unittest.TestCase):
    def _record_trade(self, run_key: str, index: int, *, chain_time: int, wallet: str) -> None:
        record_market_trade(
            acquisition_run_key=run_key,
            event_key=f"event-{index}",
            source_provider="test",
            observation=MarketTradeObservation(
                token_mint="TOKEN",
                side="buy",
                chain_time=chain_time,
                observed_at=chain_time + 1,
                wallet_address=wallet,
                venue="pump_swap",
                transaction_key=f"tx-{index}",
            ),
        )

    def test_pumpswap_pool_creation_does_not_fake_fresh_token_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_market_lifecycle(
                    acquisition_run_key="run",
                    event_key="pool-create",
                    source_provider="pumpswap",
                    observation=MarketLifecycleObservation(
                        token_mint="TOKEN",
                        market_started_at=930,
                        observed_at=935,
                        venue="pump_swap",
                    ),
                )
                for i in range(6):
                    self._record_trade("run", i, chain_time=975 + i * 4, wallet=f"W{i}")
                hit = _evaluate_pumpswap_token(
                    acquisition_run_key="run",
                    token_mint="TOKEN",
                    as_of=1000,
                    trigger_key="trigger",
                    trigger_chain_time=995,
                    config=MarketRadarConfig(),
                )
        self.assertIsNone(hit)

    def test_pumpswap_established_acceleration_can_open_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                for i in range(3):
                    self._record_trade("run", i, chain_time=800, wallet=f"B{i}")
                for i in range(6):
                    self._record_trade("run", 10 + i, chain_time=975 + i * 4, wallet=f"F{i}")
                hit = _evaluate_pumpswap_token(
                    acquisition_run_key="run",
                    token_mint="TOKEN",
                    as_of=1000,
                    trigger_key="trigger",
                    trigger_chain_time=995,
                    config=MarketRadarConfig(),
                )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.trigger.trigger_kind, "activity_acceleration")
        self.assertEqual(hit.episode.token_mint, "TOKEN")


if __name__ == "__main__":
    unittest.main()
