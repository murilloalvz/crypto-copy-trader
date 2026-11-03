from src.pumpswap_pool_store import (
    PumpSwapPoolMapping,
    load_known_pumpswap_pool_mapping,
    load_pumpswap_pool_mapping,
    record_pumpswap_pool_mapping,
)
from src.pumpswap_stream import PumpSwapPoolResolver


class ReusablePumpSwapPoolResolver(PumpSwapPoolResolver):
    """PumpSwap resolver that causally reuses immutable pool identity learned in prior runs.

    The live PumpSwap smoke showed that rehydrating every pre-existing pool would consume roughly
    one getAccountInfo call per newly seen pool. Pool identity itself is stable, so an identity that
    was already learned before the current T0 is reusable without another network request.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.historical_store_hits = 0

    async def resolve(self, pool_address: str, *, as_of: int) -> PumpSwapPoolMapping | None:
        pool = str(pool_address).strip()
        if not pool:
            raise ValueError("pool_address cannot be empty")
        decision_time = int(as_of)
        if decision_time < 0:
            raise ValueError("as_of must be non-negative")

        cached = self._cache.get(pool)
        if cached is not None and cached.observed_at <= decision_time:
            self.cache_hits += 1
            return cached

        current = load_pumpswap_pool_mapping(
            acquisition_run_key=self.acquisition_run_key,
            pool_address=pool,
            as_of=decision_time,
        )
        if current is not None:
            self.store_hits += 1
            self._cache[pool] = current
            return current

        historical = load_known_pumpswap_pool_mapping(
            pool_address=pool,
            as_of=decision_time,
        )
        if historical is not None:
            record_pumpswap_pool_mapping(
                acquisition_run_key=self.acquisition_run_key,
                pool_address=pool,
                base_mint=historical.base_mint,
                quote_mint=historical.quote_mint,
                observed_at=historical.observed_at,
                source_provider=f"historical:{historical.source_provider}",
            )
            reused = PumpSwapPoolMapping(
                acquisition_run_key=self.acquisition_run_key,
                pool_address=pool,
                base_mint=historical.base_mint,
                quote_mint=historical.quote_mint,
                observed_at=historical.observed_at,
                source_provider=f"historical:{historical.source_provider}",
            )
            self.historical_store_hits += 1
            self._cache[pool] = reused
            return reused

        return await super().resolve(pool, as_of=decision_time)
