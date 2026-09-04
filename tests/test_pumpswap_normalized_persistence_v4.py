import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_transaction_view import load_market_trades_by_transaction
from src.pumpswap_asset_role import WSOL_MINT
from src.pumpswap_normalized_persistence import PumpSwapNormalizedPersistResult
from src.pumpswap_normalized_persistence_v3 import PreparedPumpSwapPersistenceV3
from src.pumpswap_normalized_persistence_v4 import (
    PumpSwapSQLiteThreadedMicrobatchWriter,
    persist_pumpswap_notification_normalized_v4,
)
from src.pumpswap_pool_store import PumpSwapPoolMapping
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapTradeEvent


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


class PumpSwapNormalizedPersistenceV4Tests(unittest.IsolatedAsyncioTestCase):
    async def test_thread_owned_writer_persists_same_canonical_trade(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "normalized-v4.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                telemetry = []
                writer = PumpSwapSQLiteThreadedMicrobatchWriter(
                    batch_size=8,
                    max_wait_ms=5,
                    telemetry_sink=telemetry.append,
                )
                result = await persist_pumpswap_notification_normalized_v4(
                    _notification(),
                    acquisition_run_key="run",
                    resolver=_FakeResolver("run"),
                    writer=writer,
                )
                await writer.close(cancel_pending=False)
                rows = load_market_trades_by_transaction(
                    acquisition_run_key="run",
                    transaction_key="sig-1",
                )

        self.assertEqual(result.newly_persisted_trades, 1)
        self.assertEqual(result.duplicate_or_replayed_trades, 0)
        self.assertEqual(result.affected_tokens, ("TOKEN",))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].observation.token_mint, "TOKEN")
        self.assertEqual(len(telemetry), 1)
        self.assertEqual(writer.batch_sizes, [1])

    async def test_writer_keeps_draining_while_event_loop_is_blocked(self):
        thread_names: list[str] = []

        def fake_stage(prepared_items):
            thread_names.append(threading.current_thread().name)
            started = time.perf_counter()
            results = tuple(
                PumpSwapNormalizedPersistResult(
                    newly_persisted_trades=0,
                    duplicate_or_replayed_trades=0,
                    unresolved_trades=0,
                    role_filtered_trades=0,
                    newly_persisted_lifecycle=0,
                    role_filtered_lifecycle=0,
                    affected_tokens=(),
                )
                for _ in prepared_items
            )
            return results, started, time.perf_counter()

        prepared = tuple(
            PreparedPumpSwapPersistenceV3(
                acquisition_run_key="run",
                transaction_key=f"sig-{index}",
                lifecycle_writes=(),
                trade_writes=(),
                unresolved_trades=0,
                role_filtered_trades=0,
                role_filtered_lifecycle=0,
                resolver_and_normalize_seconds=0.0,
            )
            for index in range(16)
        )

        with patch(
            "src.pumpswap_normalized_persistence_v4._persist_prepared_batch_db_stage",
            side_effect=fake_stage,
        ):
            writer = PumpSwapSQLiteThreadedMicrobatchWriter(
                batch_size=8,
                max_wait_ms=1,
            )
            futures = [writer.enqueue(item) for item in prepared]

            # Deliberately block the asyncio thread. The writer must still form batches
            # and finish work because its scheduling loop is owned by another OS thread.
            time.sleep(0.05)

            self.assertTrue(all(future.done() for future in futures))
            self.assertTrue(
                all(
                    name.startswith("pumpswap-sqlite-threaded-microbatch-writer")
                    for name in thread_names
                )
            )
            self.assertEqual(sum(writer.batch_sizes), len(prepared))
            self.assertLessEqual(max(writer.batch_sizes), 8)
            await writer.close(cancel_pending=False)


if __name__ == "__main__":
    unittest.main()
