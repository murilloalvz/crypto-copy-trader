from __future__ import annotations

import asyncio
from dataclasses import dataclass
import threading
import time
import unittest

from src.cross_source_token_commit_lanes import CrossSourceTokenCommitLanes


@dataclass(frozen=True)
class _Token:
    token_mint: str
    trigger: object | None = object()


class PreparedPumpSwapRadarV5:
    def __init__(self, token: str):
        self.tokens = (_Token(token),)


class CrossSourceTokenCommitLanesParallelV3Tests(unittest.IsolatedAsyncioTestCase):
    async def _unexpected_inherited(self, *_args, **_kwargs):
        raise AssertionError("recognized stateful work unexpectedly used inherited runner")

    async def test_disjoint_pumpswap_tokens_overlap_with_bounded_workers(self):
        lanes = CrossSourceTokenCommitLanes(pump_workers=1, pumpswap_workers=4)
        active = 0
        max_active = 0
        guard = threading.Lock()
        barrier = threading.Barrier(4)

        def work(_prepared):
            nonlocal active, max_active
            with guard:
                active += 1
                max_active = max(max_active, active)
            try:
                barrier.wait(timeout=1.0)
                time.sleep(0.02)
                return "ok"
            finally:
                with guard:
                    active -= 1

        try:
            results = await asyncio.gather(
                *(
                    lanes.run_sync_stage(
                        self._unexpected_inherited,
                        work,
                        PreparedPumpSwapRadarV5(f"TOKEN-{index}"),
                        executor=object(),
                    )
                    for index in range(4)
                )
            )
        finally:
            lanes.close()

        self.assertEqual(results, ["ok"] * 4)
        self.assertEqual(max_active, 4)
        snapshot = lanes.snapshot()
        self.assertEqual(snapshot.pumpswap_workers, 4)
        self.assertEqual(snapshot.max_parallel_calls, 4)
        self.assertEqual(snapshot.same_token_overlap_violations, 0)

    async def test_same_pumpswap_token_stays_serialized_with_four_workers(self):
        lanes = CrossSourceTokenCommitLanes(pump_workers=1, pumpswap_workers=4)
        active = 0
        max_active = 0
        guard = threading.Lock()

        def work(_prepared):
            nonlocal active, max_active
            with guard:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.03)
                return "ok"
            finally:
                with guard:
                    active -= 1

        try:
            await asyncio.gather(
                *(
                    lanes.run_sync_stage(
                        self._unexpected_inherited,
                        work,
                        PreparedPumpSwapRadarV5("SAME"),
                        executor=object(),
                    )
                    for _ in range(4)
                )
            )
        finally:
            lanes.close()

        self.assertEqual(max_active, 1)
        self.assertEqual(lanes.snapshot().same_token_overlap_violations, 0)

    def test_worker_counts_must_be_positive(self):
        with self.assertRaises(ValueError):
            CrossSourceTokenCommitLanes(pump_workers=0, pumpswap_workers=1)
        with self.assertRaises(ValueError):
            CrossSourceTokenCommitLanes(pump_workers=1, pumpswap_workers=0)


if __name__ == "__main__":
    unittest.main()
