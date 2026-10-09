import asyncio
from concurrent.futures import ThreadPoolExecutor
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_transaction_view import load_market_trades_by_transaction
from src.pumpswap_asset_role import WSOL_MINT
from src.pumpswap_normalized_persistence import persist_pumpswap_notification_normalized
from src.pumpswap_normalized_persistence_v2 import persist_pumpswap_notification_normalized_v2
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


def _notification() -> PumpSwapLogNotification:
    return PumpSwapLogNotification(
        signature="sig-1",
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


class PumpSwapNormalizedPersistenceV2Tests(unittest.TestCase):
    def test_v2_matches_legacy_normalized_persistence_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "normalized-v2.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                legacy = asyncio.run(
                    persist_pumpswap_notification_normalized(
                        _notification(),
                        acquisition_run_key="legacy",
                        resolver=_FakeResolver("legacy"),
                    )
                )

                telemetry = []
                with ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="test-pumpswap-writer",
                ) as executor:
                    current = asyncio.run(
                        persist_pumpswap_notification_normalized_v2(
                            _notification(),
                            acquisition_run_key="current",
                            resolver=_FakeResolver("current"),
                            db_executor=executor,
                            telemetry_sink=telemetry.append,
                        )
                    )

                legacy_rows = load_market_trades_by_transaction(
                    acquisition_run_key="legacy",
                    transaction_key="sig-1",
                )
                current_rows = load_market_trades_by_transaction(
                    acquisition_run_key="current",
                    transaction_key="sig-1",
                )

        self.assertEqual(legacy, current)
        self.assertEqual(len(legacy_rows), 1)
        self.assertEqual(len(current_rows), 1)
        self.assertEqual(legacy_rows[0].observation, current_rows[0].observation)
        self.assertEqual(len(telemetry), 1)
        self.assertGreaterEqual(telemetry[0].writer_queue_wait_seconds, 0.0)
        self.assertGreaterEqual(telemetry[0].writer_service_seconds, 0.0)

    def test_db_stage_runs_on_supplied_writer_executor(self):
        thread_names: list[str] = []

        def fake_stage(**kwargs):
            thread_names.append(threading.current_thread().name)
            return (0, 0, 0, (), 0.0, 0.0)

        notification = PumpSwapLogNotification(
            signature="empty-sig",
            slot=1,
            observed_at=1000,
            trade_events=(),
        )
        with patch(
            "src.pumpswap_normalized_persistence_v2._persist_db_stage",
            side_effect=fake_stage,
        ):
            with ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="test-pumpswap-writer",
            ) as executor:
                result = asyncio.run(
                    persist_pumpswap_notification_normalized_v2(
                        notification,
                        acquisition_run_key="run",
                        resolver=_FakeResolver("run"),
                        db_executor=executor,
                    )
                )

        self.assertEqual(result.newly_persisted_trades, 0)
        self.assertEqual(len(thread_names), 1)
        self.assertTrue(thread_names[0].startswith("test-pumpswap-writer"))


if __name__ == "__main__":
    unittest.main()
