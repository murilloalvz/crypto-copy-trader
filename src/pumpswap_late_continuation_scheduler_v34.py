from __future__ import annotations

import time
from typing import Callable, Generic, TypeVar

from src.pumpswap_ready_scheduler import ReadyAssetScheduler


T = TypeVar("T")


class LateContinuationReadyAssetSchedulerV34(ReadyAssetScheduler[T], Generic[T]):
    """Demote already-submitted work once it is proven continuation-only.

    v27 already removes continuation-only work before scheduler submission. A hot burst can
    still prepare many detector-positive jobs while the first stateful opener is waiting to
    commit, so those jobs are conservatively submitted as stateful. Once the opener commits,
    the run-local episode cache can prove that some of those pending jobs are now pure
    continuations.

    This scheduler rechecks only *pending* submitted jobs immediately before a normal stateful
    completion advances the per-asset cursor. Proven continuation-only reservations are removed
    from the pending dependency graph, converted to ordinary skipped/no-op tickets, and queued
    for the normal finalizer so their continuation audit/hit handling still runs. Their later
    ``complete`` call is intentionally a no-op because the stateful cursor already consumed the
    skipped ticket.

    The classifier is conservative: ``True`` means the payload may still mutate episode state
    and must remain FIFO. Only ``False`` is eligible for late demotion.
    """

    last_instance: "LateContinuationReadyAssetSchedulerV34 | None" = None

    def __init__(self, *, may_require_stateful: Callable[[T], bool]) -> None:
        super().__init__()
        self._may_require_stateful = may_require_stateful
        self._late_demoted_reservations: set[tuple[str, int]] = set()
        self.late_demotions = 0
        self.late_demoted_tickets = 0
        self.late_demotion_wait_seconds: list[float] = []
        type(self).last_instance = self
        LateContinuationReadyAssetSchedulerV34.last_instance = self

    def _demote_proven_continuations(self) -> None:
        # Deterministic pending-id order keeps diagnostics/replay behavior reproducible.
        for pending_id in tuple(sorted(self._pending)):
            pending = self._pending.get(pending_id)
            if pending is None:
                continue
            if self._may_require_stateful(pending.payload):
                continue

            reservation = pending.reservation
            key = self._reservation_key(reservation)
            if key not in self._submitted_reservations:
                raise RuntimeError("late-demotion pending reservation lost submission identity")

            now = time.monotonic()
            self._pending.pop(pending_id)
            self._remove_pending_indexes(pending_id, pending)
            for asset in pending.blocking_assets:
                self._waiting_by_asset[asset] = max(
                    0, self._waiting_by_asset.get(asset, 0) - 1
                )
            self._active_waits.pop(pending_id, None)

            # ``skip`` is the already-proven scheduler primitive for read-only work. Remove
            # submission identity first so the same reservation can legally transition from
            # conservative stateful-pending to proven no-op.
            self._submitted_reservations.discard(key)
            self.skip(reservation)
            self._late_demoted_reservations.add(key)

            self.late_demotions += 1
            self.late_demoted_tickets += len(reservation.tickets)
            self.late_demotion_wait_seconds.append(
                max(0.0, now - pending.waiter_started_monotonic)
            )

            # The payload still goes through the existing finalizer. Under v27's dynamic
            # classifier/finalizer this path only appends continuation audit and returns the
            # canonical episode hit; it does not assign new episode state.
            self._enqueue_ready(
                pending.payload,
                reservation,
                waiter_started_monotonic=pending.waiter_started_monotonic,
                blocking_assets=pending.blocking_assets,
            )

    async def complete(self, reservation) -> None:
        key = self._reservation_key(reservation)
        if key in self._late_demoted_reservations:
            # Its stateful ticket was already converted to skip/no-op. Finalizer completion is
            # only acknowledgement that continuation audit/hit handling finished.
            self._late_demoted_reservations.remove(key)
            return

        # The finalizer has already executed the current stateful payload. If that payload opened
        # an episode, v27's run-local cache is now populated, so this is the earliest safe moment
        # to reclassify later pending tickets *before* advancing the current cursor.
        self._demote_proven_continuations()
        await super().complete(reservation)
