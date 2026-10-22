import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import load_market_trades
from src.pumpswap_asset_role import WSOL_MINT
from src.pumpswap_normalized_persistence import persist_pumpswap_notification_normalized
from src.pumpswap_normalized_persistence_v3 import (
    PumpSwapSQLiteMicrobatchWriter,
    persist_pumpswap_notification_normalized_v3,
)
from src.pumpswap_pool_store import PumpSwapPoolMapping
from src.pumpswap_stream import PumpSwapLogNotification, PumpSwapTradeEvent


class _MappingResolver:
    def __init__(self, run_key: str, token_by_pool: dict[str, str]):
        self.acquisition_run_key = run_key
        self.token_by_pool = dict(token_by_pool)

    async def resolve(self, pool_address: str, *, as_of: int):
        return PumpSwapPoolMapping(
            acquisition_run_key=self.acquisition_run_key,
            pool_address=pool_address,
            base_mint=self.token_by_pool[pool_address],
            quote_mint=WSOL_MINT,
            observed_at=as_of,
            source_provider="test",
        )

    def learn_from_create(self, event, *, observed_at: int):
        raise AssertionError("test notification has no lifecycle events")


def _notification(
    *,
    signature: str,
    pool: str,
    observed_at: int,
    side: str = "buy",
) -> PumpSwapLogNotification:
    return PumpSwapLogNotification(
        signature=signature,
        slot=1,
        observed_at=observed_at,
        trade_events=(
            PumpSwapTradeEvent(
                side=side,
                pool=pool,
                user="wallet-A",
                timestamp=observed_at - 1,
                base_amount_raw=1,
                quote_amount_raw=1,
                event_index=0,
            ),
        ),
    )


class PumpSwapNormalizedPersistenceV3Tests(unittest.IsolatedAsyncioTestCase):
    async def test_microbatch_matches_legacy_conflicting_replay_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "normalized-v3.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                later = _notification(
                    signature="same-sig",
                    pool="POOL-OLD",
                    observed_at=1100,
                )
                earlier = _notification(
                    signature="same-sig",
                    pool="POOL-NEW",
                    observed_at=1050,
                )
                mapping = {"POOL-OLD": "OLD", "POOL-NEW": "NEW"}

                legacy_resolver = _MappingResolver("legacy", mapping)
                legacy_first = await persist_pumpswap_notification_normalized(
                    later,
                    acquisition_run_key="legacy",
                    resolver=legacy_resolver,
                )
                legacy_second = await persist_pumpswap_notification_normalized(
                    earlier,
                    acquisition_run_key="legacy",
                    resolver=legacy_resolver,
                )

                telemetry = []
                writer = PumpSwapSQLiteMicrobatchWriter(
                    batch_size=8,
                    max_wait_ms=25,
                    telemetry_sink=telemetry.append,
                )
                current_resolver = _MappingResolver("current", mapping)
                current_first, current_second = await asyncio.gather(
                    persist_pumpswap_notification_normalized_v3(
                        later,
                        acquisition_run_key="current",
                        resolver=current_resolver,
                        writer=writer,
                    ),
                    persist_pumpswap_notification_normalized_v3(
                        earlier,
                        acquisition_run_key="current",
                        resolver=current_resolver,
                        writer=writer,
                    ),
                )
                await writer.close(cancel_pending=False)

                legacy_old = load_market_trades(
                    acquisition_run_key="legacy",
                    token_mint="OLD",
                )
                legacy_new = load_market_trades(
                    acquisition_run_key="legacy",
                    token_mint="NEW",
                )
                current_old = load_market_trades(
                    acquisition_run_key="current",
                    token_mint="OLD",
                )
                current_new = load_market_trades(
                    acquisition_run_key="current",
                    token_mint="NEW",
                )

        self.assertEqual(legacy_first, current_first)
        self.assertEqual(legacy_second, current_second)
        self.assertEqual(legacy_old, ())
        self.assertEqual(current_old, ())
        self.assertEqual(len(legacy_new), 1)
        self.assertEqual(len(current_new), 1)
        self.assertEqual(legacy_new[0].observation, current_new[0].observation)
        self.assertEqual(current_new[0].observation.observed_at, 1050)
        self.assertEqual(current_new[0].observation.side, "buy")
        self.assertEqual(len(telemetry), 2)
        self.assertEqual(writer.batch_sizes, [2])
        self.assertTrue(all(item.writer_batch_size == 2 for item in telemetry))

    async def test_many_submissions_are_committed_in_fewer_batches(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "microbatch-throughput.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                mapping = {f"POOL-{index}": f"TOKEN-{index}" for index in range(12)}
                resolver = _MappingResolver("run", mapping)
                telemetry = []
                writer = PumpSwapSQLiteMicrobatchWriter(
                    batch_size=12,
                    max_wait_ms=25,
                    telemetry_sink=telemetry.append,
                )
                results = await asyncio.gather(
                    *(
                        persist_pumpswap_notification_normalized_v3(
                            _notification(
                                signature=f"sig-{index}",
                                pool=f"POOL-{index}",
                                observed_at=1000 + index,
                            ),
                            acquisition_run_key="run",
                            resolver=resolver,
                            writer=writer,
                        )
                        for index in range(12)
                    )
                )
                await writer.close(cancel_pending=False)

        self.assertEqual(len(results), 12)
        self.assertTrue(all(item.newly_persisted_trades == 1 for item in results))
        self.assertLess(len(writer.batch_sizes), len(results))
        self.assertEqual(sum(writer.batch_sizes), len(results))
        self.assertEqual(len(telemetry), len(results))
        self.assertTrue(all(item.writer_queue_wait_seconds >= 0.0 for item in telemetry))
        self.assertTrue(all(item.writer_result_wait_seconds >= 0.0 for item in telemetry))


if __name__ == "__main__":
    unittest.main()
