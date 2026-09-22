from __future__ import annotations

import asyncio
import threading
import unittest
from unittest.mock import patch

from src.signal_plane_route_research_coordinator_v0 import (
    SIGNAL_PLANE_ROUTE_RESEARCH_COORDINATOR_VERSION,
    SignalPlaneRouteResearchCoordinatorV0,
)


class SignalPlaneRouteResearchCoordinatorV0Tests(unittest.TestCase):
    def test_version_is_frozen(self):
        self.assertEqual(
            SIGNAL_PLANE_ROUTE_RESEARCH_COORDINATOR_VERSION,
            "signal_plane_route_research_coordinator_v0",
        )

    def test_defaults_preserve_frozen_cohort_shape_and_pacing(self):
        coordinator = SignalPlaneRouteResearchCoordinatorV0(
            acquisition_run_key="systems-coordinator",
        )
        self.assertEqual(coordinator.max_episodes, 40)
        self.assertEqual(coordinator.research_workers, 4)
        self.assertEqual(coordinator.hazard_workers, 4)
        snapshot = coordinator.snapshot()
        self.assertEqual(snapshot["hazard_pacer"]["interval_ms"], 650)
        self.assertEqual(snapshot["entry_pacer"]["interval_ms"], 1000)

    def test_one_new_admission_fans_out_to_hazard_and_research(self):
        async def scenario():
            coordinator = SignalPlaneRouteResearchCoordinatorV0(
                acquisition_run_key="systems-coordinator",
                max_episodes=2,
            )
            coordinator._loop = asyncio.get_running_loop()
            coordinator._loop_thread_id = threading.get_ident()
            coordinator._started = True

            with patch(
                "src.signal_plane_route_research_coordinator_v0."
                "admit_opportunity_episode",
                return_value=True,
            ):
                admitted = coordinator.admit_episode(
                    acquisition_run_key="systems-coordinator",
                    episode_key="episode-1",
                    admitted_at=100,
                )

            await asyncio.sleep(0)
            return coordinator, admitted

        coordinator, admitted = asyncio.run(scenario())
        self.assertTrue(admitted)
        self.assertEqual(coordinator.hazard_queue.qsize(), 1)
        self.assertEqual(coordinator.research_queue.qsize(), 1)
        self.assertEqual(coordinator.counters["new_admissions"], 1)
        self.assertEqual(coordinator.counters["selected_for_research"], 1)
        self.assertEqual(coordinator.counters["hazard_jobs_enqueued"], 1)
        self.assertEqual(coordinator.counters["research_jobs_enqueued"], 1)

    def test_replay_is_not_queued_again(self):
        async def scenario():
            coordinator = SignalPlaneRouteResearchCoordinatorV0(
                acquisition_run_key="systems-coordinator",
            )
            coordinator._loop = asyncio.get_running_loop()
            coordinator._loop_thread_id = threading.get_ident()
            coordinator._started = True

            with patch(
                "src.signal_plane_route_research_coordinator_v0."
                "admit_opportunity_episode",
                return_value=False,
            ):
                admitted = coordinator.admit_episode(
                    acquisition_run_key="systems-coordinator",
                    episode_key="episode-1",
                    admitted_at=100,
                )

            await asyncio.sleep(0)
            return coordinator, admitted

        coordinator, admitted = asyncio.run(scenario())
        self.assertFalse(admitted)
        self.assertEqual(coordinator.hazard_queue.qsize(), 0)
        self.assertEqual(coordinator.research_queue.qsize(), 0)
        self.assertEqual(coordinator.counters["admission_replays"], 1)

    def test_predeclared_cap_does_not_expand(self):
        async def scenario():
            coordinator = SignalPlaneRouteResearchCoordinatorV0(
                acquisition_run_key="systems-coordinator",
                max_episodes=1,
            )
            coordinator._loop = asyncio.get_running_loop()
            coordinator._loop_thread_id = threading.get_ident()
            coordinator._started = True

            with patch(
                "src.signal_plane_route_research_coordinator_v0."
                "admit_opportunity_episode",
                return_value=True,
            ):
                first = coordinator.admit_episode(
                    acquisition_run_key="systems-coordinator",
                    episode_key="episode-1",
                    admitted_at=100,
                )
                second = coordinator.admit_episode(
                    acquisition_run_key="systems-coordinator",
                    episode_key="episode-2",
                    admitted_at=101,
                )

            await asyncio.sleep(0)
            return coordinator, first, second

        coordinator, first, second = asyncio.run(scenario())
        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(len(coordinator.selected_episode_keys), 1)
        self.assertEqual(coordinator.hazard_queue.qsize(), 1)
        self.assertEqual(coordinator.research_queue.qsize(), 1)
        self.assertEqual(
            coordinator.counters["not_selected_after_predeclared_cap"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
