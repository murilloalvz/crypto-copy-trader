from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass
import threading
import time

from src.pumpswap_deadline_hedged_resolver_v52 import (
    DeadlineBoundedParallelHedgedResolverV52,
)


def _caller_class() -> str:
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    name = task.get_name() if task is not None else ""
    return "prefetch" if name.startswith("pumpswap-ingress-prefetch") else "demand"


@dataclass(frozen=True)
class ResolverWaitSnapshotV53:
    demand_resolve_seconds: tuple[float, ...]
    prefetch_resolve_seconds: tuple[float, ...]
    demand_pool_lock_wait_seconds: tuple[float, ...]
    prefetch_pool_lock_wait_seconds: tuple[float, ...]
    demand_capacity_wait_seconds: tuple[float, ...]
    prefetch_capacity_wait_seconds: tuple[float, ...]
    pool_lock_waits: int
    capacity_waits: int
    demand_capacity_waiters_high_water: int
    prefetch_capacity_waiters_high_water: int
    hot_pool_lock_wait_seconds: tuple[tuple[str, float, int], ...]


class _TimedLockV53:
    def __init__(self, *, pool: str, telemetry: "TracedDeadlineBoundedResolverV53") -> None:
        self._inner = asyncio.Lock()
        self._pool = pool
        self._telemetry = telemetry

    def locked(self) -> bool:
        return self._inner.locked()

    async def acquire(self) -> bool:
        caller = _caller_class()
        started = time.monotonic()
        was_locked = self._inner.locked()
        acquired = await self._inner.acquire()
        waited = max(0.0, time.monotonic() - started)
        self._telemetry._record_pool_lock_wait(
            caller=caller,
            pool=self._pool,
            seconds=waited,
            actually_waited=was_locked,
        )
        return acquired

    def release(self) -> None:
        self._inner.release()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.release()


class _TimedPoolLockDictV53(dict):
    def __init__(self, telemetry: "TracedDeadlineBoundedResolverV53") -> None:
        super().__init__()
        self._telemetry = telemetry

    def setdefault(self, key, default=None):
        normalized = str(key)
        existing = self.get(normalized)
        if existing is not None:
            return existing
        lock = _TimedLockV53(pool=normalized, telemetry=self._telemetry)
        self[normalized] = lock
        return lock


class _TimedSemaphoreV53:
    def __init__(
        self,
        inner: asyncio.Semaphore,
        telemetry: "TracedDeadlineBoundedResolverV53",
    ) -> None:
        self._inner = inner
        self._telemetry = telemetry

    def locked(self) -> bool:
        return self._inner.locked()

    async def acquire(self) -> bool:
        caller = _caller_class()
        started = time.monotonic()
        was_locked = self._inner.locked()
        self._telemetry._capacity_waiter_enter(caller, was_locked=was_locked)
        try:
            acquired = await self._inner.acquire()
        finally:
            self._telemetry._capacity_waiter_leave(caller, was_locked=was_locked)
        waited = max(0.0, time.monotonic() - started)
        self._telemetry._record_capacity_wait(
            caller=caller,
            seconds=waited,
            actually_waited=was_locked,
        )
        return acquired

    def release(self) -> None:
        self._inner.release()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.release()


class TracedDeadlineBoundedResolverV53(DeadlineBoundedParallelHedgedResolverV52):
    """Observational v53 resolver wrapper around the unchanged authoritative resolve path.

    The parent ``resolve`` implementation is not replaced. v53 only wraps the already-existing
    per-pool locks and global resolution semaphore to measure where authoritative normalization
    waits, plus total resolver latency split between ingress prefetch and demand normalization.
    """

    last_instance: "TracedDeadlineBoundedResolverV53 | None" = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._v53_metrics_lock = threading.Lock()
        self._v53_timings: dict[str, list[float]] = defaultdict(list)
        self._v53_counts: Counter[str] = Counter()
        self._v53_capacity_waiters: Counter[str] = Counter()
        self._v53_capacity_waiters_high_water: Counter[str] = Counter()
        self._v53_pool_wait_total: dict[str, float] = defaultdict(float)
        self._v53_pool_wait_count: Counter[str] = Counter()

        # No resolver work has started yet when __init__ returns. Replacing these synchronization
        # primitives with behaviorally equivalent wrappers is therefore observational only.
        original_semaphore = self._resolution_semaphore
        self._resolution_semaphore = _TimedSemaphoreV53(original_semaphore, self)
        self._pool_locks = _TimedPoolLockDictV53(self)
        TracedDeadlineBoundedResolverV53.last_instance = self
        type(self).last_instance = self

    def _record_pool_lock_wait(
        self,
        *,
        caller: str,
        pool: str,
        seconds: float,
        actually_waited: bool,
    ) -> None:
        with self._v53_metrics_lock:
            self._v53_timings[f"{caller}_pool_lock_wait"].append(seconds)
            if actually_waited:
                self._v53_counts["pool_lock_waits"] += 1
                self._v53_pool_wait_total[pool] += seconds
                self._v53_pool_wait_count[pool] += 1

    def _capacity_waiter_enter(self, caller: str, *, was_locked: bool) -> None:
        if not was_locked:
            return
        with self._v53_metrics_lock:
            self._v53_capacity_waiters[caller] += 1
            self._v53_capacity_waiters_high_water[caller] = max(
                self._v53_capacity_waiters_high_water[caller],
                self._v53_capacity_waiters[caller],
            )

    def _capacity_waiter_leave(self, caller: str, *, was_locked: bool) -> None:
        if not was_locked:
            return
        with self._v53_metrics_lock:
            self._v53_capacity_waiters[caller] = max(
                0,
                self._v53_capacity_waiters[caller] - 1,
            )

    def _record_capacity_wait(
        self,
        *,
        caller: str,
        seconds: float,
        actually_waited: bool,
    ) -> None:
        with self._v53_metrics_lock:
            self._v53_timings[f"{caller}_capacity_wait"].append(seconds)
            if actually_waited:
                self._v53_counts["capacity_waits"] += 1

    async def resolve(self, pool_address: str, *, as_of: int):
        caller = _caller_class()
        started = time.monotonic()
        try:
            return await super().resolve(pool_address, as_of=as_of)
        finally:
            elapsed = max(0.0, time.monotonic() - started)
            with self._v53_metrics_lock:
                self._v53_timings[f"{caller}_resolve"].append(elapsed)

    def resolver_wait_snapshot_v53(self) -> ResolverWaitSnapshotV53:
        with self._v53_metrics_lock:
            hot = sorted(
                (
                    (pool, total, int(self._v53_pool_wait_count[pool]))
                    for pool, total in self._v53_pool_wait_total.items()
                ),
                key=lambda item: (-item[1], item[0]),
            )[:10]
            return ResolverWaitSnapshotV53(
                demand_resolve_seconds=tuple(self._v53_timings["demand_resolve"]),
                prefetch_resolve_seconds=tuple(self._v53_timings["prefetch_resolve"]),
                demand_pool_lock_wait_seconds=tuple(
                    self._v53_timings["demand_pool_lock_wait"]
                ),
                prefetch_pool_lock_wait_seconds=tuple(
                    self._v53_timings["prefetch_pool_lock_wait"]
                ),
                demand_capacity_wait_seconds=tuple(
                    self._v53_timings["demand_capacity_wait"]
                ),
                prefetch_capacity_wait_seconds=tuple(
                    self._v53_timings["prefetch_capacity_wait"]
                ),
                pool_lock_waits=int(self._v53_counts["pool_lock_waits"]),
                capacity_waits=int(self._v53_counts["capacity_waits"]),
                demand_capacity_waiters_high_water=int(
                    self._v53_capacity_waiters_high_water["demand"]
                ),
                prefetch_capacity_waiters_high_water=int(
                    self._v53_capacity_waiters_high_water["prefetch"]
                ),
                hot_pool_lock_wait_seconds=tuple(hot),
            )
