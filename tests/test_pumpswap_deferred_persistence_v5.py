import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import record_market_trade
from src.market_opportunity_radar import MarketTradeObservation
from src.pumpswap_asset_role import WSOL_MINT
from src.pumpswap_deferred_persistence_v5 import (
    DeferredPumpSwapPersistHandle,
    begin_pumpswap_notification_normalized_v5,
)
from src.pumpswap_normalized_persistence import PumpSwapNormalizedPersistResult
from src.pumpswap_pool_store import PumpSwapPoolMapping
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapTradeEvent
from unified_market_latency_smoke_v19 import _reservation_missing_assets


class _FakeResolver:
    def __init__(self, run_key: str):
        self.acquisition_run_key = run_key

    async def resolve(self, pool_address: str, *, as_of: int):
        return PumpSwapPoolMapping(
            acquisition_run_key=self.acquisition_run_key,
            pool_address=pool_address,
            base_mint="TOKEN",
            quote_mint=WSOL_MINT,
            observed_at=as_of,
            source_provider="test",
        )

    def learn_from_create(self, event, *, observed_at: int):
        raise AssertionError("test notification has no lifecycle events")


class _FakeWriter:
    def __init__(self):
        self.future = Future()
        self.prepared = None

    def enqueue(self, prepared):
        self.prepared = prepared
        return self.future


def _notification(signature: str = "sig-1") -> PumpSwapLogNotification:
    return PumpSwapLogNotification(
        signature=signature,
        slot=1,
        observed_at=1000,
        trade_events=(
            PumpSwapTradeEvent(
                side="buy",
                pool="POOL",
                user="wallet-A",
                timestamp=999,
                base_amount_raw=1,
                quote_amount_raw=1,
                event_index=0,
            ),
        ),
    )


def _result(*assets: str) -> PumpSwapNormalizedPersistResult:
    return PumpSwapNormalizedPersistResult(
        newly_persisted_trades=1,
        duplicate_or_replayed_trades=0,
        unresolved_trades=0,
        role_filtered_trades=0,
        newly_persisted_lifecycle=0,
        role_filtered_lifecycle=0,
        affected_tokens=tuple(assets),
    )


class PumpSwapDeferredPersistenceV5Tests(unittest.IsolatedAsyncioTestCase):
    async def test_handle_returns_before_writer_result_and_contains_incoming_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deferred-v5.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                writer = _FakeWriter()
                handle = await begin_pumpswap_notification_normalized_v5(
                    _notification(),
                    acquisition_run_key="run",
                    resolver=_FakeResolver("run"),
                    writer=writer,
                )
                self.assertEqual(handle.reservation_assets, ("TOKEN",))
                self.assertIsNotNone(writer.prepared)
                self.assertFalse(writer.future.done())

                expected = _result("TOKEN")
                writer.future.set_result(expected)
                observed = await handle.wait_result()

        self.assertEqual(observed, expected)

    async def test_reservation_assets_include_existing_canonical_transaction_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deferred-v5-existing.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_market_trade(
                    acquisition_run_key="run",
                    event_key="existing-event",
                    source_provider="test",
                    observation=MarketTradeObservation(
                        token_mint="EXISTING",
                        side="buy",
                        chain_time=998,
                        observed_at=999,
                        wallet_address="wallet-B",
                        venue="pumpswap",
                        transaction_key="sig-1",
                    ),
                )
                writer = _FakeWriter()
                handle = await begin_pumpswap_notification_normalized_v5(
                    _notification(),
                    acquisition_run_key="run",
                    resolver=_FakeResolver("run"),
                    writer=writer,
                )

        self.assertEqual(handle.reservation_assets, ("EXISTING", "TOKEN"))

    def test_missing_asset_guard_is_fail_closed(self):
        handle = DeferredPumpSwapPersistHandle(
            reservation_assets=("A", "B"),
            normalization_completed_monotonic=1.0,
            result_future=Future(),
        )
        self.assertEqual(_reservation_missing_assets(handle, _result("B")), ())
        self.assertEqual(_reservation_missing_assets(handle, _result("B", "C")), ("C",))


if __name__ == "__main__":
    unittest.main()
