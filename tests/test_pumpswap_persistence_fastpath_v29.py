import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import load_market_trades
from src.pumpswap_asset_role import WSOL_MINT
from src.pumpswap_normalized_persistence_v3 import (
    _persist_prepared_batch_db_stage,
    prepare_pumpswap_notification_normalized_v3,
)
from src.pumpswap_persistence_fastpath_v29 import (
    persist_prepared_batch_fast_v29,
    pumpswap_persistence_fastpath_snapshot,
    reset_pumpswap_persistence_fastpath_metrics,
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


def _notification(*, signature: str, pool: str, observed_at: int) -> PumpSwapLogNotification:
    return PumpSwapLogNotification(
        signature=signature,
        slot=1,
        observed_at=observed_at,
        trade_events=(
            PumpSwapTradeEvent(
                side="buy",
                pool=pool,
                user="wallet-A",
                timestamp=observed_at - 1,
                base_amount_raw=1,
                quote_amount_raw=1,
                event_index=0,
            ),
        ),
    )


class PumpSwapPersistenceFastPathV29Tests(unittest.IsolatedAsyncioTestCase):
    async def _prepare(self, *, run_key: str, notification, mapping):
        resolver = _MappingResolver(run_key, mapping)
        return await prepare_pumpswap_notification_normalized_v3(
            notification,
            acquisition_run_key=run_key,
            resolver=resolver,
        )

    async def test_conflicting_replay_matches_existing_batch_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fast-v29.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                mapping = {"POOL-OLD": "OLD", "POOL-NEW": "NEW"}
                later = _notification(signature="same", pool="POOL-OLD", observed_at=1100)
                earlier = _notification(signature="same", pool="POOL-NEW", observed_at=1050)

                legacy_items = (
                    await self._prepare(run_key="legacy", notification=later, mapping=mapping),
                    await self._prepare(run_key="legacy", notification=earlier, mapping=mapping),
                )
                legacy_results, _, _ = _persist_prepared_batch_db_stage(legacy_items)

                fast_items = (
                    await self._prepare(run_key="fast", notification=later, mapping=mapping),
                    await self._prepare(run_key="fast", notification=earlier, mapping=mapping),
                )
                reset_pumpswap_persistence_fastpath_metrics()
                fast_results, _, _ = persist_prepared_batch_fast_v29(fast_items)
                snapshot = pumpswap_persistence_fastpath_snapshot()

                legacy_new = load_market_trades(acquisition_run_key="legacy", token_mint="NEW")
                fast_new = load_market_trades(acquisition_run_key="fast", token_mint="NEW")
                fast_old = load_market_trades(acquisition_run_key="fast", token_mint="OLD")

        self.assertEqual(legacy_results, fast_results)
        self.assertEqual(len(legacy_new), 1)
        self.assertEqual(len(fast_new), 1)
        self.assertEqual(fast_old, ())
        self.assertEqual(fast_new[0].observation.observed_at, 1050)
        self.assertEqual(snapshot.trade_insert_attempts, 2)
        self.assertEqual(snapshot.trade_collision_reads, 1)
        self.assertEqual(snapshot.affected_token_batch_readbacks, 1)

    async def test_new_rows_skip_replay_reads_and_share_one_batch_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fast-v29-new.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                mapping = {f"POOL-{index}": f"TOKEN-{index}" for index in range(20)}
                items = tuple(
                    [
                        await self._prepare(
                            run_key="run",
                            notification=_notification(
                                signature=f"sig-{index}",
                                pool=f"POOL-{index}",
                                observed_at=1000 + index,
                            ),
                            mapping=mapping,
                        )
                        for index in range(20)
                    ]
                )
                reset_pumpswap_persistence_fastpath_metrics()
                results, _, _ = persist_prepared_batch_fast_v29(items)
                snapshot = pumpswap_persistence_fastpath_snapshot()

        self.assertTrue(all(result.newly_persisted_trades == 1 for result in results))
        self.assertEqual(snapshot.prepared_items, 20)
        self.assertEqual(snapshot.trade_insert_attempts, 20)
        self.assertEqual(snapshot.trade_collision_reads, 0)
        self.assertEqual(snapshot.affected_token_batch_readbacks, 1)


if __name__ == "__main__":
    unittest.main()
