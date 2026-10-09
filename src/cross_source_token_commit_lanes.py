from __future__ import annotations

import asyncio
from collections import Counter
import contextvars
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import functools
import threading
import time
from typing import Any, Awaitable, Callable


@dataclass(frozen=True)
class CrossSourceCommitLaneSnapshot:
    pump_workers: int
    pumpswap_workers: int
    pump_calls: int
    pumpswap_calls: int
    fallback_calls: int
    max_parallel_calls: int
    same_token_overlap_violations: int
    pump_lane_queue_wait_seconds: tuple[float, ...]
    pumpswap_lane_queue_wait_seconds: tuple[float, ...]
    token_lock_wait_seconds: tuple[float, ...]
    service_seconds: tuple[float, ...]


def _trigger_token_keys(prepared: Any) -> tuple[str, ...]:
    keys: set[str] = set()
    for token in getattr(prepared, "tokens", ()):
        if getattr(token, "trigger", None) is None:
            continue
        mint = str(getattr(token, "token_mint", "")).strip()
        if mint:
            keys.add(mint)
    return tuple(sorted(keys))


def _prepared_source(prepared: Any) -> str | None:
    class_name = type(prepared).__name__.lower()
    if "pumpswap" in class_name:
        return "pumpswap"
    if "pump" in class_name:
        return "pump"
    return None


class CrossSourceTokenCommitLanes:
    """Bounded source commit lanes with shared per-token serialization.

    Defaults preserve Tailfix-v1 behavior: one Pump worker and one PumpSwap worker. Later systems
    profiles may raise a lane's worker count only when the caller also supplies enough independent
    ready work. Every trigger token is still protected by one process-local lock shared across both
    sources, so increasing lane capacity never permits same-token concurrent finalization.

    Multi-token jobs acquire the complete sorted token set, preventing deadlocks and preserving
    overlap serialization. Unknown/non-stateful call shapes fail back to the inherited runner rather
    than receiving speculative concurrency.
    """

    def __init__(self, *, pump_workers: int = 1, pumpswap_workers: int = 1) -> None:
        if pump_workers <= 0 or pumpswap_workers <= 0:
            raise ValueError("commit lane worker counts must be positive")
        self.pump_workers = int(pump_workers)
        self.pumpswap_workers = int(pumpswap_workers)
        self._pump_executor = ThreadPoolExecutor(
            max_workers=self.pump_workers,
            thread_name_prefix="market-radar-pump-token-lane",
        )
        self._pumpswap_executor = ThreadPoolExecutor(
            max_workers=self.pumpswap_workers,
            thread_name_prefix="market-radar-pumpswap-token-lane",
        )
        self._registry_lock = threading.Lock()
        self._token_locks: dict[str, threading.Lock] = {}
        self._stats_lock = threading.Lock()
        self._counts: Counter[str] = Counter()
        self._pump_lane_queue_wait_seconds: list[float] = []
        self._pumpswap_lane_queue_wait_seconds: list[float] = []
        self._token_lock_wait_seconds: list[float] = []
        self._service_seconds: list[float] = []
        self._active_calls = 0
        self._max_parallel_calls = 0
        self._active_tokens: set[str] = set()
        self._closed = False

    def _locks_for(self, token_keys: tuple[str, ...]) -> tuple[threading.Lock, ...]:
        with self._registry_lock:
            return tuple(
                self._token_locks.setdefault(token, threading.Lock())
                for token in token_keys
            )

    def _record_lane_queue_wait(self, source: str, seconds: float) -> None:
        with self._stats_lock:
            target = (
                self._pump_lane_queue_wait_seconds
                if source == "pump"
                else self._pumpswap_lane_queue_wait_seconds
            )
            target.append(max(0.0, seconds))

    def _run_guarded(
        self,
        *,
        source: str,
        token_keys: tuple[str, ...],
        submitted_monotonic: float,
        context: contextvars.Context,
        function: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        executor_started = time.monotonic()
        self._record_lane_queue_wait(source, executor_started - submitted_monotonic)

        locks = self._locks_for(token_keys)
        lock_wait_started = time.monotonic()
        acquired: list[threading.Lock] = []
        try:
            for lock in locks:
                lock.acquire()
                acquired.append(lock)
            lock_acquired = time.monotonic()

            with self._stats_lock:
                self._token_lock_wait_seconds.append(
                    max(0.0, lock_acquired - lock_wait_started)
                )
                overlapping = self._active_tokens.intersection(token_keys)
                if overlapping:
                    self._counts["same_token_overlap_violations"] += 1
                self._active_tokens.update(token_keys)
                self._active_calls += 1
                self._max_parallel_calls = max(
                    self._max_parallel_calls,
                    self._active_calls,
                )

            service_started = time.monotonic()
            try:
                return context.run(function, *args, **kwargs)
            finally:
                finished = time.monotonic()
                with self._stats_lock:
                    self._service_seconds.append(
                        max(0.0, finished - service_started)
                    )
                    self._active_calls = max(0, self._active_calls - 1)
                    for token in token_keys:
                        self._active_tokens.discard(token)
        finally:
            for lock in reversed(acquired):
                lock.release()

    async def run_sync_stage(
        self,
        inherited_runner: Callable[..., Awaitable[Any]],
        function: Callable[..., Any],
        /,
        *args: Any,
        executor=None,
        **kwargs: Any,
    ) -> Any:
        """Route only recognized stateful finalizers; delegate everything else unchanged."""

        if self._closed:
            raise RuntimeError("cross-source commit lanes are closed")
        prepared = args[0] if args else None
        source = _prepared_source(prepared) if prepared is not None else None
        token_keys = _trigger_token_keys(prepared) if prepared is not None else ()

        if executor is None or source is None or not token_keys:
            with self._stats_lock:
                self._counts["fallback_calls"] += 1
            return await inherited_runner(
                function,
                *args,
                executor=executor,
                **kwargs,
            )

        with self._stats_lock:
            self._counts[f"{source}_calls"] += 1

        selected_executor = (
            self._pump_executor if source == "pump" else self._pumpswap_executor
        )
        submitted = time.monotonic()
        context = contextvars.copy_context()
        loop = asyncio.get_running_loop()
        call = functools.partial(
            self._run_guarded,
            source=source,
            token_keys=token_keys,
            submitted_monotonic=submitted,
            context=context,
            function=function,
            args=args,
            kwargs=dict(kwargs),
        )
        return await loop.run_in_executor(selected_executor, call)

    def snapshot(self) -> CrossSourceCommitLaneSnapshot:
        with self._stats_lock:
            return CrossSourceCommitLaneSnapshot(
                pump_workers=self.pump_workers,
                pumpswap_workers=self.pumpswap_workers,
                pump_calls=self._counts["pump_calls"],
                pumpswap_calls=self._counts["pumpswap_calls"],
                fallback_calls=self._counts["fallback_calls"],
                max_parallel_calls=self._max_parallel_calls,
                same_token_overlap_violations=self._counts[
                    "same_token_overlap_violations"
                ],
                pump_lane_queue_wait_seconds=tuple(
                    self._pump_lane_queue_wait_seconds
                ),
                pumpswap_lane_queue_wait_seconds=tuple(
                    self._pumpswap_lane_queue_wait_seconds
                ),
                token_lock_wait_seconds=tuple(self._token_lock_wait_seconds),
                service_seconds=tuple(self._service_seconds),
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pump_executor.shutdown(wait=True, cancel_futures=False)
        self._pumpswap_executor.shutdown(wait=True, cancel_futures=False)
