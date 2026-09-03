import asyncio

from src.pumpswap_pool_store import PumpSwapPoolMapping
from src.pumpswap_reusable_resolver import ReusablePumpSwapPoolResolver


class ConcurrentReusablePumpSwapPoolResolver(ReusablePumpSwapPoolResolver):
    """Bound concurrent pool resolution and single-flight each pool address.

    Different unknown pools may hydrate concurrently, while repeated trades for the same pool wait
    behind one resolution path and then reuse the resulting cache/store mapping.
    """

    def __init__(self, *args, max_concurrent_resolutions: int = 8, **kwargs):
        if max_concurrent_resolutions <= 0:
            raise ValueError("max_concurrent_resolutions must be positive")
        super().__init__(*args, **kwargs)
        self.max_concurrent_resolutions = int(max_concurrent_resolutions)
        self._resolution_semaphore = asyncio.Semaphore(self.max_concurrent_resolutions)
        self._pool_locks: dict[str, asyncio.Lock] = {}
        self.singleflight_waits = 0

    async def resolve(self, pool_address: str, *, as_of: int) -> PumpSwapPoolMapping | None:
        pool = str(pool_address).strip()
        if not pool:
            raise ValueError("pool_address cannot be empty")

        lock = self._pool_locks.setdefault(pool, asyncio.Lock())
        if lock.locked():
            self.singleflight_waits += 1
        async with lock:
            async with self._resolution_semaphore:
                return await super().resolve(pool, as_of=as_of)
