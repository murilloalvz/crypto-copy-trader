from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass

from src.pumpswap_ingress_prefetch_v49 import (
    PumpSwapIngressPrefetchV49,
    candidate_trade_pools_v49,
)
from src.pumpswap_stream import PumpSwapLogNotification


@dataclass(frozen=True)
class PrefetchSkippedV53:
    reason: str


@dataclass(frozen=True)
class OpportunisticPrefetchSnapshotV53:
    notifications_seen: int
    candidate_pools: int
    scheduled: int
    coalesced_inflight: int
    admitted: int
    skipped_capacity: int
    skipped_pool_busy: int
    completed_available: int
    completed_unresolved: int
    failed: int
    active: int


class OpportunisticPumpSwapIngressPrefetchV53(PumpSwapIngressPrefetchV49):
    """Never let speculative ingress prefetch queue behind authoritative resolution work.

    v49 prefetch is optional optimization only. v53 preserves cache reuse and same-pool coalescing,
    but a speculative task is admitted to the normal resolver only when the pool is not already
    resolving and the global expensive-resolution semaphore has immediate capacity. If either
    condition is false, the prefetch is skipped without touching negative cache, hydration budget,
    reservation state, detector state, or canonical persistence. The authoritative normalization
    path still calls ``resolver.resolve`` exactly as before.
    """

    last_instance: "OpportunisticPumpSwapIngressPrefetchV53 | None" = None

    def __init__(self) -> None:
        super().__init__()
        self._v53_counters: Counter[str] = Counter()
        OpportunisticPumpSwapIngressPrefetchV53.last_instance = self
        type(self).last_instance = self

    async def _resolve_one_opportunistic(
        self,
        *,
        resolver,
        pool_address: str,
        as_of: int,
    ):
        # Preserve the cheap causal-cache fast path even while network capacity is saturated.
        causal_cache_hit = getattr(resolver, "_causal_cache_hit", None)
        if callable(causal_cache_hit):
            cached = causal_cache_hit(pool_address, as_of=int(as_of))
            if cached is not None:
                self._v53_counters["admitted"] += 1
                return cached

        pool_locks = getattr(resolver, "_pool_locks", None)
        if isinstance(pool_locks, dict):
            active_lock = pool_locks.get(pool_address)
            if active_lock is not None and active_lock.locked():
                self._v53_counters["skipped_pool_busy"] += 1
                return PrefetchSkippedV53("pool_busy")

        semaphore = getattr(resolver, "_resolution_semaphore", None)
        if semaphore is not None and callable(getattr(semaphore, "locked", None)):
            if semaphore.locked():
                self._v53_counters["skipped_capacity"] += 1
                return PrefetchSkippedV53("capacity")

        # No await occurs between the immediate-capacity check above and the normal resolver's
        # acquisition of its free pool lock/semaphore on the same asyncio loop. Thus speculative
        # work never intentionally joins the semaphore wait queue. If the resolver implementation
        # lacks these introspection points, fail safe by using the unchanged v49 behavior.
        self._v53_counters["admitted"] += 1
        return await resolver.resolve(pool_address, as_of=int(as_of))

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
                return await self._resolve_one_opportunistic(
                    resolver=resolver,
                    pool_address=pool_address,
                    as_of=int(notification.observed_at),
                )

            task = asyncio.create_task(
                _resolve_one(),
                name=f"pumpswap-ingress-prefetch-v53:{pool[:12]}",
            )
            self._tasks_by_pool[pool] = task
            self._counters["scheduled"] += 1
            task.add_done_callback(
                lambda finished, pool_address=pool: self._completed_v53(
                    pool_address,
                    finished,
                )
            )

    def _completed_v53(self, pool: str, task: asyncio.Task) -> None:
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
            if isinstance(result, PrefetchSkippedV53):
                return
            if result is None:
                self._counters["completed_unresolved"] += 1
            else:
                self._counters["completed_available"] += 1

    def snapshot_v53(self) -> OpportunisticPrefetchSnapshotV53:
        base = self.snapshot()
        return OpportunisticPrefetchSnapshotV53(
            notifications_seen=base.notifications_seen,
            candidate_pools=base.candidate_pools,
            scheduled=base.scheduled,
            coalesced_inflight=base.coalesced_inflight,
            admitted=int(self._v53_counters["admitted"]),
            skipped_capacity=int(self._v53_counters["skipped_capacity"]),
            skipped_pool_busy=int(self._v53_counters["skipped_pool_busy"]),
            completed_available=base.completed_available,
            completed_unresolved=base.completed_unresolved,
            failed=base.failed,
            active=base.active,
        )
