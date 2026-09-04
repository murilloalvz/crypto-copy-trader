from __future__ import annotations

import asyncio
from dataclasses import dataclass
import unittest

from src.pumpswap_demoting_scheduler_v34 import DemotingReadyAssetSchedulerV34


@dataclass
class _Payload:
    name: str
    stateful: bool = True


class DemotingReadyAssetSchedulerV34Tests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_proven_continuation_keeps_payload_and_skips_only_stateful_ticket(self):
        scheduler = DemotingReadyAssetSchedulerV34[_Payload](
            should_remain_stateful=lambda payload: payload.stateful
        )
        first = _Payload("first")
        follower = _Payload("follower")
        successor = _Payload("successor")

        r0 = scheduler.reserve(("asset",))
        r1 = scheduler.reserve(("asset",))
        r2 = scheduler.reserve(("asset",))
        scheduler.submit(first, r0)
        scheduler.submit(follower, r1)
        scheduler.submit(successor, r2)

        ready0 = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        self.assertEqual(ready0.payload.name, "first")
        self.assertEqual(scheduler.waiting_backlog(), 2)

        # Simulate the opener establishing an episode before scheduler.complete().
        follower.stateful = False
        await scheduler.complete(ready0.reservation)
        scheduler.ready_task_done()

        self.assertEqual(scheduler.demoted_pending_jobs, 1)
        self.assertEqual(scheduler.demoted_pending_tickets, 1)
        self.assertEqual(scheduler.waiting_backlog(), 0)
        self.assertEqual(scheduler.demoted_finalizer_acks_pending, 1)

        # The continuation payload must still be finalized/audited; it is not discarded.
        ready1 = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        ready2 = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        self.assertEqual([ready1.payload.name, ready2.payload.name], ["follower", "successor"])

        await scheduler.complete(ready1.reservation)
        scheduler.ready_task_done()
        self.assertEqual(scheduler.demoted_finalizer_acks_pending, 0)

        await scheduler.complete(ready2.reservation)
        scheduler.ready_task_done()
        self.assertEqual(scheduler.snapshot().total_outstanding_tickets, 0)

    async def test_entire_hot_continuation_tail_collapses_after_one_opener(self):
        scheduler = DemotingReadyAssetSchedulerV34[_Payload](
            should_remain_stateful=lambda payload: payload.stateful
        )
        opener = _Payload("opener")
        followers = [_Payload(f"c{index}") for index in range(20)]
        reservations = [scheduler.reserve(("hot",)) for _ in range(21)]
        scheduler.submit(opener, reservations[0])
        for payload, reservation in zip(followers, reservations[1:]):
            scheduler.submit(payload, reservation)

        ready = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        self.assertEqual(ready.payload.name, "opener")
        self.assertEqual(scheduler.waiting_backlog(), 20)

        for payload in followers:
            payload.stateful = False
        await scheduler.complete(ready.reservation)
        scheduler.ready_task_done()

        self.assertEqual(scheduler.demoted_pending_jobs, 20)
        self.assertEqual(scheduler.demoted_pending_tickets, 20)
        self.assertEqual(scheduler.waiting_backlog(), 0)
        self.assertEqual(scheduler.snapshot().total_outstanding_tickets, 0)
        self.assertEqual(scheduler.ready_backlog(), 20)

        seen = []
        while scheduler.ready_backlog():
            item = scheduler._ready.get_nowait()
            seen.append(item.payload.name)
            await scheduler.complete(item.reservation)
            scheduler.ready_task_done()
        self.assertEqual(seen, [payload.name for payload in followers])
        self.assertEqual(scheduler.demoted_finalizer_acks_pending, 0)

    async def test_ambiguous_pending_work_remains_stateful(self):
        scheduler = DemotingReadyAssetSchedulerV34[_Payload](
            should_remain_stateful=lambda payload: payload.stateful
        )
        first = _Payload("first")
        follower = _Payload("follower", stateful=True)
        r0 = scheduler.reserve(("asset",))
        r1 = scheduler.reserve(("asset",))
        scheduler.submit(first, r0)
        scheduler.submit(follower, r1)

        ready0 = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        await scheduler.complete(ready0.reservation)
        scheduler.ready_task_done()

        self.assertEqual(scheduler.demoted_pending_jobs, 0)
        ready1 = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        self.assertEqual(ready1.payload.name, "follower")
        await scheduler.complete(ready1.reservation)
        scheduler.ready_task_done()

    async def test_multi_asset_demotion_does_not_release_later_stateful_work_early(self):
        scheduler = DemotingReadyAssetSchedulerV34[_Payload](
            should_remain_stateful=lambda payload: payload.stateful
        )
        a0 = _Payload("a0")
        b0 = _Payload("b0")
        continuation = _Payload("continuation")
        later = _Payload("later")
        ra0 = scheduler.reserve(("A",))
        rb0 = scheduler.reserve(("B",))
        rcont = scheduler.reserve(("A", "B"))
        rlater = scheduler.reserve(("A", "B"))
        scheduler.submit(a0, ra0)
        scheduler.submit(b0, rb0)
        scheduler.submit(continuation, rcont)
        scheduler.submit(later, rlater)

        ready_a = scheduler._ready.get_nowait()
        ready_b = scheduler._ready.get_nowait()
        scheduler.ready_task_done()
        scheduler.ready_task_done()
        self.assertEqual({ready_a.payload.name, ready_b.payload.name}, {"a0", "b0"})

        continuation.stateful = False
        await scheduler.complete(ready_a.reservation)

        demoted = scheduler._ready.get_nowait()
        scheduler.ready_task_done()
        self.assertEqual(demoted.payload.name, "continuation")
        self.assertEqual(scheduler.waiting_backlog(), 1)
        await scheduler.complete(demoted.reservation)

        await scheduler.complete(ready_b.reservation)
        later_ready = scheduler._ready.get_nowait()
        scheduler.ready_task_done()
        self.assertEqual(later_ready.payload.name, "later")
        await scheduler.complete(later_ready.reservation)
        self.assertEqual(scheduler.snapshot().total_outstanding_tickets, 0)


if __name__ == "__main__":
    unittest.main()
