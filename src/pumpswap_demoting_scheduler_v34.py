from __future__ import annotations

import time
from typing import Callable, Generic, TypeVar

from src.pumpswap_ready_scheduler import ReadyAssetScheduler


T = TypeVar("T")


class DemotingReadyAssetSchedulerV34(ReadyAssetScheduler[T], Generic[T]):
    """ReadyAssetScheduler with proof-based pending stateful demotion.

    A detector-positive item may be submitted before the run-local episode cache knows
    whether an earlier predecessor will establish the episode. Once a predecessor has
    finalized, ``complete`` may prove that some still-pending submitted items are now
    continuation-only. Those items no longer need stateful episode assignment, but their
    issued per-asset tickets must still be consumed in FIFO order and their continuation
    audit/hit finalization must still execute.

    This scheduler converts only *pending* submitted reservations for which the supplied
    predicate returns False (meaning "no longer stateful") into causal skips. The payload is
    then queued through the existing finalizer. Its later scheduler ``complete`` is a no-op
    because the stateful cursor already consumed the skipped reservation. Ready/running work
    is never demoted, and ambiguous/late-earlier/different-window work remains strict FIFO.
    """

    def __init__(self, *, should_remain_stateful: Callable[[T], bool]):
        super().__init__()
        self._should_remain_stateful = should_remain_stateful
        self._demoted_finalizer_acks: set[tuple[str, int]] = set()
        self.demoted_pending_jobs = 0
        self.demoted_pending_tickets = 0
        self.demotion_wait_seconds: list[float] = []

    @property
    def demoted_finalizer_acks_pending(self) -> int:
        return len(self._demoted_finalizer_acks)

    def _demote_proven_pending(self) -> None:
        selected: list[tuple[int, object]] = []
        for pending_id, pending in tuple(sorted(self._pending.items())):
            if self._should_remain_stateful(pending.payload):
                continue
            selected.append((pending_id, pending))

        if not selected:
            return

        affected_assets: set[str] = set()
        now = time.monotonic()
        for pending_id, pending in selected:
            current = self._pending.pop(pending_id, None)
            if current is None:
                continue
            self._remove_pending_indexes(pending_id, current)
            for asset in current.blocking_assets:
                self._waiting_by_asset[asset] = max(
                    0, self._waiting_by_asset.get(asset, 0) - 1
                )
            self._active_waits.pop(pending_id, None)

            key = self._reservation_key(current.reservation)
            if key not in self._submitted_reservations:
                raise RuntimeError("pending reservation missing submitted state during demotion")
            self._submitted_reservations.discard(key)

            for asset, ticket in current.reservation.tickets:
                completed = self._completed.get(asset, 0)
                if ticket < completed:
                    raise RuntimeError(
                        f"cannot demote already completed ticket for {asset}: "
                        f"ticket={ticket} completed={completed}"
                    )
                if ticket in self._skipped_by_asset.get(asset, set()):
                    raise RuntimeError("pending demotion collided with an existing skipped ticket")
                self._skipped_by_asset.setdefault(asset, set()).add(ticket)
                affected_assets.add(asset)
                self.demoted_pending_tickets += 1

            self._demoted_finalizer_acks.add(key)
            self.demoted_pending_jobs += 1
            self.demotion_wait_seconds.append(
                max(0.0, now - current.waiter_started_monotonic)
            )

            # Preserve evidence: the payload must still traverse the normal v27-aware finalizer,
            # which now only appends continuation audit and returns the canonical episode hit.
            self._enqueue_ready(
                current.payload,
                current.reservation,
                waiter_started_monotonic=current.waiter_started_monotonic,
                blocking_assets=current.blocking_assets,
            )

        # Consume only contiguous skipped tickets. Any earlier stateful predecessor still controls
        # the cursor, so later state-mutating work cannot overtake it.
        advanced_pairs: list[tuple[str, int]] = []
        for asset in sorted(affected_assets):
            advanced_pairs.extend(self._advance_skipped_asset(asset))
        if advanced_pairs:
            self._consider_successors(tuple(advanced_pairs))

    async def complete(self, reservation):
        key = self._reservation_key(reservation)
        if key in self._demoted_finalizer_acks:
            # Continuation audit/hit handling finished. Its stateful ticket was already converted
            # to a causal skip, so there is no cursor mutation left to perform here.
            self._demoted_finalizer_acks.remove(key)
            return

        # The caller finalizes the current payload before calling complete(), so the run-local
        # episode cache already contains any newly established canonical episode. Demote proven
        # followers before advancing the current cursor so an entire hot continuation burst can
        # collapse at once rather than releasing one follower per stateful completion.
        self._demote_proven_pending()
        await super().complete(reservation)
