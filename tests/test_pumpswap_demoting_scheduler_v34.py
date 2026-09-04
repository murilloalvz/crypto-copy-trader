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
    async def test_pending_proven_noop_is_skipped_without_overtaking_fifo(self):
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

        ready2 = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        self.assertEqual(ready2.payload.name, "successor")
        await scheduler.complete(ready2.reservation)
        scheduler.ready_task_done()
        self.assertEqual(scheduler.snapshot().total_outstanding_tickets, 0)

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


if __name__ == "__main__":
    unittest.main()
