from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Generic, TypeVar


T = TypeVar("T")


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile)))
    return ordered[index]


@dataclass(frozen=True)
class AssetReservation:
    tickets: tuple[tuple[str, int], ...]
    created_monotonic: float = field(default=0.0, compare=False)

    @property
    def assets(self) -> tuple[str, ...]:
        return tuple(asset for asset, _ in self.tickets)


@dataclass(frozen=True)
class ScheduledAssetWork(Generic[T]):
    payload: T
    reservation: AssetReservation
    waiter_started_monotonic: float = field(default=0.0, compare=False)
    dependency_ready_monotonic: float = field(default=0.0, compare=False)
    ready_queue_entered_monotonic: float = field(default=0.0, compare=False)


@dataclass(frozen=True)
class SchedulerAssetTelemetry:
    asset: str
    reservations: int
    max_outstanding_tickets: int
    max_waiting_jobs: int
    active_waiting_jobs: int
    dependency_wait_count: int
    dependency_wait_total_seconds: float
    dependency_wait_p50_seconds: float
    dependency_wait_p95_seconds: float
    dependency_wait_max_seconds: float


@dataclass(frozen=True)
class SchedulerSnapshot:
    ready_backlog: int
    waiting_backlog: int
    outstanding_by_asset: tuple[tuple[str, int], ...]
    asset_telemetry: tuple[SchedulerAssetTelemetry, ...] = ()

    @property
    def total_outstanding_tickets(self) -> int:
        return sum(count for _, count in self.outstanding_by_asset)


class ReadyAssetScheduler(Generic[T]):
    """Ingress-ordered per-asset FIFO scheduler that never spends execution slots waiting."""

    def __init__(self) -> None:
        self._issued: dict[str, int] = {}
        self._completed: dict[str, int] = {}
        self._condition = asyncio.Condition()
        self._ready: asyncio.Queue[ScheduledAssetWork[T]] = asyncio.Queue()
        self._waiters: set[asyncio.Task[None]] = set()
        self._pre_cancel_snapshot: SchedulerSnapshot | None = None

        # Diagnostic-only state. None of these counters participate in scheduling decisions.
        self._reservations_by_asset: dict[str, int] = {}
        self._max_outstanding_by_asset: dict[str, int] = {}
        self._waiting_by_asset: dict[str, int] = {}
        self._max_waiting_by_asset: dict[str, int] = {}
        self._dependency_waits_by_asset: dict[str, list[float]] = {}
        self._active_waits: dict[int, tuple[float, tuple[str, ...]]] = {}

    def reserve(self, assets: tuple[str, ...] | list[str]) -> AssetReservation:
        unique_assets = tuple(sorted({str(asset).strip() for asset in assets if str(asset).strip()}))
        tickets: list[tuple[str, int]] = []
        created = time.monotonic()
        for asset in unique_assets:
            ticket = self._issued.get(asset, 0)
            self._issued[asset] = ticket + 1
            tickets.append((asset, ticket))
            self._reservations_by_asset[asset] = self._reservations_by_asset.get(asset, 0) + 1
            outstanding = self._issued[asset] - self._completed.get(asset, 0)
            self._max_outstanding_by_asset[asset] = max(
                self._max_outstanding_by_asset.get(asset, 0), outstanding
            )
        return AssetReservation(tuple(tickets), created_monotonic=created)

    def submit(self, payload: T, reservation: AssetReservation) -> None:
        # Fast path: most reservations are already the next ticket for every asset.
        # Avoid creating an asyncio Task merely to discover that there is no causal
        # predecessor to wait for. Under burst load that task-resumption delay became
        # measurable at the latency gate even though the reservation was already ready.
        if self._reservation_ready(reservation):
            now = time.monotonic()
            self._ready.put_nowait(
                ScheduledAssetWork(
                    payload,
                    reservation,
                    waiter_started_monotonic=now,
                    dependency_ready_monotonic=now,
                    ready_queue_entered_monotonic=now,
                )
            )
            return

        task = asyncio.create_task(self._wait_until_ready(payload, reservation))
        self._waiters.add(task)
        task.add_done_callback(self._waiters.discard)

    def _reservation_ready(self, reservation: AssetReservation) -> bool:
        return all(
            self._completed.get(asset, 0) == ticket
            for asset, ticket in reservation.tickets
        )

    async def _wait_until_ready(self, payload: T, reservation: AssetReservation) -> None:
        waiter_started = time.monotonic()
        task = asyncio.current_task()
        task_key = id(task) if task is not None else id(reservation)
        blocking_assets: tuple[str, ...] = ()

        async with self._condition:
            blocking_assets = tuple(
                asset
                for asset, ticket in reservation.tickets
                if self._completed.get(asset, 0) != ticket
            )
            if blocking_assets:
                self._active_waits[task_key] = (waiter_started, blocking_assets)
                for asset in blocking_assets:
                    current = self._waiting_by_asset.get(asset, 0) + 1
                    self._waiting_by_asset[asset] = current
                    self._max_waiting_by_asset[asset] = max(
                        self._max_waiting_by_asset.get(asset, 0), current
                    )
            try:
                await self._condition.wait_for(lambda: self._reservation_ready(reservation))
            finally:
                if blocking_assets:
                    for asset in blocking_assets:
                        self._waiting_by_asset[asset] = max(
                            0, self._waiting_by_asset.get(asset, 0) - 1
                        )
                    self._active_waits.pop(task_key, None)

        dependency_ready = time.monotonic()
        if blocking_assets:
            wait_seconds = max(0.0, dependency_ready - waiter_started)
            for asset in blocking_assets:
                self._dependency_waits_by_asset.setdefault(asset, []).append(wait_seconds)

        ready_queue_entered = time.monotonic()
        await self._ready.put(
            ScheduledAssetWork(
                payload,
                reservation,
                waiter_started_monotonic=waiter_started,
                dependency_ready_monotonic=dependency_ready,
                ready_queue_entered_monotonic=ready_queue_entered,
            )
        )

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
        if self._pre_cancel_snapshot is not None:
            return self._pre_cancel_snapshot.ready_backlog
        return self._ready.qsize()

    def waiting_backlog(self) -> int:
        if self._pre_cancel_snapshot is not None:
            return self._pre_cancel_snapshot.waiting_backlog
        return sum(1 for task in self._waiters if not task.done())

    def _asset_telemetry(self) -> tuple[SchedulerAssetTelemetry, ...]:
        now = time.monotonic()
        active_ages_by_asset: dict[str, list[float]] = {}
        for started, assets in self._active_waits.values():
            age = max(0.0, now - started)
            for asset in assets:
                active_ages_by_asset.setdefault(asset, []).append(age)

        all_assets = set(self._issued)
        all_assets.update(self._reservations_by_asset)
        telemetry: list[SchedulerAssetTelemetry] = []
        for asset in all_assets:
            completed_waits = list(self._dependency_waits_by_asset.get(asset, ()))
            active_ages = active_ages_by_asset.get(asset, [])
            effective_waits = completed_waits + active_ages
            telemetry.append(
                SchedulerAssetTelemetry(
                    asset=asset,
                    reservations=self._reservations_by_asset.get(asset, 0),
                    max_outstanding_tickets=self._max_outstanding_by_asset.get(asset, 0),
                    max_waiting_jobs=self._max_waiting_by_asset.get(asset, 0),
                    active_waiting_jobs=len(active_ages),
                    dependency_wait_count=len(effective_waits),
                    dependency_wait_total_seconds=sum(effective_waits),
                    dependency_wait_p50_seconds=_percentile(effective_waits, 0.50),
                    dependency_wait_p95_seconds=_percentile(effective_waits, 0.95),
                    dependency_wait_max_seconds=max(effective_waits, default=0.0),
                )
            )
        return tuple(
            sorted(
                telemetry,
                key=lambda item: (
                    -item.dependency_wait_total_seconds,
                    -item.reservations,
                    item.asset,
                ),
            )
        )

    def snapshot(self) -> SchedulerSnapshot:
        outstanding = tuple(
            sorted(
                (
                    (asset, issued - self._completed.get(asset, 0))
                    for asset, issued in self._issued.items()
                    if issued - self._completed.get(asset, 0) > 0
                ),
                key=lambda item: (-item[1], item[0]),
            )
        )
        return SchedulerSnapshot(
            ready_backlog=self._ready.qsize(),
            waiting_backlog=sum(1 for task in self._waiters if not task.done()),
            outstanding_by_asset=outstanding,
            asset_telemetry=self._asset_telemetry(),
        )

    def pre_cancel_snapshot(self) -> SchedulerSnapshot:
        return self._pre_cancel_snapshot or self.snapshot()

    async def cancel_waiters(self) -> None:
        self._pre_cancel_snapshot = self.snapshot()
        waiters = tuple(task for task in self._waiters if not task.done())
        for task in waiters:
            task.cancel()
        if waiters:
            await asyncio.gather(*waiters, return_exceptions=True)
