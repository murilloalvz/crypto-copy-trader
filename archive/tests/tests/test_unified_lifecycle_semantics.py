import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import record_market_lifecycle, record_market_trade
from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation
from src.market_radar_bridge import evaluate_market_token


class UnifiedLifecycleSemanticsTests(unittest.TestCase):
    def test_latest_pumpswap_pool_create_does_not_replace_pump_token_birth(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unified.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_market_lifecycle(
                    acquisition_run_key="run",
                    event_key="pump-create",
                    source_provider="pump",
                    observation=MarketLifecycleObservation(
                        token_mint="TOKEN",
                        market_started_at=100,
                        observed_at=101,
                        venue="pump_bonding_curve",
                    ),
                )
                record_market_lifecycle(
                    acquisition_run_key="run",
                    event_key="pumpswap-pool-create",
                    source_provider="pumpswap",
                    observation=MarketLifecycleObservation(
                        token_mint="TOKEN",
                        market_started_at=930,
                        observed_at=935,
                        venue="pump_swap",
                    ),
                )
                for i in range(6):
                    record_market_trade(
                        acquisition_run_key="run",
                        event_key=f"trade-{i}",
                        source_provider="test",
                        observation=MarketTradeObservation(
                            token_mint="TOKEN",
                            side="buy",
                            chain_time=975 + i * 4,
                            observed_at=976 + i * 4,
                            wallet_address=f"W{i}",
                            venue="pump_swap",
                            transaction_key=f"tx-{i}",
                        ),
                    )
                hit = evaluate_market_token(
                    acquisition_run_key="run",
                    token_mint="TOKEN",
                    as_of=1000,
                    trigger_key="trigger",
                    trigger_chain_time=995,
                    venue="pump_bonding_curve",
                )

        # The true Pump token birth is 900 seconds old, so the recent PumpSwap pool creation
        # cannot unlock the fresh_market_burst escape hatch. With no baseline, no hit is valid.
        self.assertIsNone(hit)


if __name__ == "__main__":
    unittest.main()
