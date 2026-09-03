import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src import database
from src.market_observation_store import count_market_replay_conflicts, load_market_trades
from src.pumpswap_normalized_persistence import persist_pumpswap_notification_normalized
from src.pumpswap_pool_store import PumpSwapPoolIdentity
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapTradeEvent


class PumpSwapReplayIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_conflicting_normalization_is_audited_without_crashing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "market.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                resolver = AsyncMock()
                resolver.acquisition_run_key = "run"
                resolver.resolve.side_effect = [
                    PumpSwapPoolIdentity("POOL", "So11111111111111111111111111111111111111112", "TOKEN_A", 100),
                    PumpSwapPoolIdentity("POOL", "So11111111111111111111111111111111111111112", "TOKEN_B", 100),
                ]
                resolver.learn_from_create = AsyncMock()
                event = PumpSwapTradeEvent(
                    pool="POOL",
                    side="buy",
                    base_amount=1,
                    quote_amount=1,
                    user="W",
                    timestamp=100,
                    event_index=0,
                )
                first = PumpSwapLogNotification("sig", 1, 110, (event,), ())
                second = PumpSwapLogNotification("sig", 1, 115, (event,), ())

                await persist_pumpswap_notification_normalized(
                    first, acquisition_run_key="run", resolver=resolver
                )
                await persist_pumpswap_notification_normalized(
                    second, acquisition_run_key="run", resolver=resolver
                )

                rows_a = load_market_trades(acquisition_run_key="run", token_mint="TOKEN_A")
                rows_b = load_market_trades(acquisition_run_key="run", token_mint="TOKEN_B")
                conflicts = count_market_replay_conflicts(acquisition_run_key="run")

        self.assertEqual(len(rows_a), 1)
        self.assertEqual(rows_b, ())
        self.assertEqual(conflicts, 1)


if __name__ == "__main__":
    unittest.main()
