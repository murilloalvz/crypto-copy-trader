from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from src.pumpswap_ingress_prefetch_v49 import candidate_trade_pools_v49
from src.pumpswap_opportunistic_prefetch_v53 import (
    OpportunisticPumpSwapIngressPrefetchV53,
)
from src.pumpswap_stream import PumpSwapLogNotification


@dataclass(frozen=True)
class DemandOnlyPrefetchSnapshotV54:
    notifications_seen: int
    candidate_pools: int
    scheduled: int
    skipped_speculative: int
    active: int


class DemandOnlyPumpSwapIngressPrefetchV54(OpportunisticPumpSwapIngressPrefetchV53):
    """Keep ingress observation but never let speculative work own resolver synchronization.

    v53 showed that optional prefetch can still acquire the same per-pool lock used by authoritative
    normalization. Under a later fresh v48 subcohort, global resolution-capacity wait was zero while
    authoritative demand waited seconds on the pool lock. v54 therefore removes only speculative
    resolver admission: ingress still identifies candidate pools for diagnostics, but it creates no
    resolver task, consumes no hydration budget, touches no pool lock/semaphore, persists no mapping,
    and creates no reservation or detector evidence.

    Authoritative normalization is unchanged and still calls ``resolver.resolve`` with the original
    causal ``as_of``. This is deliberately narrower than changing single-flight, reservation order,
    FIFO, detector semantics, provider pacing, or any economic rule.
    """

    last_instance: "DemandOnlyPumpSwapIngressPrefetchV54 | None" = None

    def __init__(self) -> None:
        super().__init__()
        self._v54_counters: Counter[str] = Counter()
        DemandOnlyPumpSwapIngressPrefetchV54.last_instance = self
        type(self).last_instance = self

    def schedule(self, notification: PumpSwapLogNotification, resolver) -> None:
        del resolver  # Explicitly unused: speculative ingress is observation-only in v54.
        self._counters["notifications_seen"] += 1
        pools = candidate_trade_pools_v49(notification)
        self._counters["candidate_pools"] += len(pools)
        self._v54_counters["skipped_speculative"] += len(pools)
        # Intentionally create no asyncio task. The canonical demand path owns all resolver work.

    def snapshot_v54(self) -> DemandOnlyPrefetchSnapshotV54:
        base = self.snapshot()
        return DemandOnlyPrefetchSnapshotV54(
            notifications_seen=base.notifications_seen,
            candidate_pools=base.candidate_pools,
            scheduled=base.scheduled,
            skipped_speculative=int(self._v54_counters["skipped_speculative"]),
            active=base.active,
        )
