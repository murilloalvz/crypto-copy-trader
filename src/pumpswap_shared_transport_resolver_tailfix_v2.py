from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
import threading
import time

from src.pumpswap_deadline_hedged_resolver_v52 import (
    DeadlineBoundedParallelHedgedResolverV52,
    HedgeWallDeadlineSnapshotV52,
)
from src.solana import SolanaRPCError


@dataclass(frozen=True)
class SharedTransportTailSnapshotV2:
    transport_workers: int
    active_transports: int
    max_active_transports: int
    transport_limit_violations: int
    decisions_released: int
    residual_cleanup_pending: int
    residual_cleanup_high_water: int
    decision_release_seconds: tuple[float, ...]
    residual_cleanup_seconds: tuple[float, ...]


class SharedTransportDeadlineResolverTailfixV2(
    DeadlineBoundedParallelHedgedResolverV52
):
    """Release a hydration batch at hedge decision time without exceeding RPC capacity.

    v52 correctly publishes each item Future as soon as a valid hedge wins (or the configured
    wall deadline expires), but its per-batch ThreadPoolExecutor is shut down with wait=True.
    Therefore the surrounding v41 batch slot remains occupied until every already-running losing
    transport exits. Under bursts, otherwise-ready pool misses can queue behind loser cleanup;
    because the authoritative resolver keeps a per-pool single-flight lock while waiting for its
    item Future, this can amplify into same-pool lock wait and finally the global reservation
    sequence barrier.

    Tailfix v2 moves endpoint transports to one resolver-owned executor whose max_workers equals
    the already-configured max_concurrent_resolutions budget. A batch returns immediately after its
    causal decision is published; losing transports that were already running may finish in the
    shared executor, while not-yet-started losers are cancelled. New work can use only genuinely
    free transport workers, so decision-time batch release cannot oversubscribe the existing RPC
    ceiling.

    Cache, hydration budget, causal as_of, per-pool single-flight, explicit unresolved behavior,
    reservation order, detector semantics and economics are unchanged.
    """

    last_instance: "SharedTransportDeadlineResolverTailfixV2 | None" = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        workers = int(self.max_concurrent_resolutions)
        self._tailfix_transport_executor = ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="pumpswap-shared-transport-tailfix-v2",
        )
        self._tailfix_lock = threading.Lock()
        self._tailfix_active_transports = 0
        self._tailfix_max_active_transports = 0
        self._tailfix_transport_limit_violations = 0
        self._tailfix_decisions_released = 0
        self._tailfix_cleanup_pending = 0
        self._tailfix_cleanup_high_water = 0
        self._tailfix_decision_release_seconds: list[float] = []
        self._tailfix_cleanup_seconds: list[float] = []
        SharedTransportDeadlineResolverTailfixV2.last_instance = self
        type(self).last_instance = self

    def _metered_endpoint_batch(self, rpc_url: str, pools: list[str]):
        with self._tailfix_lock:
            self._tailfix_active_transports += 1
            self._tailfix_max_active_transports = max(
                self._tailfix_max_active_transports,
                self._tailfix_active_transports,
            )
            if self._tailfix_active_transports > int(self.max_concurrent_resolutions):
                self._tailfix_transport_limit_violations += 1
        try:
            return self._one_endpoint_batch(rpc_url, pools)
        finally:
            with self._tailfix_lock:
                self._tailfix_active_transports = max(
                    0, self._tailfix_active_transports - 1
                )

    def _record_decision(
        self,
        *,
        started_monotonic: float,
        decision_monotonic: float,
        deadline_expired: bool,
    ) -> None:
        decision_seconds = max(0.0, decision_monotonic - started_monotonic)
        with self._v52_metrics_lock:
            self.hedge_fetch_seconds.append(decision_seconds)
            if deadline_expired:
                self.hedge_wall_deadline_expirations += 1
        with self._tailfix_lock:
            self._tailfix_decisions_released += 1
            self._tailfix_decision_release_seconds.append(decision_seconds)

    def _track_residual_cleanup(
        self,
        pending: set[Future],
        *,
        decision_monotonic: float,
    ) -> None:
        running = {future for future in pending if not future.cancel()}
        if not running:
            with self._v52_metrics_lock:
                self.hedge_cleanup_seconds.append(0.0)
            with self._tailfix_lock:
                self._tailfix_cleanup_seconds.append(0.0)
            return

        tracker_lock = threading.Lock()
        remaining = {"count": len(running)}
        with self._tailfix_lock:
            self._tailfix_cleanup_pending += len(running)
            self._tailfix_cleanup_high_water = max(
                self._tailfix_cleanup_high_water,
                self._tailfix_cleanup_pending,
            )

        def finished(_future: Future) -> None:
            done = False
            with tracker_lock:
                remaining["count"] -= 1
                done = remaining["count"] == 0
            with self._tailfix_lock:
                self._tailfix_cleanup_pending = max(
                    0, self._tailfix_cleanup_pending - 1
                )
            if done:
                cleanup = max(0.0, time.monotonic() - decision_monotonic)
                with self._v52_metrics_lock:
                    self.hedge_cleanup_seconds.append(cleanup)
                with self._tailfix_lock:
                    self._tailfix_cleanup_seconds.append(cleanup)

        for future in running:
            future.add_done_callback(finished)

    def _fetch_batch(self, items):
        started = time.monotonic()
        pools = [pool for pool, _ in items]
        endpoints = list(dict.fromkeys(self.client.rpc_urls))[: self.hedge_endpoints]
        if not endpoints:
            decision_at = time.monotonic()
            error = SolanaRPCError("no RPC endpoint configured for hedged batch hydration")
            self._set_item_error(items, error)
            self._record_decision(
                started_monotonic=started,
                decision_monotonic=decision_at,
                deadline_expired=False,
            )
            self._track_residual_cleanup(set(), decision_monotonic=decision_at)
            return

        with self._hedge_metrics_lock:
            self.hedged_batch_calls += 1
            self.hedged_endpoint_requests += len(endpoints)

        futures = {
            self._tailfix_transport_executor.submit(
                self._metered_endpoint_batch,
                endpoint,
                pools,
            ): endpoint
            for endpoint in endpoints
        }
        errors: list[BaseException] = []
        winner = None
        pending = set(futures)
        deadline_monotonic = started + self.hedge_wall_deadline_seconds
        deadline_expired = False

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

        if winner is not None:
            rpc_url, decoded = winner
            with self._batch_metrics_lock:
                self.network_batch_calls += 1
                self.network_batch_sizes.append(len(items))
            with self._hedge_metrics_lock:
                self.hedged_winner_hosts[rpc_url] = (
                    self.hedged_winner_hosts.get(rpc_url, 0) + 1
                )
            for (_, item_future), account in zip(items, decoded):
                if not item_future.done():
                    item_future.set_result(account)
            decision_at = time.monotonic()
            self._record_decision(
                started_monotonic=started,
                decision_monotonic=decision_at,
                deadline_expired=False,
            )
            self._track_residual_cleanup(
                pending,
                decision_monotonic=decision_at,
            )
            return

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
        self._set_item_error(items, SolanaRPCError(message))
        decision_at = time.monotonic()
        self._record_decision(
            started_monotonic=started,
            decision_monotonic=decision_at,
            deadline_expired=deadline_expired,
        )
        self._track_residual_cleanup(
            pending,
            decision_monotonic=decision_at,
        )

    def hedge_deadline_snapshot_v52(self) -> HedgeWallDeadlineSnapshotV52:
        with self._v52_metrics_lock:
            return HedgeWallDeadlineSnapshotV52(
                wall_deadline_seconds=self.hedge_wall_deadline_seconds,
                deadline_expirations=self.hedge_wall_deadline_expirations,
                fetch_seconds=tuple(self.hedge_fetch_seconds),
                cleanup_seconds=tuple(self.hedge_cleanup_seconds),
            )

    def tailfix_snapshot_v2(self) -> SharedTransportTailSnapshotV2:
        with self._tailfix_lock:
            return SharedTransportTailSnapshotV2(
                transport_workers=int(self.max_concurrent_resolutions),
                active_transports=self._tailfix_active_transports,
                max_active_transports=self._tailfix_max_active_transports,
                transport_limit_violations=self._tailfix_transport_limit_violations,
                decisions_released=self._tailfix_decisions_released,
                residual_cleanup_pending=self._tailfix_cleanup_pending,
                residual_cleanup_high_water=self._tailfix_cleanup_high_water,
                decision_release_seconds=tuple(self._tailfix_decision_release_seconds),
                residual_cleanup_seconds=tuple(self._tailfix_cleanup_seconds),
            )

    def shutdown_parallel_batches(self, *, wait: bool = False) -> None:
        super().shutdown_parallel_batches(wait=wait)
        self._tailfix_transport_executor.shutdown(
            wait=wait,
            cancel_futures=not wait,
        )
