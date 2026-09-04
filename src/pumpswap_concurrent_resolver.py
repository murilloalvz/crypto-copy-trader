import asyncio

from src.pumpswap_pool_store import (
    PumpSwapPoolMapping,
    load_pumpswap_pool_mapping,
    record_pumpswap_pool_mapping,
)
from src.pumpswap_reusable_resolver import ReusablePumpSwapPoolResolver


class ConcurrentReusablePumpSwapPoolResolver(ReusablePumpSwapPoolResolver):
    """Bound concurrent pool resolution and single-flight each pool address.

    Different unknown pools may hydrate concurrently, while repeated trades for the same pool wait
    behind one resolution path and then reuse the resulting cache/store mapping. CreatePoolEvent
    learning uses the same causal replay policy as the shared pool store so an earlier on-chain
    observation can safely supersede a later RPC completion without aborting acquisition.

    The concurrency semaphore protects only potentially expensive resolution work. A causally valid
    in-memory cache hit is returned before both the per-pool lock and global semaphore so the common
    cheap path cannot queue behind unrelated network hydrations.
    """

    def __init__(self, *args, max_concurrent_resolutions: int = 8, **kwargs):
        if max_concurrent_resolutions <= 0:
            raise ValueError("max_concurrent_resolutions must be positive")
        super().__init__(*args, **kwargs)
        self.max_concurrent_resolutions = int(max_concurrent_resolutions)
        self._resolution_semaphore = asyncio.Semaphore(self.max_concurrent_resolutions)
        self._pool_locks: dict[str, asyncio.Lock] = {}
        self.singleflight_waits = 0

    def _causal_cache_hit(
        self,
        pool: str,
        *,
        as_of: int,
    ) -> PumpSwapPoolMapping | None:
        cached = self._cache.get(pool)
        if cached is None or cached.observed_at > as_of:
            return None
        self.cache_hits += 1
        return cached

    def learn_from_create(self, event, *, observed_at: int) -> PumpSwapPoolMapping:
        learned_at = int(observed_at)
        if learned_at < int(event.timestamp):
            raise ValueError("pool mapping observed_at cannot precede CreatePoolEvent timestamp")

        record_pumpswap_pool_mapping(
            acquisition_run_key=self.acquisition_run_key,
            pool_address=event.pool,
            base_mint=event.base_mint,
            quote_mint=event.quote_mint,
            observed_at=learned_at,
            source_provider="solana_logs_subscribe_create_pool",
        )
        canonical = load_pumpswap_pool_mapping(
            acquisition_run_key=self.acquisition_run_key,
            pool_address=event.pool,
        )
        if canonical is None:
            raise RuntimeError("PumpSwap CreatePoolEvent mapping disappeared after persistence")
        self._cache[event.pool] = canonical
        return canonical

    async def resolve(self, pool_address: str, *, as_of: int) -> PumpSwapPoolMapping | None:
        pool = str(pool_address).strip()
        if not pool:
            raise ValueError("pool_address cannot be empty")
        decision_time = int(as_of)
        if decision_time < 0:
            raise ValueError("as_of must be non-negative")

        cached = self._causal_cache_hit(pool, as_of=decision_time)
        if cached is not None:
            return cached

        lock = self._pool_locks.setdefault(pool, asyncio.Lock())
        if lock.locked():
            self.singleflight_waits += 1
        async with lock:
            # Another same-pool resolution may have populated the canonical cache while this
            # coroutine waited for the single-flight lock. Re-check before spending a global slot.
            cached = self._causal_cache_hit(pool, as_of=decision_time)
            if cached is not None:
                return cached

            async with self._resolution_semaphore:
                resolved = await super().resolve(pool, as_of=decision_time)
            if resolved is None:
                return None

            # A CreatePoolEvent can race an RPC hydration because create learning is synchronous
            # while trade resolution is async. The store owns the canonical earliest-observed
            # mapping, so reload it before normalization/cache use instead of returning a stale
            # object assembled by whichever worker completed first.
            canonical = load_pumpswap_pool_mapping(
                acquisition_run_key=self.acquisition_run_key,
                pool_address=pool,
            )
            if canonical is None:
                raise RuntimeError("resolved PumpSwap pool mapping disappeared after persistence")
            self._cache[pool] = canonical
            return canonical
