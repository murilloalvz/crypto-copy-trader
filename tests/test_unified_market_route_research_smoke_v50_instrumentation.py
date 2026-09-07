import contextlib
import io
import time
import unittest
from types import SimpleNamespace

import unified_market_route_research_smoke_v50 as v50


class UnifiedMarketRouteResearchSmokeV50InstrumentationTests(unittest.IsolatedAsyncioTestCase):
    async def test_v50_observes_v20_normalization_and_full_reservation_lifecycle(self):
        notification = SimpleNamespace(signature="sig-v50-integration")

        async def fake_stream_factory(**_kwargs):
            yield notification

        async def fake_v20_begin(_notification, *args, **kwargs):
            self.assertIs(_notification, notification)
            return SimpleNamespace(normalization_completed_monotonic=time.monotonic())

        async def fake_v49_run(**_kwargs):
            stream = v50.v19.iter_pumpswap_log_notifications()
            async for current in stream:
                await v50.v20.begin_pumpswap_notification_normalized_v5(
                    current,
                    acquisition_run_key="test-run",
                    resolver=None,
                    writer=None,
                    reservation_asset_index=object(),
                )
                scheduler = v50.ready_scheduler_module.ReadyAssetScheduler()
                reservation = scheduler.reserve(("asset-A",))
                scheduler.skip(reservation)

        original_stream = v50.v19.iter_pumpswap_log_notifications
        original_v20_begin = v50.v20.begin_pumpswap_notification_normalized_v5
        original_base = v50._BASE_V49_RUN_SMOKE
        v50.v19.iter_pumpswap_log_notifications = fake_stream_factory
        v50.v20.begin_pumpswap_notification_normalized_v5 = fake_v20_begin
        v50._BASE_V49_RUN_SMOKE = fake_v49_run
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                await v50.run_smoke_v50()
        finally:
            v50._BASE_V49_RUN_SMOKE = original_base
            v50.v20.begin_pumpswap_notification_normalized_v5 = original_v20_begin
            v50.v19.iter_pumpswap_log_notifications = original_stream

        text = output.getvalue()
        self.assertIn(
            "ingress=1 normalization=1 reservations=1 submit_or_skip=1",
            text,
        )
        self.assertIn("attributed_rows=1", text)
        self.assertIn("trace_attribution_complete=True", text)
        self.assertNotIn("dominant_clock=insufficient_trace", text)


if __name__ == "__main__":
    unittest.main()
