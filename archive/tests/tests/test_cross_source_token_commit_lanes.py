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


class PreparedPumpRadarV5:
    def __init__(self, *tokens: str):
        self.tokens = tuple(_Token(token) for token in tokens)


class PreparedPumpSwapRadarV5:
    def __init__(self, *tokens: str):
        self.tokens = tuple(_Token(token) for token in tokens)


class UnknownPrepared:
    def __init__(self):
        self.tokens = (_Token("unknown"),)


class CrossSourceTokenCommitLanesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.lanes = CrossSourceTokenCommitLanes()

    async def asyncTearDown(self):
        self.lanes.close()

    async def _unexpected_inherited(self, *_args, **_kwargs):
        raise AssertionError("recognized stateful work unexpectedly used inherited runner")

    async def test_distinct_tokens_can_overlap_across_sources(self):
        barrier = threading.Barrier(2)
        active = 0
        max_active = 0
        guard = threading.Lock()

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

        results = await asyncio.gather(
            self.lanes.run_sync_stage(
                self._unexpected_inherited,
                work,
                PreparedPumpRadarV5("A"),
                executor=object(),
            ),
            self.lanes.run_sync_stage(
                self._unexpected_inherited,
                work,
                PreparedPumpSwapRadarV5("B"),
                executor=object(),
            ),
        )

        self.assertEqual(results, ["ok", "ok"])
        self.assertEqual(max_active, 2)
        snapshot = self.lanes.snapshot()
        self.assertEqual(snapshot.max_parallel_calls, 2)
        self.assertEqual(snapshot.same_token_overlap_violations, 0)
        self.assertEqual(snapshot.pump_calls, 1)
        self.assertEqual(snapshot.pumpswap_calls, 1)

    async def test_same_token_is_serialized_across_sources(self):
        active = 0
        max_active = 0
        guard = threading.Lock()

        def work(_prepared):
            nonlocal active, max_active
            with guard:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.04)
                return "ok"
            finally:
                with guard:
                    active -= 1

        await asyncio.gather(
            self.lanes.run_sync_stage(
                self._unexpected_inherited,
                work,
                PreparedPumpRadarV5("SAME"),
                executor=object(),
            ),
            self.lanes.run_sync_stage(
                self._unexpected_inherited,
                work,
                PreparedPumpSwapRadarV5("SAME"),
                executor=object(),
            ),
        )

        self.assertEqual(max_active, 1)
        self.assertEqual(self.lanes.snapshot().same_token_overlap_violations, 0)

    async def test_multi_token_overlap_serializes_complete_overlap_set(self):
        active = 0
        max_active = 0
        guard = threading.Lock()

        def work(_prepared):
            nonlocal active, max_active
            with guard:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.04)
            finally:
                with guard:
                    active -= 1

        await asyncio.gather(
            self.lanes.run_sync_stage(
                self._unexpected_inherited,
                work,
                PreparedPumpRadarV5("A", "SHARED"),
                executor=object(),
            ),
            self.lanes.run_sync_stage(
                self._unexpected_inherited,
                work,
                PreparedPumpSwapRadarV5("SHARED", "B"),
                executor=object(),
            ),
        )

        self.assertEqual(max_active, 1)
        self.assertEqual(self.lanes.snapshot().same_token_overlap_violations, 0)

    async def test_unclassified_work_fails_back_to_inherited_runner(self):
        calls = []

        async def inherited(function, /, *args, executor=None, **kwargs):
            calls.append((function, args, executor, kwargs))
            return "inherited"

        result = await self.lanes.run_sync_stage(
            inherited,
            lambda _prepared: None,
            UnknownPrepared(),
            executor=object(),
        )

        self.assertEqual(result, "inherited")
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.lanes.snapshot().fallback_calls, 1)

    async def test_exception_releases_same_token_lock(self):
        def explode(_prepared):
            raise RuntimeError("boom")

        with self.assertRaisesRegex(RuntimeError, "boom"):
            await self.lanes.run_sync_stage(
                self._unexpected_inherited,
                explode,
                PreparedPumpRadarV5("A"),
                executor=object(),
            )

        result = await self.lanes.run_sync_stage(
            self._unexpected_inherited,
            lambda _prepared: "recovered",
            PreparedPumpSwapRadarV5("A"),
            executor=object(),
        )
        self.assertEqual(result, "recovered")
        self.assertEqual(self.lanes.snapshot().same_token_overlap_violations, 0)


if __name__ == "__main__":
    unittest.main()
