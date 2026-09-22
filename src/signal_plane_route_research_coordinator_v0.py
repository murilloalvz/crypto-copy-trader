from __future__ import annotations

import asyncio
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import threading
import time

from src.config import settings
from src.jupiter_research_entry_route import (
    JupiterResearchEntryRouteConfig,
    JupiterResearchEntryRouteProbe,
)
from src.market_opportunity_episode_store import get_market_opportunity_episode
from src.opportunity_enrichment_store import admit_opportunity_episode
from src.opportunity_onchain_hazard import SolanaRPCMintHazardProbe
from src.opportunity_provider_attempt_store import (
    FINAL_PROVIDER_STATUSES,
    load_provider_attempt,
)
from src.opportunity_route_research_store import (
    freeze_route_research_decision,
    load_route_research_outcomes,
)
from src.provider_start_pacer_v44 import ProviderStartPacerV44


SIGNAL_PLANE_ROUTE_RESEARCH_COORDINATOR_VERSION = (
    "signal_plane_route_research_coordinator_v0"
)


@dataclass(frozen=True)
class _EpisodeJob:
    episode_key: str
    enqueued_monotonic: float


class SignalPlaneRouteResearchCoordinatorV0:
    """Frozen-semantics downstream coordinator for the new Signal Plane.

    New durable episodes enter two independent lanes, matching the historical
    v37/v41 topology: one hazard provider lane and one research lane that waits
    for terminal hazard evidence before attempting the Jupiter route-only entry.
    Provider starts retain v44 pacing and every provider attempt remains at-most-once.
    """

    def __init__(
        self,
        *,
        acquisition_run_key: str,
        max_episodes: int = 40,
        research_workers: int = 4,
        hazard_workers: int = 4,
        hazard_wait_timeout_seconds: int = 30,
        hazard_rpc_timeout_seconds: int = 3,
        jupiter_timeout_seconds: int = 5,
        research_notional_usd: float = 25.0,
        research_slippage_bps: int = 100,
        hazard_start_interval_ms: int = 650,
        entry_start_interval_ms: int = 1000,
    ) -> None:
        run_key = str(acquisition_run_key).strip()
        if not run_key:
            raise ValueError("acquisition_run_key cannot be empty")
        if min(
            max_episodes,
            research_workers,
            hazard_workers,
            hazard_wait_timeout_seconds,
            hazard_rpc_timeout_seconds,
            jupiter_timeout_seconds,
        ) <= 0:
            raise ValueError("coordinator counts/timeouts must be positive")
        if research_notional_usd <= 0:
            raise ValueError("research_notional_usd must be positive")
        if not 0 <= research_slippage_bps <= 10_000:
            raise ValueError("research_slippage_bps must be between 0 and 10000")
        if min(hazard_start_interval_ms, entry_start_interval_ms) < 0:
            raise ValueError("provider pacing intervals cannot be negative")

        self.acquisition_run_key = run_key
        self.max_episodes = int(max_episodes)
        self.research_workers = int(research_workers)
        self.hazard_workers = int(hazard_workers)
        self.hazard_wait_timeout_seconds = int(hazard_wait_timeout_seconds)
        self.hazard_pacer = ProviderStartPacerV44(
            interval_ms=hazard_start_interval_ms
        )
        self.entry_pacer = ProviderStartPacerV44(
            interval_ms=entry_start_interval_ms
        )
        self.hazard_probe = SolanaRPCMintHazardProbe(
            rpc_timeout_seconds=hazard_rpc_timeout_seconds
        )
        self.entry_probe = JupiterResearchEntryRouteProbe(
            JupiterResearchEntryRouteConfig(
                api_key=settings.jupiter_api_key,
                timeout_seconds=jupiter_timeout_seconds,
                notional_usd=research_notional_usd,
                slippage_bps=research_slippage_bps,
            )
        )

        self.hazard_queue: asyncio.Queue[_EpisodeJob] = asyncio.Queue(
            maxsize=self.max_episodes
        )
        self.research_queue: asyncio.Queue[_EpisodeJob] = asyncio.Queue(
            maxsize=self.max_episodes
        )
        self.counters: Counter[str] = Counter()
        self.selected_episode_keys: set[str] = set()
        self.decision_latencies_seconds: list[float] = []
        self.disposition_latencies_seconds: list[float] = []
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._executor: ThreadPoolExecutor | None = None
        self._started = False

    def start(self) -> None:
        if self._started:
            raise RuntimeError("coordinator already started")
        self._loop = asyncio.get_running_loop()
        self._executor = ThreadPoolExecutor(
            max_workers=self.research_workers + self.hazard_workers,
            thread_name_prefix="signal-plane-route-research-v0",
        )
        self._tasks = [
            *[
                asyncio.create_task(
                    self._hazard_worker(index),
                    name=f"signal-plane-hazard-v0-{index}",
                )
                for index in range(self.hazard_workers)
            ],
            *[
                asyncio.create_task(
                    self._research_worker(index),
                    name=f"signal-plane-research-v0-{index}",
                )
                for index in range(self.research_workers)
            ],
        ]
        self._started = True

    def admit_episode(self, **kwargs) -> bool:
        """Thread-safe callback compatible with admit_opportunity_episode."""

        if not self._started or self._loop is None:
            raise RuntimeError("coordinator must be started before admission")
        run_key = str(kwargs.get("acquisition_run_key", "")).strip()
        episode_key = str(kwargs.get("episode_key", "")).strip()
        admitted_at = int(kwargs.get("admitted_at", -1))
        if run_key != self.acquisition_run_key:
            raise ValueError("coordinator run key mismatch")

        admitted = admit_opportunity_episode(
            acquisition_run_key=run_key,
            episode_key=episode_key,
            admitted_at=admitted_at,
        )
        if not admitted:
            with self._lock:
                self.counters["admission_replays"] += 1
            return False

        with self._lock:
            self.counters["new_admissions"] += 1
            if len(self.selected_episode_keys) >= self.max_episodes:
                self.counters["not_selected_after_predeclared_cap"] += 1
                return True
            if episode_key in self.selected_episode_keys:
                raise RuntimeError("new episode selected twice")
            self.selected_episode_keys.add(episode_key)
            self.counters["selected_for_research"] += 1

        job = _EpisodeJob(
            episode_key=episode_key,
            enqueued_monotonic=time.monotonic(),
        )
        handoff: Future[None] = Future()

        def enqueue_and_ack() -> None:
            try:
                self._enqueue_selected_job(job)
            except Exception as exc:
                handoff.set_exception(exc)
            else:
                handoff.set_result(None)

        self._loop.call_soon_threadsafe(enqueue_and_ack)
        handoff.result(timeout=5.0)
        return True

    def _enqueue_selected_job(self, job: _EpisodeJob) -> None:
        try:
            self.hazard_queue.put_nowait(job)
            self.research_queue.put_nowait(job)
            self.counters["hazard_jobs_enqueued"] += 1
            self.counters["research_jobs_enqueued"] += 1
            self.counters["hazard_queue_high_water"] = max(
                self.counters["hazard_queue_high_water"],
                self.hazard_queue.qsize(),
            )
            self.counters["research_queue_high_water"] = max(
                self.counters["research_queue_high_water"],
                self.research_queue.qsize(),
            )
        except asyncio.QueueFull as exc:
            self.counters["downstream_queue_overflow"] += 1
            raise RuntimeError("selected downstream queue overflow") from exc

    async def _run_blocking(self, fn):
        if self._executor is None:
            raise RuntimeError("coordinator executor is unavailable")
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn)

    async def _hazard_worker(self, index: int) -> None:
        while True:
            job = await self.hazard_queue.get()
            try:
                episode = get_market_opportunity_episode(job.episode_key)
                if episode is None:
                    self.counters["hazard_missing_episode"] += 1
                    continue

                def capture():
                    self.hazard_pacer.wait_for_slot()
                    return self.hazard_probe.capture(episode)

                result = await self._run_blocking(capture)
                self.counters[
                    f"hazard_status_{result.attempt.status.lower()}"
                ] += 1
                if result.reused_attempt:
                    self.counters["hazard_reused_attempts"] += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                self.counters["hazard_worker_errors"] += 1
                raise
            finally:
                self.hazard_queue.task_done()

    async def _wait_for_hazard(self, episode):
        deadline = time.monotonic() + self.hazard_wait_timeout_seconds
        attempt_key = SolanaRPCMintHazardProbe.attempt_key(episode)
        while True:
            attempt = load_provider_attempt(attempt_key=attempt_key)
            if attempt is not None and attempt.status in FINAL_PROVIDER_STATUSES:
                return attempt
            if time.monotonic() >= deadline:
                return attempt
            await asyncio.sleep(0.05)

    async def _research_worker(self, index: int) -> None:
        while True:
            job = await self.research_queue.get()
            try:
                episode = get_market_opportunity_episode(job.episode_key)
                if episode is None:
                    self.counters["research_missing_episode"] += 1
                    continue

                hazard = await self._wait_for_hazard(episode)
                if hazard is None or hazard.status not in FINAL_PROVIDER_STATUSES:
                    self.counters["hazard_wait_timeout"] += 1
                    continue
                if hazard.status != "AVAILABLE":
                    self.counters[
                        f"hazard_terminal_{hazard.status.lower()}"
                    ] += 1
                    self.disposition_latencies_seconds.append(
                        time.monotonic() - job.enqueued_monotonic
                    )
                    continue

                self.counters["entry_eligible"] += 1

                def capture_entry():
                    self.entry_pacer.wait_for_slot()
                    return self.entry_probe.capture(
                        episode,
                        hazard_attempt=hazard,
                    )

                result = await self._run_blocking(capture_entry)
                self.counters[
                    f"entry_status_{result.attempt.status.lower()}"
                ] += 1
                if result.reused_attempt:
                    self.counters["entry_reused_attempts"] += 1
                if result.attempt.status != "AVAILABLE" or result.quote is None:
                    self.disposition_latencies_seconds.append(
                        time.monotonic() - job.enqueued_monotonic
                    )
                    continue
                if result.quote.executable:
                    self.counters["route_only_executable_violations"] += 1
                    continue

                decision = await self._run_blocking(
                    lambda: freeze_route_research_decision(
                        episode=episode,
                        entry_attempt=result.attempt,
                        hazard_attempt=hazard,
                    )
                )
                self.counters["research_decisions_frozen"] += 1
                if (
                    decision.research_decision_as_of
                    < episode.first_trigger_observed_at
                ):
                    self.counters[
                        "research_decision_clock_violations"
                    ] += 1

                outcomes = load_route_research_outcomes(
                    acquisition_run_key=self.acquisition_run_key,
                    episode_key=episode.episode_key,
                )
                if [item.horizon_seconds for item in outcomes] != [
                    300,
                    900,
                    3600,
                ]:
                    self.counters["research_schedule_violations"] += 1
                self.counters["research_outcomes_scheduled"] += len(outcomes)
                elapsed = time.monotonic() - job.enqueued_monotonic
                self.decision_latencies_seconds.append(elapsed)
                self.disposition_latencies_seconds.append(elapsed)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.counters["research_worker_errors"] += 1
                raise
            finally:
                self.research_queue.task_done()

    async def drain(self) -> None:
        await self.hazard_queue.join()
        await self.research_queue.join()

    async def close(self) -> None:
        if not self._started:
            return
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=False)
        self._tasks = []
        self._executor = None
        self._started = False

    def snapshot(self) -> dict:
        hazard = self.hazard_pacer.snapshot()
        entry = self.entry_pacer.snapshot()
        return {
            "version": SIGNAL_PLANE_ROUTE_RESEARCH_COORDINATOR_VERSION,
            "run_key": self.acquisition_run_key,
            "selected_episode_count": len(self.selected_episode_keys),
            "counters": dict(sorted(self.counters.items())),
            "hazard_queue_depth": self.hazard_queue.qsize(),
            "research_queue_depth": self.research_queue.qsize(),
            "hazard_pacer": {
                "interval_ms": hazard.interval_ms,
                "starts": hazard.starts,
                "waited_starts": hazard.waited_starts,
            },
            "entry_pacer": {
                "interval_ms": entry.interval_ms,
                "starts": entry.starts,
                "waited_starts": entry.waited_starts,
            },
        }
