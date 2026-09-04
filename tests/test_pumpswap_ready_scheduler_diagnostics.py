import asyncio
import unittest

from src.pumpswap_ready_scheduler import ReadyAssetScheduler


class ReadyAssetSchedulerDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def test_dependency_timestamps_and_hot_asset_telemetry(self):
        scheduler = ReadyAssetScheduler[str]()
        a0 = scheduler.reserve(["A"])
        a1 = scheduler.reserve(["A"])
        scheduler.submit("a0", a0)
        scheduler.submit("a1", a1)

        first = await asyncio.wait_for(scheduler.get_ready(), timeout=0.2)
        self.assertEqual(first.payload, "a0")
        self.assertGreaterEqual(
            first.dependency_ready_monotonic, first.reservation.created_monotonic
        )
        self.assertGreaterEqual(
            first.ready_queue_entered_monotonic, first.dependency_ready_monotonic
        )

        await asyncio.sleep(0.01)
        await scheduler.complete(first.reservation)
        scheduler.ready_task_done()

        second = await asyncio.wait_for(scheduler.get_ready(), timeout=0.2)
        self.assertEqual(second.payload, "a1")
        self.assertGreater(
            second.dependency_ready_monotonic - second.reservation.created_monotonic,
            0.0,
        )
        await scheduler.complete(second.reservation)
        scheduler.ready_task_done()

        snapshot = scheduler.snapshot()
        asset = next(item for item in snapshot.asset_telemetry if item.asset == "A")
        self.assertEqual(asset.reservations, 2)
        self.assertGreaterEqual(asset.max_outstanding_tickets, 2)
        self.assertGreaterEqual(asset.max_waiting_jobs, 1)
        self.assertGreaterEqual(asset.dependency_wait_count, 1)
        self.assertGreater(asset.dependency_wait_total_seconds, 0.0)
        self.assertGreater(asset.dependency_wait_p95_seconds, 0.0)
        await scheduler.cancel_waiters()

    async def test_unrelated_asset_has_no_artificial_causal_wait(self):
        scheduler = ReadyAssetScheduler[str]()
        a0 = scheduler.reserve(["A"])
        b0 = scheduler.reserve(["B"])
        scheduler.submit("a0", a0)
        scheduler.submit("b0", b0)

        first = await asyncio.wait_for(scheduler.get_ready(), timeout=0.2)
        second = await asyncio.wait_for(scheduler.get_ready(), timeout=0.2)
        self.assertEqual({first.payload, second.payload}, {"a0", "b0"})

        snapshot = scheduler.snapshot()
        telemetry = {item.asset: item for item in snapshot.asset_telemetry}
        self.assertEqual(telemetry["A"].dependency_wait_count, 0)
        self.assertEqual(telemetry["B"].dependency_wait_count, 0)

        await scheduler.complete(first.reservation)
        scheduler.ready_task_done()
        await scheduler.complete(second.reservation)
        scheduler.ready_task_done()
        await scheduler.cancel_waiters()

    async def test_pre_cancel_snapshot_includes_active_wait_age(self):
        scheduler = ReadyAssetScheduler[str]()
        a0 = scheduler.reserve(["A"])
        a1 = scheduler.reserve(["A"])
        scheduler.submit("a0", a0)
        scheduler.submit("a1", a1)

        first = await asyncio.wait_for(scheduler.get_ready(), timeout=0.2)
        self.assertEqual(first.payload, "a0")
        await asyncio.sleep(0.01)
        await scheduler.cancel_waiters()

        snapshot = scheduler.pre_cancel_snapshot()
        asset = next(item for item in snapshot.asset_telemetry if item.asset == "A")
        self.assertEqual(snapshot.waiting_backlog, 1)
        self.assertEqual(asset.active_waiting_jobs, 1)
        self.assertGreater(asset.dependency_wait_total_seconds, 0.0)
        self.assertGreaterEqual(asset.max_waiting_jobs, 1)


if __name__ == "__main__":
    unittest.main()
