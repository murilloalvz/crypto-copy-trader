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
    continuation-only. Those items no longer need stateful execution, but their issued
    per-asset tickets must still be consumed in FIFO order.

    This scheduler converts only *pending* submitted reservations for which the supplied
    predicate returns False (meaning "no longer stateful") into causal skips. It never
    reorders tickets, never demotes ready/running work, and leaves ambiguous/late-earlier
    cases on the original stateful path.
    """

    def __init__(self, *, should_remain_stateful: Callable[[T], bool]):
        super().__init__()
        self._should_remain_stateful = should_remain_stateful
        self.demoted_pending_jobs = 0
        self.demoted_pending_tickets = 0
        self.demotion_wait_seconds: list[float] = []

    def _demote_proven_pending(self) -> None:
        selected: list[tuple[int, object]] = []
        for pending_id, pending in tuple(self._pending.items()):
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
                self._skipped_by_asset.setdefault(asset, set()).add(ticket)
                affected_assets.add(asset)
                self.demoted_pending_tickets += 1

            self.demoted_pending_jobs += 1
            self.demotion_wait_seconds.append(max(0.0, now - current.waiter_started_monotonic))

        advanced_pairs: list[tuple[str, int]] = []
        for asset in affected_assets:
            advanced_pairs.extend(self._advance_skipped_asset(asset))
        if advanced_pairs:
            self._consider_successors(tuple(advanced_pairs))

    async def complete(self, reservation):
        # The caller finalizes the current payload before calling complete(), so the
        # run-local episode cache already contains any newly established canonical episode.
        self._demote_proven_pending()
        await super().complete(reservation)
