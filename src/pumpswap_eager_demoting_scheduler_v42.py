from __future__ import annotations

from typing import Generic, TypeVar

from src.pumpswap_demoting_scheduler_v34 import DemotingReadyAssetSchedulerV34


T = TypeVar("T")


class EagerDemotingReadyAssetSchedulerV42(DemotingReadyAssetSchedulerV34[T], Generic[T]):
    """v34 scheduler with eager proof-based demotion on new submissions.

    v34 demotes pending followers when a stateful predecessor completes. Under a hot-asset burst,
    the immutable run-local episode cache may already prove many pending followers are
    continuation-only before the next scheduler ``complete`` call occurs. Those followers do not
    need to remain in the state-mutating dependency graph merely because no completion callback has
    fired yet.

    v42 invokes the *same* v34 proof over already-pending work immediately before each new submit.
    Only pending jobs for which ``should_remain_stateful`` is false are demoted; ready/running jobs
    are untouched, ambiguous/late-earlier/different-window work remains FIFO, issued tickets are
    still consumed as causal skips, and every demoted payload still traverses the normal finalizer
    for continuation audit visibility.

    No detector, episode-window, reservation, replay, as-of or trigger semantics change.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.eager_submit_demote_passes = 0
        self.eager_submit_demoted_jobs = 0
        self.eager_submit_demoted_tickets = 0

    def submit(self, payload: T, reservation) -> None:
        before_jobs = self.demoted_pending_jobs
        before_tickets = self.demoted_pending_tickets

        # Reuse the exact v34 proof and demotion mechanics. This examines pending submitted work
        # only; the incoming reservation has not yet been submitted and therefore cannot be
        # accidentally demoted by this pass.
        self._demote_proven_pending()

        self.eager_submit_demote_passes += 1
        self.eager_submit_demoted_jobs += self.demoted_pending_jobs - before_jobs
        self.eager_submit_demoted_tickets += self.demoted_pending_tickets - before_tickets
        super().submit(payload, reservation)
