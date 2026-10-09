import unittest

from src.pumpswap_eager_demoting_scheduler_v42 import EagerDemotingReadyAssetSchedulerV42


class EagerDemotingSchedulerV42Tests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_eagerly_demotes_previously_pending_proven_continuation(self):
        stateful = {"opener": True, "follower": True, "new": True}
        scheduler = EagerDemotingReadyAssetSchedulerV42(
            should_remain_stateful=lambda payload: stateful[payload]
        )

        opener = scheduler.reserve(["asset"])
        follower = scheduler.reserve(["asset"])
        new = scheduler.reserve(["other"])

        scheduler.submit("opener", opener)
        scheduler.submit("follower", follower)
        self.assertEqual(scheduler.waiting_backlog(), 1)

        # Simulate the run-local episode cache learning that the pending follower can no longer
        # mutate state before another completion callback occurs.
        stateful["follower"] = False
        scheduler.submit("new", new)

        self.assertEqual(scheduler.eager_submit_demoted_jobs, 1)
        self.assertEqual(scheduler.eager_submit_demoted_tickets, 1)
        self.assertEqual(scheduler.demoted_pending_jobs, 1)
        self.assertEqual(scheduler.waiting_backlog(), 0)

        first = await scheduler.get_ready()
        second = await scheduler.get_ready()
        third = await scheduler.get_ready()
        self.assertEqual(first.payload, "opener")
        self.assertEqual(second.payload, "follower")
        self.assertEqual(third.payload, "new")

    async def test_ambiguous_pending_follower_remains_fifo_without_blocking_other_asset(self):
        stateful = {"opener": True, "follower": True, "other": True}
        scheduler = EagerDemotingReadyAssetSchedulerV42(
            should_remain_stateful=lambda payload: stateful[payload]
        )
        opener = scheduler.reserve(["asset"])
        follower = scheduler.reserve(["asset"])
        other = scheduler.reserve(["other"])

        scheduler.submit("opener", opener)
        scheduler.submit("follower", follower)
        scheduler.submit("other", other)

        self.assertEqual(scheduler.eager_submit_demoted_jobs, 0)
        self.assertEqual(scheduler.waiting_backlog(), 1)

        # Different assets stay independent: opener and unrelated work are ready, while the
        # same-asset follower remains pending until opener completion advances its FIFO cursor.
        first = await scheduler.get_ready()
        second = await scheduler.get_ready()
        self.assertEqual(first.payload, "opener")
        self.assertEqual(second.payload, "other")
        self.assertEqual(scheduler.waiting_backlog(), 1)

        await scheduler.complete(first.reservation)
        scheduler.ready_task_done()
        third = await scheduler.get_ready()
        self.assertEqual(third.payload, "follower")

    async def test_ready_job_is_never_demoted_by_eager_submit_pass(self):
        stateful = {"ready": True, "other": True}
        scheduler = EagerDemotingReadyAssetSchedulerV42(
            should_remain_stateful=lambda payload: stateful[payload]
        )
        ready = scheduler.reserve(["asset"])
        scheduler.submit("ready", ready)
        stateful["ready"] = False

        other = scheduler.reserve(["other"])
        scheduler.submit("other", other)

        self.assertEqual(scheduler.eager_submit_demoted_jobs, 0)
        work = await scheduler.get_ready()
        self.assertEqual(work.payload, "ready")


if __name__ == "__main__":
    unittest.main()
