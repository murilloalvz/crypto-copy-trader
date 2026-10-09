from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import src.pumpswap_deferred_persistence_v5 as deferred_persistence
from src.pumpswap_causal_normalization_v5 import prepare_pumpswap_notification_causal_v5
from src.pumpswap_writer_headroom_v5 import InstrumentedPumpSwapSQLiteWriterV5
import unified_market_route_research_smoke_tailfix_v3 as tailfix_v3
import unified_market_route_research_smoke_tailfix_v4 as tailfix_v4
import unified_market_route_research_smoke_tailfix_v5 as v5


class _FakeResolver:
    def __init__(self):
        self.v5_snapshot = SimpleNamespace(
            normalization_cache_hits=20,
            normalization_current_store_hits=2,
            normalization_historical_promotions=3,
            normalization_network_resolutions=2,
            delayed_availability_reuses=4,
            coalesced_after_pool_lock_reuses=10,
            create_pool_durable_learns=1,
            create_pool_reuses=0,
        )
        self.v3_snapshot = SimpleNamespace(
            mapping_sync_started=6,
            mapping_sync_completed=6,
            mapping_sync_inflight=0,
        )

    def normalization_resolver_snapshot_v5(self):
        return self.v5_snapshot

    def resolver_stage_snapshot_v3(self):
        return self.v3_snapshot


class _FakeWriter:
    def __init__(
        self,
        *,
        queue_depth_p95=10.0,
        result_wait_p95_seconds=1.0,
        pending_at_close=0,
        queue_before_close=0,
        queue_high_water=255,
    ):
        self.snapshot = SimpleNamespace(
            queue_depth_p50=2.0,
            queue_depth_p95=float(queue_depth_p95),
            queue_wait_p95_seconds=0.5,
            result_wait_p95_seconds=float(result_wait_p95_seconds),
            batch_service_p95_seconds=0.1,
            base=SimpleNamespace(
                submitted=100,
                completed=100 - int(pending_at_close),
                pending_at_close=int(pending_at_close),
                queue_before_close=int(queue_before_close),
                queue_high_water=int(queue_high_water),
            ),
        )

    def headroom_snapshot_v5(self):
        return self.snapshot


class UnifiedMarketRouteResearchSmokeTailfixV5Tests(unittest.IsolatedAsyncioTestCase):
    async def _run_with_fake_writer(self, writer, *, pumpswap_workers=256):
        resolver = _FakeResolver()

        async def fake_v4(**kwargs):
            self.assertIs(
                tailfix_v3.HardenedTracedSharedTransportResolverV3,
                v5.HardenedNormalizationResolverV5,
            )
            self.assertIs(
                deferred_persistence.prepare_pumpswap_notification_normalized_v3,
                prepare_pumpswap_notification_causal_v5,
            )
            self.assertIs(
                tailfix_v4.InstrumentedPumpSwapSQLiteWriterV4,
                InstrumentedPumpSwapSQLiteWriterV5,
            )
            v5.HardenedNormalizationResolverV5.last_instance = resolver
            InstrumentedPumpSwapSQLiteWriterV5.last_instance = writer

        with patch.object(tailfix_v4, "run_smoke_tailfix_v4", side_effect=fake_v4):
            await v5.run_smoke_tailfix_v5(pumpswap_workers=pumpswap_workers)
        return resolver

    async def test_installs_and_restores_all_v5_systems_seams(self):
        original_resolver = tailfix_v3.HardenedTracedSharedTransportResolverV3
        original_prepare = deferred_persistence.prepare_pumpswap_notification_normalized_v3
        original_writer = tailfix_v4.InstrumentedPumpSwapSQLiteWriterV4

        await self._run_with_fake_writer(_FakeWriter())

        self.assertIs(tailfix_v3.HardenedTracedSharedTransportResolverV3, original_resolver)
        self.assertIs(deferred_persistence.prepare_pumpswap_notification_normalized_v3, original_prepare)
        self.assertIs(tailfix_v4.InstrumentedPumpSwapSQLiteWriterV4, original_writer)
        self.assertIsNotNone(v5.last_resolver_snapshot_v5)
        self.assertIsNotNone(v5.last_writer_headroom_v5)

    async def test_transient_high_water_alone_does_not_hold_promotion(self):
        await self._run_with_fake_writer(
            _FakeWriter(
                queue_depth_p95=20,
                result_wait_p95_seconds=1.2,
                queue_high_water=255,
            )
        )

        self.assertFalse(v5.last_writer_warning_v5)
        self.assertLess(v5.last_writer_queue_p95_share_v5, 0.80)

    async def test_sustained_queue_p95_pressure_warns(self):
        await self._run_with_fake_writer(
            _FakeWriter(queue_depth_p95=220, result_wait_p95_seconds=1.0)
        )
        self.assertTrue(v5.last_writer_warning_v5)
        self.assertGreaterEqual(v5.last_writer_queue_p95_share_v5, 0.80)

    async def test_four_second_writer_result_wait_warns(self):
        await self._run_with_fake_writer(
            _FakeWriter(queue_depth_p95=10, result_wait_p95_seconds=4.0)
        )
        self.assertTrue(v5.last_writer_warning_v5)

    async def test_incomplete_drain_warns(self):
        await self._run_with_fake_writer(
            _FakeWriter(
                queue_depth_p95=10,
                result_wait_p95_seconds=1.0,
                pending_at_close=1,
                queue_before_close=1,
            )
        )
        self.assertTrue(v5.last_writer_warning_v5)

    async def test_restores_all_systems_seams_on_exception(self):
        original_resolver = tailfix_v3.HardenedTracedSharedTransportResolverV3
        original_prepare = deferred_persistence.prepare_pumpswap_notification_normalized_v3
        original_writer = tailfix_v4.InstrumentedPumpSwapSQLiteWriterV4

        async def explode(**kwargs):
            raise RuntimeError("boom")

        with patch.object(tailfix_v4, "run_smoke_tailfix_v4", side_effect=explode):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                await v5.run_smoke_tailfix_v5(pumpswap_workers=256)

        self.assertIs(tailfix_v3.HardenedTracedSharedTransportResolverV3, original_resolver)
        self.assertIs(deferred_persistence.prepare_pumpswap_notification_normalized_v3, original_prepare)
        self.assertIs(tailfix_v4.InstrumentedPumpSwapSQLiteWriterV4, original_writer)


if __name__ == "__main__":
    unittest.main()
