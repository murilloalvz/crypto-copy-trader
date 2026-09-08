from __future__ import annotations

import asyncio
from dataclasses import dataclass
import unittest

from src.pumpswap_partial_order_v6 import PumpSwapPartialOrderCoordinatorV6
from src.pumpswap_ready_scheduler import ReadyAssetScheduler
from src.pumpswap_stateful_priority_scheduler_v51 import (
    StatefulPriorityEagerDemotingReadyAssetSchedulerV51,
)


class PartialOrderCoordinatorV6Tests(unittest.IsolatedAsyncioTestCase):
    async def test_disjoint_assets_bypass_late_ingress_normalization(self):
        scheduler = ReadyAssetScheduler[str]()
        coordinator = PumpSwapPartialOrderCoordinatorV6(scheduler)

        # Sequence 7 becomes causally available before the late sequence 2. The assets are
        # disjoint, so no dependency edge may block either reservation.
        later = coordinator.reserve(7, ("ASSET-B",))
        earlier = coordinator.reserve(2, ("ASSET-A",))
        scheduler.submit("later", later)
        scheduler.submit("earlier", earlier)

        first = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        second = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        self.assertEqual({first.payload, second.payload}, {"later", "earlier"})
        await scheduler.complete(first.reservation)
        await scheduler.complete(second.reservation)

        snapshot = coordinator.snapshot()
        self.assertEqual(snapshot.dependency_edges, 0)
        self.assertEqual(snapshot.disjoint_admissions, 2)
        self.assertEqual(snapshot.out_of_ingress_admissions, 1)

    async def test_same_asset_is_serialized_in_causal_admission_order(self):
        scheduler = ReadyAssetScheduler[str]()
        coordinator = PumpSwapPartialOrderCoordinatorV6(scheduler)

        first = coordinator.reserve(10, ("HOT",))
        second = coordinator.reserve(1, ("HOT",))
        scheduler.submit("first", first)
        scheduler.submit("second", second)

        ready_first = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        self.assertEqual(ready_first.payload, "first")
        blocked = asyncio.create_task(scheduler.get_ready())
        await asyncio.sleep(0)
        self.assertFalse(blocked.done())
        await scheduler.complete(ready_first.reservation)
        ready_second = await asyncio.wait_for(blocked, timeout=0.1)
        self.assertEqual(ready_second.payload, "second")
        await scheduler.complete(ready_second.reservation)

        snapshot = coordinator.snapshot()
        self.assertEqual(snapshot.dependency_edges, 1)
        self.assertEqual(snapshot.overlapping_admissions, 1)
        self.assertEqual(snapshot.max_predecessors_per_admission, 1)

    async def test_multi_asset_graph_is_acyclic_and_waits_for_each_predecessor(self):
        scheduler = ReadyAssetScheduler[str]()
        coordinator = PumpSwapPartialOrderCoordinatorV6(scheduler)

        left = coordinator.reserve(8, ("A",))
        right = coordinator.reserve(0, ("B",))
        both = coordinator.reserve(4, ("A", "B"))
        scheduler.submit("left", left)
        scheduler.submit("right", right)
        scheduler.submit("both", both)

        ready = {
            (await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)).payload
            for _ in range(2)
        }
        self.assertEqual(ready, {"left", "right"})
        await scheduler.complete(left)
        await scheduler.complete(right)
        joined = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        self.assertEqual(joined.payload, "both")
        await scheduler.complete(joined.reservation)

        snapshot = coordinator.snapshot()
        self.assertEqual(snapshot.dependency_edges, 2)
        self.assertEqual(snapshot.max_predecessors_per_admission, 2)


@dataclass
class _Payload:
    name: str
    stateful: bool


class StatefulDemotedQueueV6Tests(unittest.IsolatedAsyncioTestCase):
    async def test_stateful_ready_work_overtakes_only_proven_demoted_work(self):
        states = {"opener": True, "follower": True, "independent": True}
        scheduler = StatefulPriorityEagerDemotingReadyAssetSchedulerV51[_Payload](
            should_remain_stateful=lambda payload: states[payload.name]
        )
        opener = scheduler.reserve(("HOT",))
        follower = scheduler.reserve(("HOT",))
        independent = scheduler.reserve(("COLD",))
        scheduler.submit(_Payload("opener", True), opener)
        scheduler.submit(_Payload("follower", True), follower)
        states["follower"] = False
        scheduler.submit(_Payload("independent", True), independent)

        first = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        self.assertEqual(first.payload.name, "opener")
        await scheduler.complete(first.reservation)
        second = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        self.assertEqual(second.payload.name, "independent")
        await scheduler.complete(second.reservation)
        third = await asyncio.wait_for(scheduler.get_ready(), timeout=0.1)
        self.assertEqual(third.payload.name, "follower")
        await scheduler.complete(third.reservation)

        snapshot = scheduler.priority_snapshot()
        self.assertGreaterEqual(snapshot.stateful_overtakes_demoted, 1)
        self.assertEqual(scheduler.demoted_finalizer_acks_pending, 0)


if __name__ == "__main__":
    unittest.main()
