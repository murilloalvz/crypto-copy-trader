from __future__ import annotations

import asyncio
import itertools
import time
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from src.pumpswap_eager_demoting_scheduler_v42 import (
    EagerDemotingReadyAssetSchedulerV42,
)
from src.pumpswap_ready_scheduler import ScheduledAssetWork


T = TypeVar("T")


@dataclass(frozen=True)
class StatefulPriorityQueueSnapshotV51:
    stateful_enqueued: int
    demoted_enqueued: int
    stateful_dequeued: int
    demoted_dequeued: int
    stateful_overtakes_demoted: int
    stateful_backlog_high_water: int
    demoted_backlog_high_water: int
    stateful_backlog: int
    demoted_backlog: int
    stateful_queue_wait_seconds: tuple[float, ...]
    demoted_queue_wait_seconds: tuple[float, ...]


class _StatefulPriorityReadyQueueV51(Generic[T]):
    """Stable priority queue: stateful-ready work before already-demoted audit work.

    The queue does not decide whether work is stateful. It trusts only the scheduler's
    existing v34 demotion acknowledgement, which is created after the per-asset stateful
    ticket has already been converted into a causal skip.
    """

    def __init__(
        self,
        *,
        is_demoted: Callable[[ScheduledAssetWork[T]], bool],
    ) -> None:
        self._queue: asyncio.PriorityQueue[tuple[int, int, ScheduledAssetWork[T]]] = (
            asyncio.PriorityQueue()
        )
        self._is_demoted = is_demoted
        self._counter = itertools.count()
        self._stateful_backlog = 0
        self._demoted_backlog = 0
        self._stateful_enqueued = 0
        self._demoted_enqueued = 0
        self._stateful_dequeued = 0
        self._demoted_dequeued = 0
        self._stateful_overtakes_demoted = 0
        self._stateful_backlog_high_water = 0
        self._demoted_backlog_high_water = 0
        self._stateful_waits: list[float] = []
        self._demoted_waits: list[float] = []

    def put_nowait(self, work: ScheduledAssetWork[T]) -> None:
        demoted = bool(self._is_demoted(work))
        priority = 1 if demoted else 0
        sequence = next(self._counter)
        if demoted:
            self._demoted_enqueued += 1
            self._demoted_backlog += 1
            self._demoted_backlog_high_water = max(
                self._demoted_backlog_high_water,
                self._demoted_backlog,
            )
        else:
            self._stateful_enqueued += 1
            self._stateful_backlog += 1
            self._stateful_backlog_high_water = max(
                self._stateful_backlog_high_water,
                self._stateful_backlog,
            )
        self._queue.put_nowait((priority, sequence, work))

    def _unwrap(
        self,
        item: tuple[int, int, ScheduledAssetWork[T]],
    ) -> ScheduledAssetWork[T]:
        priority, _, work = item
        now = time.monotonic()
        wait = max(0.0, now - work.ready_queue_entered_monotonic)
        if priority == 0:
            self._stateful_backlog = max(0, self._stateful_backlog - 1)
            self._stateful_dequeued += 1
            self._stateful_waits.append(wait)
            if self._demoted_backlog > 0:
                self._stateful_overtakes_demoted += 1
        else:
            self._demoted_backlog = max(0, self._demoted_backlog - 1)
            self._demoted_dequeued += 1
            self._demoted_waits.append(wait)
        return work

    async def get(self) -> ScheduledAssetWork[T]:
        return self._unwrap(await self._queue.get())

    def get_nowait(self) -> ScheduledAssetWork[T]:
        return self._unwrap(self._queue.get_nowait())

    def task_done(self) -> None:
        self._queue.task_done()

    def qsize(self) -> int:
        return self._queue.qsize()

    def empty(self) -> bool:
        return self._queue.empty()

    async def join(self) -> None:
        await self._queue.join()

    def snapshot(self) -> StatefulPriorityQueueSnapshotV51:
        return StatefulPriorityQueueSnapshotV51(
            stateful_enqueued=self._stateful_enqueued,
            demoted_enqueued=self._demoted_enqueued,
            stateful_dequeued=self._stateful_dequeued,
            demoted_dequeued=self._demoted_dequeued,
            stateful_overtakes_demoted=self._stateful_overtakes_demoted,
            stateful_backlog_high_water=self._stateful_backlog_high_water,
            demoted_backlog_high_water=self._demoted_backlog_high_water,
            stateful_backlog=self._stateful_backlog,
            demoted_backlog=self._demoted_backlog,
            stateful_queue_wait_seconds=tuple(self._stateful_waits),
            demoted_queue_wait_seconds=tuple(self._demoted_waits),
        )


class StatefulPriorityEagerDemotingReadyAssetSchedulerV51(
    EagerDemotingReadyAssetSchedulerV42[T],
    Generic[T],
):
    """v42 semantics with stateful-ready priority over proven continuation audits.

    v34/v42 already decides whether a pending job is safe to demote and consumes its
    stateful per-asset ticket as a causal skip. v51 changes only the order in which the
    *already-ready* finalizer consumer sees work: still-stateful ready work is selected
    before demoted audit-only work. FIFO remains stable within each class.
    """

    last_instance: "StatefulPriorityEagerDemotingReadyAssetSchedulerV51 | None" = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        def is_demoted(work: ScheduledAssetWork[T]) -> bool:
            key = self._reservation_key(work.reservation)
            return key in self._demoted_finalizer_acks

        # Replace only the ready-queue implementation. Every reservation, pending index,
        # completed cursor and demotion proof remains owned by the inherited v42/v34 code.
        self._ready = _StatefulPriorityReadyQueueV51(is_demoted=is_demoted)
        StatefulPriorityEagerDemotingReadyAssetSchedulerV51.last_instance = self
        type(self).last_instance = self

    def priority_snapshot(self) -> StatefulPriorityQueueSnapshotV51:
        return self._ready.snapshot()

    def is_demoted_work(self, work: ScheduledAssetWork[T]) -> bool:
        """Expose queue classification for observation-only tail attribution."""

        return self._reservation_key(work.reservation) in self._demoted_finalizer_acks
