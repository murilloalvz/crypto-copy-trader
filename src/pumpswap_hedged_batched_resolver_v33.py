from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import threading

from src.pumpswap_batched_resolver_v32 import BatchedBoundedConcurrentResolverV32
from src.solana import SolanaClient, SolanaRPCError


class HedgedBatchedBoundedResolverV33(BatchedBoundedConcurrentResolverV32):
    """Bound unknown-pool hydration tail without weakening v32 causal semantics.

    v32 batches concurrent pool identity misses, but its one batch call still inherits
    ``SolanaClient.call`` retry/fallback serialization. A few slow endpoint attempts can
    therefore hold the global ingress reservation watermark for tens of seconds.

    v33 keeps the same per-pool hydration budget, per-pool single-flight, expensive-work
    semaphore, batching, effective ``observed_at`` and global reservation ordering. Only
    the external RPC policy changes: one batch is issued once to up to two configured RPC
    endpoints in parallel, and the first valid response wins. No endpoint performs an
    internal retry. If every hedge fails, the pool identities remain explicitly unresolved
    rather than blocking unrelated market observations through sequential retries.
    """

    last_instance: "HedgedBatchedBoundedResolverV33 | None" = None

    def __init__(self, *args, hedge_endpoints: int = 2, **kwargs) -> None:
        if hedge_endpoints <= 0:
            raise ValueError("hedge_endpoints must be positive")
        super().__init__(*args, **kwargs)
        self.hedge_endpoints = int(hedge_endpoints)
        self.hedged_batch_calls = 0
        self.hedged_endpoint_requests = 0
        self.hedged_all_failed = 0
        self.hedged_winner_hosts: dict[str, int] = {}
        self._hedge_metrics_lock = threading.Lock()
        type(self).last_instance = self
        HedgedBatchedBoundedResolverV33.last_instance = self

    def _one_endpoint_batch(self, rpc_url: str, pools: list[str]):
        client = SolanaClient(
            rpc_url=rpc_url,
            timeout=self.client.timeout,
            fallback_urls=(),
        )
        result = client.call(
            "getMultipleAccounts",
            [pools, {"encoding": "base64", "commitment": self.commitment}],
            max_attempts=1,
        ) or {}
        values = result.get("value") if isinstance(result, dict) else None
        if not isinstance(values, list) or len(values) != len(pools):
            raise SolanaRPCError("getMultipleAccounts returned invalid value count")
        decoded = [self._decode_value(value) for value in values]
        return rpc_url, decoded

    def _fetch_batch(self, items):
        pools = [pool for pool, _ in items]
        endpoints = list(dict.fromkeys(self.client.rpc_urls))[: self.hedge_endpoints]
        if not endpoints:
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
            thread_name_prefix="pumpswap-hydration-hedge-v33",
        )
        futures = {
            executor.submit(self._one_endpoint_batch, endpoint, pools): endpoint
            for endpoint in endpoints
        }
        winner = None
        pending = set(futures)
        try:
            while pending and winner is None:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for completed in done:
                    try:
                        winner = completed.result()
                    except BaseException as exc:
                        errors.append(exc)
                        continue
                    break
        finally:
            for future in pending:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)

        if winner is None:
            with self._hedge_metrics_lock:
                self.hedged_all_failed += 1
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
