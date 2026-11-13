from __future__ import annotations

import asyncio
from collections import defaultdict
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.pumpswap_concurrent_resolver import ConcurrentReusablePumpSwapPoolResolver
from src.pumpswap_causal_normalization_v5 import prepare_pumpswap_notification_causal_v5
from src.pumpswap_normalization_resolver_v5 import (
    CoalescedNormalizationPoolResolutionMixinV5,
)
from src.pumpswap_pool_store import (
    PumpSwapPoolMapping,
    load_pumpswap_pool_mapping,
    record_pumpswap_pool_mapping,
)
from src.pumpswap_resolver_latency_hardening_v3 import AsyncDurablePoolResolutionMixinV3
from src.pumpswap_stream import (
    PumpSwapCreatePoolEvent,
    PumpSwapLogNotification,
    PumpSwapPoolAccount,
    PumpSwapTradeEvent,
)


USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TOKEN = "Token1111111111111111111111111111111111111"


class ResolverUnderTest(
    CoalescedNormalizationPoolResolutionMixinV5,
    AsyncDurablePoolResolutionMixinV3,
    ConcurrentReusablePumpSwapPoolResolver,
):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # The production class also carries v53 tracing. Unit tests install the minimum compatible
        # telemetry surface so the v5 method exercises the same finally-path without pulling in the
        # entire hedged transport hierarchy.
        self._v53_metrics_lock = threading.Lock()
        self._v53_timings = defaultdict(list)


class PumpSwapNormalizationResolverV5Tests(unittest.IsolatedAsyncioTestCase):
    def _resolver(self, *, run_key: str = "run") -> ResolverUnderTest:
        return ResolverUnderTest(
            acquisition_run_key=run_key,
            client=SimpleNamespace(),
            max_concurrent_resolutions=4,
        )

    async def test_concurrent_historical_reuse_promotes_once_inside_pool_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "coalesced.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_pumpswap_pool_mapping(
                    acquisition_run_key="old-run",
                    pool_address="POOL",
                    base_mint=TOKEN,
                    quote_mint=USDC,
                    observed_at=100,
                    source_provider="historical",
                )
                resolver = self._resolver(run_key="new-run")
                results = await asyncio.gather(
                    *(
                        resolver.resolve_for_normalization_v5("POOL", observed_at=120)
                        for _ in range(12)
                    )
                )
                stored = load_pumpswap_pool_mapping(
                    acquisition_run_key="new-run",
                    pool_address="POOL",
                )

        self.assertTrue(all(item is not None for item in results))
        self.assertIsNotNone(stored)
        v3_snapshot = resolver.resolver_stage_snapshot_v3()
        v5_snapshot = resolver.normalization_resolver_snapshot_v5()
        self.assertEqual(v3_snapshot.mapping_sync_started, 1)
        self.assertEqual(v3_snapshot.mapping_sync_completed, 1)
        self.assertEqual(v5_snapshot.normalization_historical_promotions, 1)
        self.assertEqual(resolver.historical_store_hits, 1)

    async def test_current_run_mapping_can_be_reused_with_later_availability(self):
        resolver = self._resolver()
        resolver._cache["POOL"] = PumpSwapPoolMapping(
            acquisition_run_key="run",
            pool_address="POOL",
            base_mint=TOKEN,
            quote_mint=USDC,
            observed_at=130,
            source_provider="rpc",
        )

        mapping = await resolver.resolve_for_normalization_v5("POOL", observed_at=120)

        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(mapping.observed_at, 130)
        snapshot = resolver.normalization_resolver_snapshot_v5()
        self.assertEqual(snapshot.delayed_availability_reuses, 1)
        self.assertEqual(snapshot.normalization_cache_hits, 1)

    async def test_historical_mapping_after_notification_is_not_looked_ahead(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "no-lookahead.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                record_pumpswap_pool_mapping(
                    acquisition_run_key="future-run",
                    pool_address="POOL",
                    base_mint=TOKEN,
                    quote_mint=USDC,
                    observed_at=130,
                    source_provider="future",
                )
                resolver = self._resolver(run_key="new-run")
                resolver._load_pool_account = lambda _pool: None
                mapping = await resolver.resolve_for_normalization_v5(
                    "POOL",
                    observed_at=120,
                )

        self.assertIsNone(mapping)
        snapshot = resolver.normalization_resolver_snapshot_v5()
        self.assertEqual(snapshot.normalization_historical_promotions, 0)
        self.assertEqual(snapshot.normalization_network_resolutions, 0)

    async def test_queued_older_notifications_share_one_network_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "network-singleflight.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                resolver = self._resolver(run_key="run")
                calls = 0

                def load(_pool):
                    nonlocal calls
                    calls += 1
                    time.sleep(0.03)
                    return PumpSwapPoolAccount(base_mint=TOKEN, quote_mint=USDC)

                resolver._load_pool_account = load
                event_observed_at = int(time.time()) - 5
                results = await asyncio.gather(
                    *(
                        resolver.resolve_for_normalization_v5(
                            "POOL",
                            observed_at=event_observed_at,
                        )
                        for _ in range(10)
                    )
                )

        self.assertTrue(all(item is not None for item in results))
        self.assertEqual(calls, 1)
        self.assertEqual(resolver.hydration_successes, 1)
        v3_snapshot = resolver.resolver_stage_snapshot_v3()
        v5_snapshot = resolver.normalization_resolver_snapshot_v5()
        self.assertEqual(v3_snapshot.mapping_sync_started, 1)
        self.assertEqual(v5_snapshot.normalization_network_resolutions, 1)
        self.assertGreaterEqual(v5_snapshot.delayed_availability_reuses, 1)

    async def test_create_pool_learning_is_async_and_durable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "create.db"
            with patch.object(database, "settings", SimpleNamespace(database_path=path)):
                resolver = self._resolver(run_key="run")
                event = PumpSwapCreatePoolEvent(
                    pool="POOL",
                    creator="CREATOR",
                    base_mint=TOKEN,
                    quote_mint=USDC,
                    base_mint_decimals=6,
                    quote_mint_decimals=6,
                    timestamp=100,
                    event_index=0,
                )
                mapping = await resolver.learn_from_create_async_v5(
                    event,
                    observed_at=110,
                )
                stored = load_pumpswap_pool_mapping(
                    acquisition_run_key="run",
                    pool_address="POOL",
                )

        self.assertEqual(mapping.observed_at, 110)
        self.assertIsNotNone(stored)
        snapshot = resolver.normalization_resolver_snapshot_v5()
        self.assertEqual(snapshot.create_pool_durable_learns, 1)


class PumpSwapCausalNormalizationV5Tests(unittest.IsolatedAsyncioTestCase):
    async def test_trade_observed_at_is_clamped_to_mapping_availability(self):
        mapping = PumpSwapPoolMapping(
            acquisition_run_key="run",
            pool_address="POOL",
            base_mint=TOKEN,
            quote_mint=USDC,
            observed_at=130,
            source_provider="rpc",
        )

        class Resolver:
            acquisition_run_key = "run"

            async def resolve_for_normalization_v5(self, pool, *, observed_at):
                self.seen = (pool, observed_at)
                return mapping

        resolver = Resolver()
        notification = PumpSwapLogNotification(
            signature="sig",
            slot=1,
            observed_at=120,
            trade_events=(
                PumpSwapTradeEvent(
                    side="buy",
                    pool="POOL",
                    user="USER",
                    timestamp=110,
                    base_amount_raw=1,
                    quote_amount_raw=1,
                    event_index=0,
                ),
            ),
        )

        prepared = await prepare_pumpswap_notification_causal_v5(
            notification,
            acquisition_run_key="run",
            resolver=resolver,
        )

        self.assertEqual(resolver.seen, ("POOL", 120))
        self.assertEqual(len(prepared.trade_writes), 1)
        self.assertEqual(prepared.trade_writes[0].observation.observed_at, 130)

    async def test_lifecycle_uses_async_create_hook(self):
        class Resolver:
            acquisition_run_key = "run"

            def __init__(self):
                self.calls = []

            async def learn_from_create_async_v5(self, event, *, observed_at):
                self.calls.append((event.pool, observed_at))

        resolver = Resolver()
        notification = PumpSwapLogNotification(
            signature="sig-create",
            slot=1,
            observed_at=120,
            trade_events=(),
            lifecycle_events=(
                PumpSwapCreatePoolEvent(
                    pool="POOL",
                    creator="CREATOR",
                    base_mint=TOKEN,
                    quote_mint=USDC,
                    base_mint_decimals=6,
                    quote_mint_decimals=6,
                    timestamp=110,
                    event_index=0,
                ),
            ),
        )

        prepared = await prepare_pumpswap_notification_causal_v5(
            notification,
            acquisition_run_key="run",
            resolver=resolver,
        )

        self.assertEqual(resolver.calls, [("POOL", 120)])
        self.assertEqual(len(prepared.lifecycle_writes), 1)
        self.assertEqual(prepared.lifecycle_writes[0].observation.observed_at, 120)


if __name__ == "__main__":
    unittest.main()
