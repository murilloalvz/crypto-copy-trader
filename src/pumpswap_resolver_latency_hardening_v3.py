from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
import threading
import time

from src import pumpswap_pool_store
from src.pumpswap_resolver_wait_trace_v53 import _caller_class
from src.solana import SolanaRPCError
from src.sqlite_write_admission import RESOLUTION_PRIORITY, sqlite_write_admission


@dataclass(frozen=True)
class ResolverStageSnapshotV3:
    current_store_lookup_seconds: tuple[float, ...]
    historical_store_lookup_seconds: tuple[float, ...]
    network_account_wait_seconds: tuple[float, ...]
    durable_mapping_write_seconds: tuple[float, ...]
    canonical_reload_seconds: tuple[float, ...]
    pool_lock_hold_seconds: tuple[float, ...]
    total_resolve_seconds: tuple[float, ...]
    durable_mapping_writes: int
    current_store_hits: int
    historical_store_hits: int
    network_resolutions: int
    event_loop_store_calls: int


class AsyncDurablePoolResolutionMixinV3:
    """Keep durable pool identity semantics while moving SQLite work off the event loop.

    The inherited resolver is causally correct, but its per-pool single-flight critical section
    performs synchronous SQLite lookups, writes and a canonical reload. Under WAL writer contention
    that can suspend the asyncio loop and, because reservation identity is not yet known, amplify one
    slow pool into a global reservation-sequence hole.

    V3 preserves the same cache, historical reuse, per-pool lock, expensive-resolution semaphore,
    hydration budget, earliest-observed canonical mapping and explicit unresolved behavior. SQLite
    stages execute through ``asyncio.to_thread``. The same-pool lock is intentionally held until the
    canonical mapping is durably committed and reloaded; V3 never publishes an in-memory identity
    before durability.

    Pool-identity writes use the global writer gate's ``resolution`` priority because they are a
    causal prerequisite for normalization/reservation. The gate still has one physical writer and
    the resolver's existing concurrency ceiling bounds how many identity writers can contend. Reads
    remain outside that writer gate and concurrent under WAL.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._v3_stage_lock = threading.Lock()
        self._v3_stage_timings: dict[str, list[float]] = defaultdict(list)
        self._v3_stage_counts: dict[str, int] = defaultdict(int)

    def _v3_record_timing(self, name: str, seconds: float) -> None:
        with self._v3_stage_lock:
            self._v3_stage_timings[name].append(max(0.0, seconds))

    def _v3_count(self, name: str, amount: int = 1) -> None:
        with self._v3_stage_lock:
            self._v3_stage_counts[name] += int(amount)

    async def _v3_to_thread(self, stage: str, function, /, *args, **kwargs):
        started = time.monotonic()
        try:
            return await asyncio.to_thread(function, *args, **kwargs)
        finally:
            self._v3_record_timing(stage, time.monotonic() - started)

    def _v3_record_mapping_sync(
        self,
        *,
        pool: str,
        base_mint: str,
        quote_mint: str,
        observed_at: int,
        source_provider: str,
    ) -> None:
        # Call the store module directly so V28's by-value monkey patches cannot accidentally nest
        # the same non-reentrant admission gate. Resolution priority changes admission only.
        with sqlite_write_admission(RESOLUTION_PRIORITY):
            pumpswap_pool_store.record_pumpswap_pool_mapping(
                acquisition_run_key=self.acquisition_run_key,
                pool_address=pool,
                base_mint=base_mint,
                quote_mint=quote_mint,
                observed_at=int(observed_at),
                source_provider=source_provider,
            )

    async def _v3_current_mapping(self, pool: str, decision_time: int):
        return await self._v3_to_thread(
            "current_store_lookup",
            pumpswap_pool_store.load_pumpswap_pool_mapping,
            acquisition_run_key=self.acquisition_run_key,
            pool_address=pool,
            as_of=decision_time,
        )

    async def _v3_historical_mapping(self, pool: str, decision_time: int):
        return await self._v3_to_thread(
            "historical_store_lookup",
            pumpswap_pool_store.load_known_pumpswap_pool_mapping,
            pool_address=pool,
            as_of=decision_time,
        )

    async def _v3_durable_mapping(
        self,
        *,
        pool: str,
        base_mint: str,
        quote_mint: str,
        observed_at: int,
        source_provider: str,
    ):
        await self._v3_to_thread(
            "durable_mapping_write",
            self._v3_record_mapping_sync,
            pool=pool,
            base_mint=base_mint,
            quote_mint=quote_mint,
            observed_at=observed_at,
            source_provider=source_provider,
        )
        self._v3_count("durable_mapping_writes")
        canonical = await self._v3_to_thread(
            "canonical_reload",
            pumpswap_pool_store.load_pumpswap_pool_mapping,
            acquisition_run_key=self.acquisition_run_key,
            pool_address=pool,
        )
        if canonical is None:
            raise RuntimeError("durable PumpSwap pool mapping disappeared after persistence")
        return canonical

    async def _v3_lookup_known(self, pool: str, decision_time: int):
        current = await self._v3_current_mapping(pool, decision_time)
        if current is not None:
            self.store_hits += 1
            self._cache[pool] = current
            self._v3_count("current_store_hits")
            return current

        historical = await self._v3_historical_mapping(pool, decision_time)
        if historical is None:
            return None

        canonical = await self._v3_durable_mapping(
            pool=pool,
            base_mint=historical.base_mint,
            quote_mint=historical.quote_mint,
            observed_at=historical.observed_at,
            source_provider=f"historical:{historical.source_provider}",
        )
        self.historical_store_hits += 1
        self._cache[pool] = canonical
        self._v3_count("historical_store_hits")
        return canonical

    async def resolve(self, pool_address: str, *, as_of: int):
        caller = _caller_class()
        total_started = time.monotonic()
        pool = str(pool_address).strip()
        if not pool:
            raise ValueError("pool_address cannot be empty")
        decision_time = int(as_of)
        if decision_time < 0:
            raise ValueError("as_of must be non-negative")

        try:
            cached = self._causal_cache_hit(pool, as_of=decision_time)
            if cached is not None:
                return cached

            known = await self._v3_lookup_known(pool, decision_time)
            if known is not None:
                return known

            lock = self._pool_locks.setdefault(pool, asyncio.Lock())
            if lock.locked():
                self.singleflight_waits += 1
            async with lock:
                lock_acquired = time.monotonic()
                try:
                    cached = self._causal_cache_hit(pool, as_of=decision_time)
                    if cached is not None:
                        return cached
                    known = await self._v3_lookup_known(pool, decision_time)
                    if known is not None:
                        return known

                    self.hydration_attempts += 1
                    try:
                        network_started = time.monotonic()
                        async with self._resolution_semaphore:
                            account = await asyncio.to_thread(self._load_pool_account, pool)
                        self._v3_record_timing(
                            "network_account_wait", time.monotonic() - network_started
                        )
                    except (SolanaRPCError, ValueError, TypeError, KeyError):
                        self.hydration_failures += 1
                        return None

                    if account is None:
                        self.hydration_failures += 1
                        return None

                    learned_at = int(time.time())
                    canonical = await self._v3_durable_mapping(
                        pool=pool,
                        base_mint=account.base_mint,
                        quote_mint=account.quote_mint,
                        observed_at=learned_at,
                        source_provider="solana_get_account_info",
                    )
                    self._cache[pool] = canonical
                    self.hydration_successes += 1
                    self._v3_count("network_resolutions")
                    return canonical
                finally:
                    self._v3_record_timing(
                        "pool_lock_hold", time.monotonic() - lock_acquired
                    )
        finally:
            elapsed = max(0.0, time.monotonic() - total_started)
            self._v3_record_timing("total_resolve", elapsed)
            with self._v53_metrics_lock:
                self._v53_timings[f"{caller}_resolve"].append(elapsed)

    def resolver_stage_snapshot_v3(self) -> ResolverStageSnapshotV3:
        with self._v3_stage_lock:
            return ResolverStageSnapshotV3(
                current_store_lookup_seconds=tuple(
                    self._v3_stage_timings["current_store_lookup"]
                ),
                historical_store_lookup_seconds=tuple(
                    self._v3_stage_timings["historical_store_lookup"]
                ),
                network_account_wait_seconds=tuple(
                    self._v3_stage_timings["network_account_wait"]
                ),
                durable_mapping_write_seconds=tuple(
                    self._v3_stage_timings["durable_mapping_write"]
                ),
                canonical_reload_seconds=tuple(
                    self._v3_stage_timings["canonical_reload"]
                ),
                pool_lock_hold_seconds=tuple(
                    self._v3_stage_timings["pool_lock_hold"]
                ),
                total_resolve_seconds=tuple(
                    self._v3_stage_timings["total_resolve"]
                ),
                durable_mapping_writes=int(
                    self._v3_stage_counts["durable_mapping_writes"]
                ),
                current_store_hits=int(self._v3_stage_counts["current_store_hits"]),
                historical_store_hits=int(
                    self._v3_stage_counts["historical_store_hits"]
                ),
                network_resolutions=int(self._v3_stage_counts["network_resolutions"]),
                event_loop_store_calls=0,
            )
