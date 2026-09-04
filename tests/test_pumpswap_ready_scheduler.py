import asyncio
import unittest

from src.pumpswap_ready_scheduler import ReadyAssetScheduler


class ReadyAssetSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_waiting_reservation_does_not_block_ready_unrelated_asset(self):
        scheduler = ReadyAssetScheduler[str]()
        a0 = scheduler.reserve(["A"])
        a1 = scheduler.reserve(["A"])
        b0 = scheduler.reserve(["B"])
        scheduler.submit("a0", a0)
        scheduler.submit("a1", a1)
        scheduler.submit("b0", b0)

        first = await asyncio.wait_for(scheduler.get_ready(), timeout=0.2)
        second = await asyncio.wait_for(scheduler.get_ready(), timeout=0.2)
        self.assertEqual({first.payload, second.payload}, {"a0", "b0"})
        self.assertEqual(scheduler.waiting_backlog(), 1)

        if first.payload == "a0":
            await scheduler.complete(first.reservation)
        else:
            await scheduler.complete(second.reservation)
        third = await asyncio.wait_for(scheduler.get_ready(), timeout=0.2)
        self.assertEqual(third.payload, "a1")
        await scheduler.cancel_waiters()

    async def test_multi_asset_waits_for_both_predecessors(self):
        scheduler = ReadyAssetScheduler[str]()
        a0 = scheduler.reserve(["A"])
        b0 = scheduler.reserve(["B"])
        ab1 = scheduler.reserve(["A", "B"])
        scheduler.submit("a0", a0)
        scheduler.submit("b0", b0)
        scheduler.submit("ab1", ab1)

        ready1 = await asyncio.wait_for(scheduler.get_ready(), timeout=0.2)
        ready2 = await asyncio.wait_for(scheduler.get_ready(), timeout=0.2)
        self.assertEqual({ready1.payload, ready2.payload}, {"a0", "b0"})
        self.assertEqual(scheduler.waiting_backlog(), 1)

        await scheduler.complete(ready1.reservation)
        await asyncio.sleep(0)
        self.assertEqual(scheduler.waiting_backlog(), 1)
        await scheduler.complete(ready2.reservation)
        ready3 = await asyncio.wait_for(scheduler.get_ready(), timeout=0.2)
        self.assertEqual(ready3.payload, "ab1")
        await scheduler.cancel_waiters()

    async def test_empty_asset_reservation_is_immediately_ready(self):
        scheduler = ReadyAssetScheduler[str]()
        reservation = scheduler.reserve([])
        scheduler.submit("empty", reservation)
        ready = await asyncio.wait_for(scheduler.get_ready(), timeout=0.2)
        self.assertEqual(ready.payload, "empty")
        await scheduler.complete(ready.reservation)
        await scheduler.cancel_waiters()

    async def test_ready_reservation_enters_queue_without_async_waiter_turn(self):
        scheduler = ReadyAssetScheduler[str]()
        reservation = scheduler.reserve(["A"])

        scheduler.submit("a0", reservation)

        self.assertEqual(scheduler.ready_backlog(), 1)
        self.assertEqual(scheduler.waiting_backlog(), 0)
        ready = scheduler._ready.get_nowait()
        self.assertEqual(ready.payload, "a0")
        self.assertEqual(ready.waiter_started_monotonic, ready.dependency_ready_monotonic)
        self.assertEqual(ready.dependency_ready_monotonic, ready.ready_queue_entered_monotonic)
        scheduler.ready_task_done()
        await scheduler.complete(ready.reservation)
        await scheduler.cancel_waiters()

    async def test_hot_asset_chain_releases_exactly_one_successor_per_completion(self):
        scheduler = ReadyAssetScheduler[str]()
        reservations = [scheduler.reserve(["HOT"]) for _ in range(50)]
        for index, reservation in enumerate(reservations):
            scheduler.submit(f"hot-{index}", reservation)

        self.assertEqual(scheduler.ready_backlog(), 1)
        self.assertEqual(scheduler.waiting_backlog(), 49)

        for index in range(50):
            ready = scheduler._ready.get_nowait()
            self.assertEqual(ready.payload, f"hot-{index}")
            scheduler.ready_task_done()
            await scheduler.complete(ready.reservation)
            self.assertEqual(scheduler.waiting_backlog(), max(0, 48 - index))
            if index < 49:
                self.assertEqual(scheduler.ready_backlog(), 1)

        self.assertEqual(scheduler.ready_backlog(), 0)
        await scheduler.cancel_waiters()

    async def test_multi_asset_pending_job_releases_only_after_last_exact_successor(self):
        scheduler = ReadyAssetScheduler[str]()
        a0 = scheduler.reserve(["A"])
        b0 = scheduler.reserve(["B"])
        ab1 = scheduler.reserve(["A", "B"])
        scheduler.submit("a0", a0)
        scheduler.submit("b0", b0)
        scheduler.submit("ab1", ab1)

        ready_a = scheduler._ready.get_nowait()
        ready_b = scheduler._ready.get_nowait()
        scheduler.ready_task_done()
        scheduler.ready_task_done()
        self.assertEqual({ready_a.payload, ready_b.payload}, {"a0", "b0"})

        first, second = (ready_a, ready_b)
        await scheduler.complete(first.reservation)
        self.assertEqual(scheduler.waiting_backlog(), 1)
        self.assertEqual(scheduler.ready_backlog(), 0)
        await scheduler.complete(second.reservation)
        self.assertEqual(scheduler.waiting_backlog(), 0)
        self.assertEqual(scheduler.ready_backlog(), 1)
        ready_ab = scheduler._ready.get_nowait()
        self.assertEqual(ready_ab.payload, "ab1")
        scheduler.ready_task_done()
        await scheduler.complete(ready_ab.reservation)
        await scheduler.cancel_waiters()

    async def test_cancel_preserves_pre_cancel_waiting_and_ready_backlog(self):
        scheduler = ReadyAssetScheduler[str]()
        a0 = scheduler.reserve(["A"])
        a1 = scheduler.reserve(["A"])
        b0 = scheduler.reserve(["B"])
        scheduler.submit("a0", a0)
        scheduler.submit("a1", a1)
        scheduler.submit("b0", b0)
        await asyncio.sleep(0)

        self.assertEqual(scheduler.ready_backlog(), 2)
        self.assertEqual(scheduler.waiting_backlog(), 1)
        await scheduler.cancel_waiters()

        self.assertEqual(scheduler.ready_backlog(), 2)
        self.assertEqual(scheduler.waiting_backlog(), 1)
        snapshot = scheduler.pre_cancel_snapshot()
        self.assertEqual(snapshot.ready_backlog, 2)
        self.assertEqual(snapshot.waiting_backlog, 1)
        self.assertEqual(dict(snapshot.outstanding_by_asset), {"A": 2, "B": 1})
        self.assertEqual(snapshot.total_outstanding_tickets, 3)


if __name__ == "__main__":
    unittest.main()
