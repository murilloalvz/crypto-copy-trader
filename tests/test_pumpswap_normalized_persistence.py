import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import load_market_trades
from src.pumpswap_asset_role import WSOL_MINT
from src.pumpswap_normalized_persistence import persist_pumpswap_notification_normalized
from src.pumpswap_pool_store import PumpSwapPoolMapping
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapTradeEvent


class FakeResolver:
    def __init__(self, mapping: PumpSwapPoolMapping):
        self.acquisition_run_key = mapping.acquisition_run_key
        self.mapping = mapping
        self.resolve_calls = 0

    async def resolve(self, pool_address: str, *, as_of: int):
        self.resolve_calls += 1
        return self.mapping

    def learn_from_create(self, event, *, observed_at: int):
        return self.mapping


class PumpSwapNormalizedPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_reversed_wsol_pool_persists_quote_token_and_inverts_buy(self):
        mapping = PumpSwapPoolMapping(
            acquisition_run_key="run",
            pool_address="POOL",
            base_mint=WSOL_MINT,
            quote_mint="TOKEN",
            observed_at=1000,
            source_provider="test",
        )
        resolver = FakeResolver(mapping)
        notification = PumpSwapLogNotification(
            signature="sig",
            slot=1,
            observed_at=1005,
            trade_events=(
                PumpSwapTradeEvent(
                    side="buy",
                    pool="POOL",
                    user="WALLET",
                    timestamp=1004,
                    base_amount_raw=10,
                    quote_amount_raw=20,
                    event_index=0,
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "normalized.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                result = await persist_pumpswap_notification_normalized(
                    notification,
                    acquisition_run_key="run",
                    resolver=resolver,
                )
                rows = load_market_trades(acquisition_run_key="run", token_mint="TOKEN")
                wsol_rows = load_market_trades(acquisition_run_key="run", token_mint=WSOL_MINT)

        self.assertEqual(result.newly_persisted_trades, 1)
        self.assertEqual(result.role_filtered_trades, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].observation.side, "sell")
        self.assertEqual(rows[0].observation.wallet_address, "WALLET")
        self.assertEqual(len(wsol_rows), 0)

    async def test_pair_without_reference_asset_is_filtered_not_unresolved(self):
        mapping = PumpSwapPoolMapping(
            acquisition_run_key="run",
            pool_address="POOL",
            base_mint="TOKEN-A",
            quote_mint="TOKEN-B",
            observed_at=1000,
            source_provider="test",
        )
        resolver = FakeResolver(mapping)
        notification = PumpSwapLogNotification(
            signature="sig-ambiguous",
            slot=1,
            observed_at=1005,
            trade_events=(
                PumpSwapTradeEvent(
                    side="sell",
                    pool="POOL",
                    user="WALLET",
                    timestamp=1004,
                    base_amount_raw=10,
                    quote_amount_raw=20,
                    event_index=0,
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ambiguous.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                result = await persist_pumpswap_notification_normalized(
                    notification,
                    acquisition_run_key="run",
                    resolver=resolver,
                )
                rows_a = load_market_trades(acquisition_run_key="run", token_mint="TOKEN-A")
                rows_b = load_market_trades(acquisition_run_key="run", token_mint="TOKEN-B")

        self.assertEqual(result.unresolved_trades, 0)
        self.assertEqual(result.role_filtered_trades, 1)
        self.assertEqual(result.newly_persisted_trades, 0)
        self.assertEqual(rows_a, [])
        self.assertEqual(rows_b, [])


if __name__ == "__main__":
    unittest.main()
