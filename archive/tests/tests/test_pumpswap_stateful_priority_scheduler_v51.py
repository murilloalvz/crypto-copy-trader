from __future__ import annotations

import asyncio
from dataclasses import dataclass
import unittest

from src.pumpswap_stateful_priority_scheduler_v51 import (
    StatefulPriorityEagerDemotingReadyAssetSchedulerV51,
)


@dataclass
class _Payload:
    name: str
    stateful: bool = True


class StatefulPrioritySchedulerV51Tests(unittest.IsolatedAsyncioTestCase):
    async def test_stateful_ready_overtakes_large_demoted_audit_burst(self):
        scheduler = StatefulPriorityEagerDemotingReadyAssetSchedulerV51[_Payload](
            should_remain_stateful=lambda payload: payload.stateful
        )
        opener = _Payload("opener")
        followers = [_Payload(f"c{index}") for index in range(625)]
        reservations = [scheduler.reserve(("hot",)) for _ in range(626)]

        scheduler.submit(opener, reservations[0])
        for payload, reservation in zip(followers, reservations[1:]):
            scheduler.submit(payload, reservation)

        ready_opener = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        self.assertEqual(ready_opener.payload.name, "opener")

        for payload in followers:
            payload.stateful = False
        await scheduler.complete(ready_opener.reservation)
        scheduler.ready_task_done()

        self.assertEqual(scheduler.demoted_pending_jobs, 625)
        self.assertEqual(scheduler.ready_backlog(), 625)

        unrelated = _Payload("unrelated-stateful")
        unrelated_reservation = scheduler.reserve(("other",))
        scheduler.submit(unrelated, unrelated_reservation)

        # v51's only behavioral amendment: genuinely stateful ready work is selected before
        # already-demoted continuation audit work. No ticket or completed cursor is changed here.
        ready_unrelated = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        self.assertEqual(ready_unrelated.payload.name, "unrelated-stateful")
        await scheduler.complete(ready_unrelated.reservation)
        scheduler.ready_task_done()

        first_demoted = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        second_demoted = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        self.assertEqual(first_demoted.payload.name, "c0")
        self.assertEqual(second_demoted.payload.name, "c1")
        await scheduler.complete(first_demoted.reservation)
        scheduler.ready_task_done()
        await scheduler.complete(second_demoted.reservation)
        scheduler.ready_task_done()

        priority = scheduler.priority_snapshot()
        self.assertGreaterEqual(priority.stateful_overtakes_demoted, 1)
        self.assertEqual(priority.demoted_backlog_high_water, 625)
        self.assertEqual(priority.stateful_backlog_high_water, 1)

    async def test_fifo_is_stable_within_stateful_priority(self):
        scheduler = StatefulPriorityEagerDemotingReadyAssetSchedulerV51[_Payload](
            should_remain_stateful=lambda payload: payload.stateful
        )
        payloads = [_Payload(f"s{index}") for index in range(10)]
        reservations = [scheduler.reserve((f"asset-{index}",)) for index in range(10)]
        for payload, reservation in zip(payloads, reservations):
            scheduler.submit(payload, reservation)

        seen = []
        for _ in payloads:
            work = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
            seen.append(work.payload.name)
            await scheduler.complete(work.reservation)
            scheduler.ready_task_done()
        self.assertEqual(seen, [payload.name for payload in payloads])

    async def test_fifo_is_stable_within_demoted_priority(self):
        scheduler = StatefulPriorityEagerDemotingReadyAssetSchedulerV51[_Payload](
            should_remain_stateful=lambda payload: payload.stateful
        )
        opener = _Payload("opener")
        followers = [_Payload(f"c{index}") for index in range(30)]
        reservations = [scheduler.reserve(("hot",)) for _ in range(31)]
        scheduler.submit(opener, reservations[0])
        for payload, reservation in zip(followers, reservations[1:]):
            scheduler.submit(payload, reservation)

        work = await scheduler.get_ready()
        for payload in followers:
            payload.stateful = False
        await scheduler.complete(work.reservation)
        scheduler.ready_task_done()

        seen = []
        for _ in followers:
            demoted = await scheduler.get_ready()
            seen.append(demoted.payload.name)
            await scheduler.complete(demoted.reservation)
            scheduler.ready_task_done()
        self.assertEqual(seen, [payload.name for payload in followers])
        self.assertEqual(scheduler.demoted_finalizer_acks_pending, 0)

    async def test_same_asset_ambiguous_stateful_follower_cannot_overtake(self):
        scheduler = StatefulPriorityEagerDemotingReadyAssetSchedulerV51[_Payload](
            should_remain_stateful=lambda payload: payload.stateful
        )
        opener = _Payload("opener")
        follower = _Payload("follower", stateful=True)
        other = _Payload("other")
        r0 = scheduler.reserve(("A",))
        r1 = scheduler.reserve(("A",))
        ro = scheduler.reserve(("B",))
        scheduler.submit(opener, r0)
        scheduler.submit(follower, r1)
        scheduler.submit(other, ro)

        first = await scheduler.get_ready()
        second = await scheduler.get_ready()
        self.assertEqual([first.payload.name, second.payload.name], ["opener", "other"])
        self.assertEqual(scheduler.waiting_backlog(), 1)

        await scheduler.complete(second.reservation)
        scheduler.ready_task_done()
        self.assertEqual(scheduler.waiting_backlog(), 1)

        await scheduler.complete(first.reservation)
        scheduler.ready_task_done()
        third = await scheduler.get_ready()
        self.assertEqual(third.payload.name, "follower")
        await scheduler.complete(third.reservation)
        scheduler.ready_task_done()

    async def test_multi_asset_work_waits_for_every_stateful_predecessor(self):
        scheduler = StatefulPriorityEagerDemotingReadyAssetSchedulerV51[_Payload](
            should_remain_stateful=lambda payload: payload.stateful
        )
        a0 = _Payload("a0")
        b0 = _Payload("b0")
        both = _Payload("both")
        ra = scheduler.reserve(("A",))
        rb = scheduler.reserve(("B",))
        rab = scheduler.reserve(("A", "B"))
        scheduler.submit(a0, ra)
        scheduler.submit(b0, rb)
        scheduler.submit(both, rab)

        first = await scheduler.get_ready()
        second = await scheduler.get_ready()
        self.assertEqual({first.payload.name, second.payload.name}, {"a0", "b0"})
        self.assertEqual(scheduler.waiting_backlog(), 1)

        await scheduler.complete(first.reservation)
        scheduler.ready_task_done()
        self.assertEqual(scheduler.waiting_backlog(), 1)

        await scheduler.complete(second.reservation)
        scheduler.ready_task_done()
        ready_both = await scheduler.get_ready()
        self.assertEqual(ready_both.payload.name, "both")
        await scheduler.complete(ready_both.reservation)
        scheduler.ready_task_done()

    async def test_snapshot_ready_backlog_counts_both_priority_classes(self):
        scheduler = StatefulPriorityEagerDemotingReadyAssetSchedulerV51[_Payload](
            should_remain_stateful=lambda payload: payload.stateful
        )
        opener = _Payload("opener")
        follower = _Payload("follower")
        r0 = scheduler.reserve(("A",))
        r1 = scheduler.reserve(("A",))
        scheduler.submit(opener, r0)
        scheduler.submit(follower, r1)
        ready = await scheduler.get_ready()
        follower.stateful = False
        await scheduler.complete(ready.reservation)
        scheduler.ready_task_done()

        unrelated = _Payload("other")
        ro = scheduler.reserve(("B",))
        scheduler.submit(unrelated, ro)
        self.assertEqual(scheduler.snapshot().ready_backlog, 2)
        self.assertEqual(scheduler.priority_snapshot().stateful_backlog, 1)
        self.assertEqual(scheduler.priority_snapshot().demoted_backlog, 1)


if __name__ == "__main__":
    unittest.main()
