from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
import threading
import time

from src.pumpswap_parallel_batched_resolver_v41 import (
    ParallelHedgedBatchedBoundedResolverV41,
)
from src.solana import SolanaRPCError


@dataclass(frozen=True)
class HedgeWallDeadlineSnapshotV52:
    wall_deadline_seconds: float
    deadline_expirations: int
    fetch_seconds: tuple[float, ...]


class DeadlineBoundedParallelHedgedResolverV52(
    ParallelHedgedBatchedBoundedResolverV41
):
    """Enforce the configured RPC timeout across the whole hedged batch wall clock.

    v33 starts each endpoint with ``max_attempts=1`` but ``SolanaClient.call`` may still perform
    an internal TLS fallback after an SSL transport failure. Without an outer wall deadline, one
    logical hedge can therefore outlive the configured RPC timeout and hold the unchanged global
    PumpSwap reservation watermark.

    v52 changes only response acceptance timing: every hedge still starts concurrently and the
    first valid response wins, but it must arrive within ``client.timeout`` seconds measured from
    batch dispatch. If none does, all item futures receive an explicit ``SolanaRPCError`` through
    the existing unresolved/negative-cache path. Late endpoint results are ignored for the timed-out
    notification. Cache/store/single-flight/hydration-budget/FIFO semantics remain inherited.
    """

    last_instance: "DeadlineBoundedParallelHedgedResolverV52 | None" = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        deadline = float(self.client.timeout)
        if deadline <= 0:
            raise ValueError("PumpSwap hedge wall deadline must be positive")
        self.hedge_wall_deadline_seconds = deadline
        self.hedge_wall_deadline_expirations = 0
        self.hedge_fetch_seconds: list[float] = []
        self._v52_metrics_lock = threading.Lock()
        DeadlineBoundedParallelHedgedResolverV52.last_instance = self
        type(self).last_instance = self

    def _record_fetch(self, started_monotonic: float, *, deadline_expired: bool) -> None:
        elapsed = max(0.0, time.monotonic() - started_monotonic)
        with self._v52_metrics_lock:
            self.hedge_fetch_seconds.append(elapsed)
            if deadline_expired:
                self.hedge_wall_deadline_expirations += 1

    def _fetch_batch(self, items):
        started = time.monotonic()
        pools = [pool for pool, _ in items]
        endpoints = list(dict.fromkeys(self.client.rpc_urls))[: self.hedge_endpoints]
        if not endpoints:
            self._record_fetch(started, deadline_expired=False)
            error = SolanaRPCError("no RPC endpoint configured for hedged batch hydration")
            for _, future in items:
                if not future.done():
                    future.set_exception(error)
            return

        with self._hedge_metrics_lock:
            self.hedged_batch_calls += 1
            self.hedged_endpoint_requests += len(endpoints)

        errors: list[BaseException] = []
        executor = ThreadPoolExecutor(
            max_workers=len(endpoints),
            thread_name_prefix="pumpswap-hydration-hedge-v52",
        )
        futures = {
            executor.submit(self._one_endpoint_batch, endpoint, pools): endpoint
            for endpoint in endpoints
        }
        winner = None
        pending = set(futures)
        deadline_monotonic = started + self.hedge_wall_deadline_seconds
        deadline_expired = False
        try:
            while pending and winner is None:
                remaining = deadline_monotonic - time.monotonic()
                if remaining <= 0:
                    deadline_expired = True
                    break
                done, pending = wait(
                    pending,
                    timeout=remaining,
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    deadline_expired = True
                    break
                for completed in done:
                    try:
                        candidate = completed.result()
                    except BaseException as exc:
                        errors.append(exc)
                        continue
                    winner = candidate
                    break
        finally:
            for future in pending:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

        self._record_fetch(started, deadline_expired=deadline_expired)

        if winner is None:
            with self._hedge_metrics_lock:
                self.hedged_all_failed += 1
            if deadline_expired:
                errors.append(
                    SolanaRPCError(
                        "hedged PumpSwap batch exceeded configured RPC wall deadline "
                        f"({self.hedge_wall_deadline_seconds:.3f}s)"
                    )
                )
            message = " | ".join(str(error) for error in errors) or "all hedged RPCs failed"
            error = SolanaRPCError(message)
            for _, future in items:
                if not future.done():
                    future.set_exception(error)
            return

        rpc_url, decoded = winner
        with self._batch_metrics_lock:
            self.network_batch_calls += 1
            self.network_batch_sizes.append(len(items))
        with self._hedge_metrics_lock:
            self.hedged_winner_hosts[rpc_url] = self.hedged_winner_hosts.get(rpc_url, 0) + 1
        for (_, future), account in zip(items, decoded):
            if not future.done():
                future.set_result(account)

    def hedge_deadline_snapshot_v52(self) -> HedgeWallDeadlineSnapshotV52:
        with self._v52_metrics_lock:
            return HedgeWallDeadlineSnapshotV52(
                wall_deadline_seconds=self.hedge_wall_deadline_seconds,
                deadline_expirations=self.hedge_wall_deadline_expirations,
                fetch_seconds=tuple(self.hedge_fetch_seconds),
            )
