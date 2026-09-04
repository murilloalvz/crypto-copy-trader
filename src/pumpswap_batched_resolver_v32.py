from __future__ import annotations

import base64
from concurrent.futures import Future
import queue
import threading
import time

from src.pumpswap_concurrent_resolver import ConcurrentReusablePumpSwapPoolResolver
from src.pumpswap_stream import (
    PUMPSWAP_PROGRAM_ID,
    PumpSwapPoolAccount,
    decode_pumpswap_pool_account,
)
from src.solana import SolanaRPCError


class BatchedBoundedConcurrentResolverV32(ConcurrentReusablePumpSwapPoolResolver):
    """Batch expensive unknown-pool RPC reads without weakening v30 causal/FIFO rules.

    Cache, run-store, historical-store, per-pool single-flight and the global expensive
    resolution semaphore are inherited unchanged. Only the final network shape changes:
    concurrent unknown pools are coalesced into one ``getMultipleAccounts`` request.
    Hydration budget accounting remains per pool, not per RPC call.
    """

    last_instance: "BatchedBoundedConcurrentResolverV32 | None" = None

    def __init__(
        self,
        *args,
        max_network_hydrations: int,
        retry_seconds: float = 15.0,
        hydration_batch_size: int = 64,
        hydration_batch_max_wait_ms: int = 5,
        **kwargs,
    ) -> None:
        if max_network_hydrations <= 0:
            raise ValueError("max_network_hydrations must be positive")
        if hydration_batch_size <= 0:
            raise ValueError("hydration_batch_size must be positive")
        if hydration_batch_max_wait_ms < 0:
            raise ValueError("hydration_batch_max_wait_ms cannot be negative")
        super().__init__(*args, **kwargs)
        self.max_network_hydrations = int(max_network_hydrations)
        self.retry_seconds = float(retry_seconds)
        self.hydration_batch_size = int(hydration_batch_size)
        self.hydration_batch_max_wait_ms = int(hydration_batch_max_wait_ms)

        self.network_hydration_calls = 0
        self.hydration_budget_skips = 0
        self.negative_cache_skips = 0
        self.network_batch_calls = 0
        self.network_batch_sizes: list[int] = []
        self._failed_until: dict[str, float] = {}
        self._budget_lock = threading.Lock()
        self._batch_metrics_lock = threading.Lock()
        self._batch_queue: queue.Queue[tuple[str, Future]] = queue.Queue()
        self._batch_thread = threading.Thread(
            target=self._batch_loop,
            name="pumpswap-pool-hydration-v32",
            daemon=True,
        )
        self._batch_thread.start()
        type(self).last_instance = self

    @staticmethod
    def _decode_value(value) -> PumpSwapPoolAccount | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("PumpSwap pool account response is not an object")
        if value.get("owner") != PUMPSWAP_PROGRAM_ID:
            raise ValueError("PumpSwap pool account has unexpected owner")
        data = value.get("data")
        if not isinstance(data, (list, tuple)) or not data:
            raise ValueError("PumpSwap pool account missing base64 data")
        try:
            raw = base64.b64decode(str(data[0]), validate=True)
        except Exception as exc:
            raise ValueError("invalid PumpSwap pool account base64") from exc
        return decode_pumpswap_pool_account(raw)

    def _fetch_batch(self, items: list[tuple[str, Future]]) -> None:
        pools = [pool for pool, _ in items]
        try:
            result = self.client.call(
                "getMultipleAccounts",
                [pools, {"encoding": "base64", "commitment": self.commitment}],
            ) or {}
            values = result.get("value") if isinstance(result, dict) else None
            if not isinstance(values, list) or len(values) != len(items):
                raise SolanaRPCError("getMultipleAccounts returned invalid value count")
            decoded = [self._decode_value(value) for value in values]
        except BaseException as exc:
            for _, future in items:
                if not future.done():
                    future.set_exception(exc)
            return

        with self._batch_metrics_lock:
            self.network_batch_calls += 1
            self.network_batch_sizes.append(len(items))
        for (_, future), account in zip(items, decoded):
            if not future.done():
                future.set_result(account)

    def _batch_loop(self) -> None:
        max_wait = self.hydration_batch_max_wait_ms / 1000.0
        while True:
            first = self._batch_queue.get()
            items = [first]
            started = time.monotonic()
            while len(items) < self.hydration_batch_size:
                remaining = max_wait - (time.monotonic() - started)
                if remaining <= 0:
                    break
                try:
                    items.append(self._batch_queue.get(timeout=remaining))
                except queue.Empty:
                    break
            try:
                self._fetch_batch(items)
            finally:
                for _ in items:
                    self._batch_queue.task_done()

    def _load_pool_account(self, pool_address: str) -> PumpSwapPoolAccount | None:
        now = time.monotonic()
        with self._budget_lock:
            retry_at = self._failed_until.get(pool_address)
            if retry_at is not None and now < retry_at:
                self.negative_cache_skips += 1
                raise ValueError("negative-cache skip")
            if self.network_hydration_calls >= self.max_network_hydrations:
                self.hydration_budget_skips += 1
                raise ValueError("hydration budget exhausted")
            self.network_hydration_calls += 1

        future: Future = Future()
        self._batch_queue.put((pool_address, future))
        try:
            result = future.result()
        except (SolanaRPCError, ValueError, TypeError, KeyError):
            with self._budget_lock:
                self._failed_until[pool_address] = now + self.retry_seconds
            raise

        with self._budget_lock:
            if result is None:
                self._failed_until[pool_address] = now + self.retry_seconds
            else:
                self._failed_until.pop(pool_address, None)
        return result

    @property
    def average_network_batch_size(self) -> float:
        with self._batch_metrics_lock:
            if not self.network_batch_sizes:
                return 0.0
            return sum(self.network_batch_sizes) / len(self.network_batch_sizes)

    @property
    def max_network_batch_size(self) -> int:
        with self._batch_metrics_lock:
            return max(self.network_batch_sizes, default=0)
