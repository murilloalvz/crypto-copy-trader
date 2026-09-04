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
    reservation_id: int = field(default=-1, compare=False)

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


@dataclass
class _PendingAssetWork(Generic[T]):
    payload: T
    reservation: AssetReservation
    waiter_started_monotonic: float
    blocking_assets: tuple[str, ...]
    indexed_tickets: set[tuple[str, int]]


class ReadyAssetScheduler(Generic[T]):
    """Ingress-ordered per-asset FIFO scheduler without waiter-task thundering herd.

    Reservations receive monotonically increasing per-asset tickets. Stateful submitted
    work can become ready only when every asset's completed cursor equals that work's
    ticket. Pending jobs are indexed by the exact ticket they need, so completing N
    inspects only a possible N+1 successor instead of waking every waiter for the asset.

    A reservation that is proven to be a causal no-op may be ``skip``-ped instead of
    submitted. The skipped ticket is remembered only while it is still ahead of an
    earlier stateful predecessor; once the cursor reaches it, the ticket is consumed and
    forgotten. This removes read-only detector results from the dependency graph without
    allowing any later state-mutating job to overtake an earlier state-mutating predecessor.
    """

    def __init__(self) -> None:
        self._issued: dict[str, int] = {}
        self._completed: dict[str, int] = {}
        self._ready: asyncio.Queue[ScheduledAssetWork[T]] = asyncio.Queue()
        self._pre_cancel_snapshot: SchedulerSnapshot | None = None

        self._next_reservation_id = 0
        self._next_pending_id = 0
        self._pending: dict[int, _PendingAssetWork[T]] = {}
        self._pending_by_ticket: dict[tuple[str, int], set[int]] = {}
        self._skipped_by_asset: dict[str, set[int]] = {}
        self._submitted_reservations: set[tuple[str, int]] = set()

        # Diagnostic-only state. None of these counters participate in scheduling decisions.
        self._reservations_by_asset: dict[str, int] = {}
        self._max_outstanding_by_asset: dict[str, int] = {}
        self._waiting_by_asset: dict[str, int] = {}
        self._max_waiting_by_asset: dict[str, int] = {}
        self._dependency_waits_by_asset: dict[str, list[float]] = {}
        self._active_waits: dict[int, tuple[float, tuple[str, ...]]] = {}

    @staticmethod
    def _reservation_key(reservation: AssetReservation) -> tuple[str, int]:
        if reservation.reservation_id >= 0:
            return ("issued", reservation.reservation_id)
        return ("external", id(reservation))

    def reserve(self, assets: tuple[str, ...] | list[str]) -> AssetReservation:
        unique_assets = tuple(
            sorted({str(asset).strip() for asset in assets if str(asset).strip()})
        )
        tickets: list[tuple[str, int]] = []
        created = time.monotonic()
        reservation_id = self._next_reservation_id
        self._next_reservation_id += 1
        for asset in unique_assets:
            ticket = self._issued.get(asset, 0)
            self._issued[asset] = ticket + 1
            tickets.append((asset, ticket))
            self._reservations_by_asset[asset] = self._reservations_by_asset.get(asset, 0) + 1
            outstanding = self._issued[asset] - self._completed.get(asset, 0)
            self._max_outstanding_by_asset[asset] = max(
                self._max_outstanding_by_asset.get(asset, 0), outstanding
            )
        return AssetReservation(
            tuple(tickets),
            created_monotonic=created,
            reservation_id=reservation_id,
        )

    def submit(self, payload: T, reservation: AssetReservation) -> None:
        key = self._reservation_key(reservation)
        if key in self._submitted_reservations:
            raise RuntimeError("asset reservation was submitted more than once")

        for asset, ticket in reservation.tickets:
            current = self._completed.get(asset, 0)
            if ticket < current or ticket in self._skipped_by_asset.get(asset, set()):
                raise RuntimeError("cannot submit a reservation already marked as causal no-op")

        self._submitted_reservations.add(key)

        if self._reservation_ready(reservation):
            now = time.monotonic()
            self._enqueue_ready(
                payload,
                reservation,
                waiter_started_monotonic=now,
                blocking_assets=(),
            )
            return

        waiter_started = time.monotonic()
        blocking_pairs = tuple(
            (asset, ticket)
            for asset, ticket in reservation.tickets
            if self._completed.get(asset, 0) != ticket
        )
        blocking_assets = tuple(asset for asset, _ in blocking_pairs)
        pending_id = self._next_pending_id
        self._next_pending_id += 1
        indexed_tickets = set(blocking_pairs)
        self._pending[pending_id] = _PendingAssetWork(
            payload=payload,
            reservation=reservation,
            waiter_started_monotonic=waiter_started,
            blocking_assets=blocking_assets,
            indexed_tickets=indexed_tickets,
        )
        self._active_waits[pending_id] = (waiter_started, blocking_assets)
        for asset in blocking_assets:
            current = self._waiting_by_asset.get(asset, 0) + 1
            self._waiting_by_asset[asset] = current
            self._max_waiting_by_asset[asset] = max(
                self._max_waiting_by_asset.get(asset, 0), current
            )
        for pair in indexed_tickets:
            self._pending_by_ticket.setdefault(pair, set()).add(pending_id)

    def skip(self, reservation: AssetReservation) -> None:
        """Remove a proven no-op reservation from the stateful dependency graph.

        ``skip`` must be chosen instead of ``submit``. A skipped ticket may sit ahead of
        the current cursor while an earlier stateful predecessor is still running. Once
        that predecessor completes, contiguous skipped tickets are consumed automatically
        before successor readiness is evaluated. Empty reservations are already no-op and
        therefore require no retained scheduler state.
        """

        key = self._reservation_key(reservation)
        if key in self._submitted_reservations:
            raise RuntimeError("cannot skip an asset reservation after submit")

        for asset, ticket in reservation.tickets:
            issued = self._issued.get(asset, 0)
            current = self._completed.get(asset, 0)
            if ticket >= issued:
                raise RuntimeError(
                    f"cannot skip unissued asset ticket for {asset}: ticket={ticket} issued={issued}"
                )
            if ticket < current:
                raise RuntimeError(
                    f"cannot skip already completed asset ticket for {asset}: "
                    f"ticket={ticket} completed={current}"
                )
            if ticket in self._skipped_by_asset.get(asset, set()):
                raise RuntimeError("asset reservation was skipped more than once")

        for asset, ticket in reservation.tickets:
            self._skipped_by_asset.setdefault(asset, set()).add(ticket)

        advanced_pairs: list[tuple[str, int]] = []
        for asset, _ in reservation.tickets:
            advanced_pairs.extend(self._advance_skipped_asset(asset))
        if advanced_pairs:
            self._consider_successors(tuple(advanced_pairs))

    def _advance_skipped_asset(self, asset: str) -> list[tuple[str, int]]:
        skipped = self._skipped_by_asset.get(asset)
        if not skipped:
            return []

        advanced_pairs: list[tuple[str, int]] = []
        current = self._completed.get(asset, 0)
        while current in skipped:
            skipped.remove(current)
            current += 1
            self._completed[asset] = current
            advanced_pairs.append((asset, current))
        if not skipped:
            self._skipped_by_asset.pop(asset, None)
        return advanced_pairs

    def _reservation_ready(self, reservation: AssetReservation) -> bool:
        return all(
            self._completed.get(asset, 0) == ticket
            for asset, ticket in reservation.tickets
        )

    def _enqueue_ready(
        self,
        payload: T,
        reservation: AssetReservation,
        *,
        waiter_started_monotonic: float,
        blocking_assets: tuple[str, ...],
    ) -> None:
        if blocking_assets:
            dependency_ready = time.monotonic()
            ready_queue_entered = time.monotonic()
            wait_seconds = max(0.0, dependency_ready - waiter_started_monotonic)
            for asset in blocking_assets:
                self._dependency_waits_by_asset.setdefault(asset, []).append(wait_seconds)
        else:
            # Preserve the existing fast-path telemetry contract: no causal wait means
            # all scheduler timestamps are exactly the same instant.
            dependency_ready = waiter_started_monotonic
            ready_queue_entered = waiter_started_monotonic

        self._ready.put_nowait(
            ScheduledAssetWork(
                payload,
                reservation,
                waiter_started_monotonic=waiter_started_monotonic,
                dependency_ready_monotonic=dependency_ready,
                ready_queue_entered_monotonic=ready_queue_entered,
            )
        )

    def _remove_pending_indexes(self, pending_id: int, pending: _PendingAssetWork[T]) -> None:
        for pair in tuple(pending.indexed_tickets):
            ids = self._pending_by_ticket.get(pair)
            if ids is None:
                continue
            ids.discard(pending_id)
            if not ids:
                self._pending_by_ticket.pop(pair, None)
        pending.indexed_tickets.clear()

    def _release_pending(self, pending_id: int) -> None:
        pending = self._pending.pop(pending_id)
        self._remove_pending_indexes(pending_id, pending)
        for asset in pending.blocking_assets:
            self._waiting_by_asset[asset] = max(
                0, self._waiting_by_asset.get(asset, 0) - 1
            )
        self._active_waits.pop(pending_id, None)
        self._enqueue_ready(
            pending.payload,
            pending.reservation,
            waiter_started_monotonic=pending.waiter_started_monotonic,
            blocking_assets=pending.blocking_assets,
        )

    def _consider_successors(self, advanced_pairs: tuple[tuple[str, int], ...]) -> None:
        candidate_ids: set[int] = set()
        for pair in advanced_pairs:
            candidate_ids.update(self._pending_by_ticket.pop(pair, set()))

        for pending_id in candidate_ids:
            pending = self._pending.get(pending_id)
            if pending is None:
                continue
            for pair in advanced_pairs:
                pending.indexed_tickets.discard(pair)
            if self._reservation_ready(pending.reservation):
                self._release_pending(pending_id)

    async def get_ready(self) -> ScheduledAssetWork[T]:
        return await self._ready.get()

    def ready_task_done(self) -> None:
        self._ready.task_done()

    async def complete(self, reservation: AssetReservation) -> None:
        key = self._reservation_key(reservation)
        if key not in self._submitted_reservations:
            raise RuntimeError("cannot complete an asset reservation that was not submitted")

        for asset, ticket in reservation.tickets:
            current = self._completed.get(asset, 0)
            if current != ticket:
                raise RuntimeError(
                    f"asset order completion mismatch for {asset}: expected {current}, got {ticket}"
                )

        self._submitted_reservations.discard(key)
        advanced_pairs: list[tuple[str, int]] = []
        for asset, ticket in reservation.tickets:
            next_ticket = ticket + 1
            self._completed[asset] = next_ticket
            advanced_pairs.append((asset, next_ticket))
            advanced_pairs.extend(self._advance_skipped_asset(asset))
        self._consider_successors(tuple(advanced_pairs))

    def ready_backlog(self) -> int:
        if self._pre_cancel_snapshot is not None:
            return self._pre_cancel_snapshot.ready_backlog
        return self._ready.qsize()

    def waiting_backlog(self) -> int:
        if self._pre_cancel_snapshot is not None:
            return self._pre_cancel_snapshot.waiting_backlog
        return len(self._pending)

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
            waiting_backlog=len(self._pending),
            outstanding_by_asset=outstanding,
            asset_telemetry=self._asset_telemetry(),
        )

    def pre_cancel_snapshot(self) -> SchedulerSnapshot:
        return self._pre_cancel_snapshot or self.snapshot()

    async def cancel_waiters(self) -> None:
        self._pre_cancel_snapshot = self.snapshot()
        self._pending.clear()
        self._pending_by_ticket.clear()
        self._active_waits.clear()
        self._skipped_by_asset.clear()
        self._submitted_reservations.clear()
