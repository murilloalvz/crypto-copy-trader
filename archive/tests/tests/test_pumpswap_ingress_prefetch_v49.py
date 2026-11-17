import asyncio

from src.pumpswap_ingress_prefetch_v49 import (
    PumpSwapIngressPrefetchV49,
    candidate_trade_pools_v49,
)
from src.pumpswap_stream import (
    PumpSwapCreatePoolEvent,
    PumpSwapLogNotification,
    PumpSwapTradeEvent,
)


def _trade(pool: str, *, event_index: int) -> PumpSwapTradeEvent:
    return PumpSwapTradeEvent(
        side="buy",
        pool=pool,
        user="user",
        timestamp=100,
        base_amount_raw=1,
        quote_amount_raw=2,
        event_index=event_index,
    )


def _create(pool: str) -> PumpSwapCreatePoolEvent:
    return PumpSwapCreatePoolEvent(
        pool=pool,
        creator="creator",
        base_mint="base",
        quote_mint="quote",
        base_mint_decimals=6,
        quote_mint_decimals=9,
        timestamp=100,
    )


def test_candidate_trade_pools_preserves_order_deduplicates_and_skips_same_notification_create():
    notification = PumpSwapLogNotification(
        signature="sig",
        slot=1,
        observed_at=101,
        trade_events=(
            _trade("pool-a", event_index=0),
            _trade("pool-b", event_index=1),
            _trade("pool-a", event_index=2),
            _trade("pool-c", event_index=3),
        ),
        lifecycle_events=(_create("pool-b"),),
    )
    assert candidate_trade_pools_v49(notification) == ("pool-a", "pool-c")


def test_prefetch_coalesces_same_pool_while_first_resolution_is_inflight():
    class Resolver:
        def __init__(self):
            self.calls = 0
            self.release = asyncio.Event()

        async def resolve(self, pool_address: str, *, as_of: int):
            self.calls += 1
            await self.release.wait()
            return object()

    async def scenario():
        resolver = Resolver()
        prefetch = PumpSwapIngressPrefetchV49()
        notification = PumpSwapLogNotification(
            signature="sig",
            slot=1,
            observed_at=101,
            trade_events=(_trade("pool-a", event_index=0),),
        )
        prefetch.schedule(notification, resolver)
        prefetch.schedule(notification, resolver)
        await asyncio.sleep(0)
        assert resolver.calls == 1
        snapshot = prefetch.snapshot()
        assert snapshot.scheduled == 1
        assert snapshot.coalesced_inflight == 1
        resolver.release.set()
        await prefetch.drain(timeout_seconds=1)
        await asyncio.sleep(0)
        snapshot = prefetch.snapshot()
        assert snapshot.completed_available == 1
        assert snapshot.active == 0

    asyncio.run(scenario())


def test_prefetch_records_unresolved_without_raising():
    class Resolver:
        async def resolve(self, pool_address: str, *, as_of: int):
            return None

    async def scenario():
        prefetch = PumpSwapIngressPrefetchV49()
        notification = PumpSwapLogNotification(
            signature="sig",
            slot=1,
            observed_at=101,
            trade_events=(_trade("pool-a", event_index=0),),
        )
        prefetch.schedule(notification, Resolver())
        await prefetch.drain(timeout_seconds=1)
        await asyncio.sleep(0)
        snapshot = prefetch.snapshot()
        assert snapshot.completed_unresolved == 1
        assert snapshot.failed == 0

    asyncio.run(scenario())
