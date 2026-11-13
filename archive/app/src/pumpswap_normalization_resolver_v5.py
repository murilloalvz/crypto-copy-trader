from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time

from src import pumpswap_pool_store
from src.pumpswap_resolver_wait_trace_v53 import _caller_class
from src.solana import SolanaRPCError


@dataclass(frozen=True)
class NormalizationResolverSnapshotV5:
    normalization_cache_hits: int
    normalization_current_store_hits: int
    normalization_historical_promotions: int
    normalization_network_resolutions: int
    delayed_availability_reuses: int
    coalesced_after_pool_lock_reuses: int
    create_pool_durable_learns: int
    create_pool_reuses: int


class CoalescedNormalizationPoolResolutionMixinV5:
    """Resolve PumpSwap identity once per pool while preserving causal availability.

    Tailfix v4 exposed two independent stampede risks in the normalization path:

    * the v3 historical-reuse path ran before the per-pool single-flight lock, so concurrent
      notifications could all promote the same historical identity into the current run;
    * after one RPC resolution learned an immutable identity, an older notification already queued
      for normalization could fail the strict ``as_of`` cache check and perform the same expensive
      resolution again even though downstream persistence already clamps the trade's effective
      ``observed_at`` to ``max(notification.observed_at, mapping.observed_at)``.

    V5 adds a normalization-specific resolver contract. Historical lookup remains strictly bounded
    by the notification's observed time, so prior-run information is never pulled from the future.
    Once an identity has actually become durable in the *current* process/run, however, later
    normalization work may reuse it even when that notification itself was observed earlier; the
    existing normalized-trade contract publishes that event no earlier than the mapping's own
    observed_at. This is delayed availability, not backdating.

    Historical promotion and RPC resolution both occur inside the existing per-pool lock. That turns
    same-pool concurrency into one durable write followed by cache/store reuse instead of N duplicate
    writes. SQLite work remains off the event loop through the inherited v3 helpers.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Reuse v3's thread-safe stage counter lock/storage so snapshots remain coherent with the
        # inherited resolver diagnostics and cancellation accounting.
        for key in (
            "v5_normalization_cache_hits",
            "v5_normalization_current_store_hits",
            "v5_normalization_historical_promotions",
            "v5_normalization_network_resolutions",
            "v5_delayed_availability_reuses",
            "v5_coalesced_after_pool_lock_reuses",
            "v5_create_pool_durable_learns",
            "v5_create_pool_reuses",
        ):
            self._v3_count(key, 0)

    def _v5_cache_for_normalization(self, pool: str, decision_time: int):
        cached = self._cache.get(pool)
        if cached is None:
            return None
        self.cache_hits += 1
        self._v3_count("v5_normalization_cache_hits")
        if int(cached.observed_at) > decision_time:
            self._v3_count("v5_delayed_availability_reuses")
        return cached

    async def _v5_current_mapping_any_time(self, pool: str):
        return await self._v3_to_thread(
            "current_store_lookup",
            pumpswap_pool_store.load_pumpswap_pool_mapping,
            acquisition_run_key=self.acquisition_run_key,
            pool_address=pool,
        )

    def _v5_accept_current_mapping(self, mapping, *, decision_time: int):
        self.store_hits += 1
        self._v3_count("current_store_hits")
        self._v3_count("v5_normalization_current_store_hits")
        if int(mapping.observed_at) > decision_time:
            self._v3_count("v5_delayed_availability_reuses")
        self._cache[mapping.pool_address] = mapping
        return mapping

    async def resolve_for_normalization_v5(self, pool_address: str, *, observed_at: int):
        """Resolve one trade pool for causal normalization, with delayed-availability clamping.

        Prior-run historical evidence is still constrained to ``observed_at``. Current-run evidence
        that is already durable may be reused regardless of its own timestamp because the caller
        persists the normalized trade at the later of the notification and mapping timestamps.
        """

        caller = _caller_class()
        total_started = time.monotonic()
        pool = str(pool_address).strip()
        if not pool:
            raise ValueError("pool_address cannot be empty")
        decision_time = int(observed_at)
        if decision_time < 0:
            raise ValueError("observed_at must be non-negative")

        try:
            cached = self._v5_cache_for_normalization(pool, decision_time)
            if cached is not None:
                return cached

            current = await self._v5_current_mapping_any_time(pool)
            if current is not None:
                return self._v5_accept_current_mapping(
                    current,
                    decision_time=decision_time,
                )

            lock = self._pool_locks.setdefault(pool, asyncio.Lock())
            waited_for_lock = lock.locked()
            if waited_for_lock:
                self.singleflight_waits += 1
            async with lock:
                cached = self._v5_cache_for_normalization(pool, decision_time)
                if cached is not None:
                    if waited_for_lock:
                        self._v3_count("v5_coalesced_after_pool_lock_reuses")
                    return cached

                current = await self._v5_current_mapping_any_time(pool)
                if current is not None:
                    if waited_for_lock:
                        self._v3_count("v5_coalesced_after_pool_lock_reuses")
                    return self._v5_accept_current_mapping(
                        current,
                        decision_time=decision_time,
                    )

                # Historical evidence remains strict. A row learned after this notification is not
                # reused merely because immutable pool identity eventually became known.
                historical = await self._v3_historical_mapping(pool, decision_time)
                if historical is not None:
                    canonical = await self._v3_durable_mapping(
                        pool=pool,
                        base_mint=historical.base_mint,
                        quote_mint=historical.quote_mint,
                        observed_at=historical.observed_at,
                        source_provider=f"historical:{historical.source_provider}",
                    )
                    self.historical_store_hits += 1
                    self._v3_count("historical_store_hits")
                    self._v3_count("v5_normalization_historical_promotions")
                    self._cache[pool] = canonical
                    return canonical

                self.hydration_attempts += 1
                try:
                    network_started = time.monotonic()
                    async with self._resolution_semaphore:
                        account = await asyncio.to_thread(self._load_pool_account, pool)
                    self._v3_record_timing(
                        "network_account_wait",
                        time.monotonic() - network_started,
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
                self._v3_count("v5_normalization_network_resolutions")
                return canonical
        finally:
            elapsed = max(0.0, time.monotonic() - total_started)
            self._v3_record_timing("total_resolve", elapsed)
            with self._v53_metrics_lock:
                self._v53_timings[f"{caller}_resolve"].append(elapsed)

    async def learn_from_create_async_v5(self, event, *, observed_at: int):
        """Persist CreatePoolEvent identity without synchronous SQLite work on the event loop."""

        learned_at = int(observed_at)
        if learned_at < int(event.timestamp):
            raise ValueError("pool mapping observed_at cannot precede CreatePoolEvent timestamp")
        pool = str(event.pool).strip()
        if not pool:
            raise ValueError("CreatePoolEvent pool cannot be empty")

        lock = self._pool_locks.setdefault(pool, asyncio.Lock())
        if lock.locked():
            self.singleflight_waits += 1
        async with lock:
            current = await self._v5_current_mapping_any_time(pool)
            if current is not None:
                same_identity = (current.base_mint, current.quote_mint) == (
                    event.base_mint,
                    event.quote_mint,
                )
                if same_identity and learned_at >= int(current.observed_at):
                    self._cache[pool] = current
                    self._v3_count("v5_create_pool_reuses")
                    return current

            canonical = await self._v3_durable_mapping(
                pool=pool,
                base_mint=event.base_mint,
                quote_mint=event.quote_mint,
                observed_at=learned_at,
                source_provider="solana_logs_subscribe_create_pool",
            )
            self._cache[pool] = canonical
            self._v3_count("v5_create_pool_durable_learns")
            return canonical

    def normalization_resolver_snapshot_v5(self) -> NormalizationResolverSnapshotV5:
        with self._v3_stage_lock:
            return NormalizationResolverSnapshotV5(
                normalization_cache_hits=int(
                    self._v3_stage_counts["v5_normalization_cache_hits"]
                ),
                normalization_current_store_hits=int(
                    self._v3_stage_counts["v5_normalization_current_store_hits"]
                ),
                normalization_historical_promotions=int(
                    self._v3_stage_counts["v5_normalization_historical_promotions"]
                ),
                normalization_network_resolutions=int(
                    self._v3_stage_counts["v5_normalization_network_resolutions"]
                ),
                delayed_availability_reuses=int(
                    self._v3_stage_counts["v5_delayed_availability_reuses"]
                ),
                coalesced_after_pool_lock_reuses=int(
                    self._v3_stage_counts["v5_coalesced_after_pool_lock_reuses"]
                ),
                create_pool_durable_learns=int(
                    self._v3_stage_counts["v5_create_pool_durable_learns"]
                ),
                create_pool_reuses=int(
                    self._v3_stage_counts["v5_create_pool_reuses"]
                ),
            )
