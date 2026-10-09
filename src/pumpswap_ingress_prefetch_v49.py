from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from typing import AsyncIterator, Callable

from src.pumpswap_stream import PumpSwapLogNotification


@dataclass(frozen=True)
class PumpSwapIngressPrefetchSnapshotV49:
    notifications_seen: int
    candidate_pools: int
    scheduled: int
    coalesced_inflight: int
    completed_available: int
    completed_unresolved: int
    failed: int
    active: int


def candidate_trade_pools_v49(notification: PumpSwapLogNotification) -> tuple[str, ...]:
    """Return trade pools worth prefetching, preserving first appearance order.

    A pool created in the same notification is excluded because the causal CreatePool event
    already carries base/quote mint identity and normalization can learn it without RPC.
    """

    lifecycle_pools = {str(event.pool) for event in notification.lifecycle_events}
    seen: set[str] = set()
    pools: list[str] = []
    for event in notification.trade_events:
        pool = str(event.pool).strip()
        if not pool or pool in lifecycle_pools or pool in seen:
            continue
        seen.add(pool)
        pools.append(pool)
    return tuple(pools)


class PumpSwapIngressPrefetchV49:
    """Start immutable PumpSwap pool-identity resolution at stream ingress.

    This is scheduling only. The authoritative normalization/persistence path still calls the
    same resolver and therefore retains cache, historical reuse, per-pool single-flight,
    hydration budget, RPC hedging and explicit unresolved behavior. Prefetch does not create
    detector observations or reservations and cannot advance FIFO state by itself.
    """

    def __init__(self) -> None:
        self._counters: Counter[str] = Counter()
        self._tasks_by_pool: dict[str, asyncio.Task] = {}

    def schedule(self, notification: PumpSwapLogNotification, resolver) -> None:
        self._counters["notifications_seen"] += 1
        pools = candidate_trade_pools_v49(notification)
        self._counters["candidate_pools"] += len(pools)
        for pool in pools:
            active = self._tasks_by_pool.get(pool)
            if active is not None and not active.done():
                self._counters["coalesced_inflight"] += 1
                continue

            async def _resolve_one(*, pool_address: str = pool):
                return await resolver.resolve(
                    pool_address,
                    as_of=int(notification.observed_at),
                )

            task = asyncio.create_task(
                _resolve_one(),
                name=f"pumpswap-ingress-prefetch-v49:{pool[:12]}",
            )
            self._tasks_by_pool[pool] = task
            self._counters["scheduled"] += 1
            task.add_done_callback(
                lambda finished, pool_address=pool: self._completed(pool_address, finished)
            )

    def _completed(self, pool: str, task: asyncio.Task) -> None:
        current = self._tasks_by_pool.get(pool)
        if current is task:
            self._tasks_by_pool.pop(pool, None)
        try:
            result = task.result()
        except asyncio.CancelledError:
            self._counters["failed"] += 1
        except BaseException:
            self._counters["failed"] += 1
        else:
            if result is None:
                self._counters["completed_unresolved"] += 1
            else:
                self._counters["completed_available"] += 1

    async def drain(self, *, timeout_seconds: float) -> None:
        pending = tuple(task for task in self._tasks_by_pool.values() if not task.done())
        if not pending:
            return
        done, still_pending = await asyncio.wait(pending, timeout=max(0.0, timeout_seconds))
        # Do not cancel outstanding resolver work. Cancellation can release a per-pool lock while
        # the underlying blocking RPC still runs, allowing a duplicate hydration to start.
        for task in done:
            try:
                task.exception()
            except (asyncio.CancelledError, BaseException):
                pass
        if still_pending:
            self._counters["drain_timeout_pending"] += len(still_pending)

    def snapshot(self) -> PumpSwapIngressPrefetchSnapshotV49:
        return PumpSwapIngressPrefetchSnapshotV49(
            notifications_seen=self._counters["notifications_seen"],
            candidate_pools=self._counters["candidate_pools"],
            scheduled=self._counters["scheduled"],
            coalesced_inflight=self._counters["coalesced_inflight"],
            completed_available=self._counters["completed_available"],
            completed_unresolved=self._counters["completed_unresolved"],
            failed=self._counters["failed"],
            active=sum(1 for task in self._tasks_by_pool.values() if not task.done()),
        )


async def iter_pumpswap_with_ingress_prefetch_v49(
    *,
    base_factory,
    resolver_getter: Callable[[], object | None],
    prefetcher: PumpSwapIngressPrefetchV49,
    **stream_kwargs,
) -> AsyncIterator[PumpSwapLogNotification]:
    """Wrap the existing stream without changing notification content or order."""

    stream = base_factory(**stream_kwargs)
    try:
        async for notification in stream:
            resolver = resolver_getter()
            if resolver is not None:
                prefetcher.schedule(notification, resolver)
            yield notification
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()
