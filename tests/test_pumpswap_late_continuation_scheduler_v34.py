import asyncio
import unittest

from src.pumpswap_late_continuation_scheduler_v34 import (
    LateContinuationReadyAssetSchedulerV34,
)


class LateContinuationReadyAssetSchedulerV34Tests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_hot_chain_is_demoted_after_opener_becomes_canonical(self):
        stateful = {"opener": True, "c1": True, "c2": True}
        scheduler = LateContinuationReadyAssetSchedulerV34[str](
            may_require_stateful=lambda payload: stateful[payload]
        )
        reservations = [scheduler.reserve(["HOT"]) for _ in range(3)]
        scheduler.submit("opener", reservations[0])
        scheduler.submit("c1", reservations[1])
        scheduler.submit("c2", reservations[2])

        opener = await asyncio.wait_for(scheduler.get_ready(), timeout=0.2)
        self.assertEqual(opener.payload, "opener")
        scheduler.ready_task_done()
        self.assertEqual(scheduler.waiting_backlog(), 2)

        # Simulate v27 cache becoming authoritative after opener finalization.
        stateful["c1"] = False
        stateful["c2"] = False
        await scheduler.complete(opener.reservation)

        self.assertEqual(scheduler.late_demotions, 2)
        self.assertEqual(scheduler.late_demoted_tickets, 2)
        self.assertEqual(scheduler.waiting_backlog(), 0)
        self.assertEqual(scheduler.snapshot().total_outstanding_tickets, 0)
        self.assertEqual(scheduler.ready_backlog(), 2)

        demoted = [scheduler._ready.get_nowait(), scheduler._ready.get_nowait()]
        for item in demoted:
            scheduler.ready_task_done()
            await scheduler.complete(item.reservation)
        self.assertEqual({item.payload for item in demoted}, {"c1", "c2"})
        self.assertEqual(scheduler._late_demoted_reservations, set())
        await scheduler.cancel_waiters()

    async def test_still_stateful_successor_remains_strict_fifo(self):
        stateful = {"first": True, "second": True}
        scheduler = LateContinuationReadyAssetSchedulerV34[str](
            may_require_stateful=lambda payload: stateful[payload]
        )
        first = scheduler.reserve(["HOT"])
        second = scheduler.reserve(["HOT"])
        scheduler.submit("first", first)
        scheduler.submit("second", second)

        ready_first = scheduler._ready.get_nowait()
        scheduler.ready_task_done()
        await scheduler.complete(ready_first.reservation)

        self.assertEqual(scheduler.late_demotions, 0)
        self.assertEqual(scheduler.waiting_backlog(), 0)
        ready_second = scheduler._ready.get_nowait()
        self.assertEqual(ready_second.payload, "second")
        scheduler.ready_task_done()
        await scheduler.complete(ready_second.reservation)
        self.assertEqual(scheduler.snapshot().total_outstanding_tickets, 0)
        await scheduler.cancel_waiters()

    async def test_multi_asset_continuation_skip_does_not_overtake_stateful_predecessors(self):
        stateful = {"a0": True, "b0": True, "ab-cont": True, "ab-next": True}
        scheduler = LateContinuationReadyAssetSchedulerV34[str](
            may_require_stateful=lambda payload: stateful[payload]
        )
        a0 = scheduler.reserve(["A"])
        b0 = scheduler.reserve(["B"])
        ab_cont = scheduler.reserve(["A", "B"])
        ab_next = scheduler.reserve(["A", "B"])
        scheduler.submit("a0", a0)
        scheduler.submit("b0", b0)
        scheduler.submit("ab-cont", ab_cont)
        scheduler.submit("ab-next", ab_next)

        ready_a = scheduler._ready.get_nowait()
        ready_b = scheduler._ready.get_nowait()
        scheduler.ready_task_done()
        scheduler.ready_task_done()
        self.assertEqual({ready_a.payload, ready_b.payload}, {"a0", "b0"})

        stateful["ab-cont"] = False
        # Completing only one predecessor may mark the continuation ticket skipped, but the
        # later stateful A/B job must not become ready until the other predecessor completes.
        await scheduler.complete(ready_a.reservation)
        ready_payloads = []
        while scheduler.ready_backlog():
            item = scheduler._ready.get_nowait()
            scheduler.ready_task_done()
            ready_payloads.append(item)
        self.assertEqual(ready_payloads, ["ab-cont"])
        self.assertEqual(scheduler.waiting_backlog(), 1)

        await scheduler.complete(ready_b.reservation)
        ready_next = scheduler._ready.get_nowait()
        self.assertEqual(ready_next.payload, "ab-next")
        scheduler.ready_task_done()
        await scheduler.complete(ready_next.reservation)
        self.assertEqual(scheduler.snapshot().total_outstanding_tickets, 0)
        await scheduler.cancel_waiters()

    async def test_classifier_exception_fails_closed(self):
        def classifier(payload: str) -> bool:
            if payload == "later":
                raise RuntimeError("classifier failed")
            return True

        scheduler = LateContinuationReadyAssetSchedulerV34[str](
            may_require_stateful=classifier
        )
        first = scheduler.reserve(["A"])
        later = scheduler.reserve(["A"])
        scheduler.submit("first", first)
        scheduler.submit("later", later)
        ready = scheduler._ready.get_nowait()
        scheduler.ready_task_done()

        with self.assertRaisesRegex(RuntimeError, "classifier failed"):
            await scheduler.complete(ready.reservation)
        self.assertEqual(scheduler.late_demotions, 0)
        self.assertEqual(scheduler.waiting_backlog(), 1)
        await scheduler.cancel_waiters()


if __name__ == "__main__":
    unittest.main()
