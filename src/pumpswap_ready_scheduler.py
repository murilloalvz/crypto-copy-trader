from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class AssetReservation:
    tickets: tuple[tuple[str, int], ...]

    @property
    def assets(self) -> tuple[str, ...]:
        return tuple(asset for asset, _ in self.tickets)


@dataclass(frozen=True)
class ScheduledAssetWork(Generic[T]):
    payload: T
    reservation: AssetReservation


class ReadyAssetScheduler(Generic[T]):
    """Ingress-ordered per-asset FIFO scheduler that never spends execution slots waiting.

    `reserve()` is called by one dispatcher in websocket ingress order. `submit()` creates a waiter
    task for the reservation. The waiter consumes no execution semaphore capacity while earlier
    tickets for one of its assets remain outstanding. Only once every predecessor has completed is
    the payload placed on the ready queue, where bounded radar workers can execute it.

    Multi-asset reservations are safe because all ticket relations are induced by one global
    ingress order, so the dependency graph is acyclic.
    """

    def __init__(self) -> None:
        self._issued: dict[str, int] = {}
        self._completed: dict[str, int] = {}
        self._condition = asyncio.Condition()
        self._ready: asyncio.Queue[ScheduledAssetWork[T]] = asyncio.Queue()
        self._waiters: set[asyncio.Task[None]] = set()

    def reserve(self, assets: tuple[str, ...] | list[str]) -> AssetReservation:
        unique_assets = tuple(sorted({str(asset).strip() for asset in assets if str(asset).strip()}))
        tickets: list[tuple[str, int]] = []
        for asset in unique_assets:
            ticket = self._issued.get(asset, 0)
            self._issued[asset] = ticket + 1
            tickets.append((asset, ticket))
        return AssetReservation(tuple(tickets))

    def submit(self, payload: T, reservation: AssetReservation) -> None:
        task = asyncio.create_task(self._wait_until_ready(payload, reservation))
        self._waiters.add(task)
        task.add_done_callback(self._waiters.discard)

    async def _wait_until_ready(self, payload: T, reservation: AssetReservation) -> None:
        async with self._condition:
            await self._condition.wait_for(
                lambda: all(
                    self._completed.get(asset, 0) == ticket
                    for asset, ticket in reservation.tickets
                )
            )
        await self._ready.put(ScheduledAssetWork(payload, reservation))

    async def get_ready(self) -> ScheduledAssetWork[T]:
        return await self._ready.get()

    def ready_task_done(self) -> None:
        self._ready.task_done()

    async def complete(self, reservation: AssetReservation) -> None:
        async with self._condition:
            for asset, ticket in reservation.tickets:
                current = self._completed.get(asset, 0)
                if current != ticket:
                    raise RuntimeError(
                        f"asset order completion mismatch for {asset}: expected {current}, got {ticket}"
                    )
            for asset, ticket in reservation.tickets:
                self._completed[asset] = ticket + 1
            self._condition.notify_all()

    def ready_backlog(self) -> int:
        return self._ready.qsize()

    def waiting_backlog(self) -> int:
        return sum(1 for task in self._waiters if not task.done())

    async def cancel_waiters(self) -> None:
        waiters = tuple(task for task in self._waiters if not task.done())
        for task in waiters:
            task.cancel()
        if waiters:
            await asyncio.gather(*waiters, return_exceptions=True)
