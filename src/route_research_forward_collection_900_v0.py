from __future__ import annotations

from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import time

from src.jupiter_research_exit_route import (
    JupiterResearchExitRouteConfig,
    JupiterResearchExitRouteProbe,
)
from src.opportunity_route_research_store import (
    load_due_route_research_outcomes,
    load_route_research_outcomes,
)
from src.provider_start_pacer_v44 import ProviderStartPacerV44


VERSION = "route_research_forward_collection_900_v0"
TARGET_HORIZONS = (300, 900)


@dataclass(frozen=True)
class ForwardCollection900Summary:
    scheduled_target: int
    statuses_target: dict[str, int]
    by_horizon: dict[int, dict[str, int]]
    submitted: int
    collector_errors: int
    executable_semantic_violations: int
    target_lateness_seconds: tuple[int, ...]
    classification: str

    @property
    def target_lateness_p95_seconds(self) -> int | None:
        if not self.target_lateness_seconds:
            return None
        ordered = sorted(self.target_lateness_seconds)
        index = min(
            len(ordered) - 1,
            int(round(0.95 * (len(ordered) - 1))),
        )
        return ordered[index]


def collect_route_research_forward_through_900_v0(
    *,
    acquisition_run_key: str,
    api_key: str | None,
    workers: int = 6,
    poll_ms: int = 100,
    jupiter_timeout_seconds: int = 5,
    slippage_bps: int = 100,
    exit_start_interval_ms: int = 250,
    max_due_per_poll: int = 100,
    target_grace_seconds: int = 30,
    hard_runtime_cap_seconds: int = 2400,
) -> ForwardCollection900Summary:
    run_key = str(acquisition_run_key).strip()
    if not run_key:
        raise ValueError("acquisition_run_key cannot be empty")
    if min(
        workers,
        poll_ms,
        jupiter_timeout_seconds,
        max_due_per_poll,
        target_grace_seconds,
        hard_runtime_cap_seconds,
    ) <= 0:
        raise ValueError("collector counts/timeouts must be positive")
    if exit_start_interval_ms < 0:
        raise ValueError("exit_start_interval_ms cannot be negative")

    initial_all = load_route_research_outcomes(acquisition_run_key=run_key)
    initial = [
        item
        for item in initial_all
        if item.horizon_seconds in TARGET_HORIZONS
    ]
    if not initial:
        return ForwardCollection900Summary(
            scheduled_target=0,
            statuses_target={},
            by_horizon={},
            submitted=0,
            collector_errors=0,
            executable_semantic_violations=0,
            target_lateness_seconds=(),
            classification="INCONCLUSIVE_NO_300_900_SCHEDULE",
        )

    latest_target = max(item.target_at for item in initial)
    remaining = max(
        0,
        latest_target + target_grace_seconds - int(time.time()),
    )
    runtime_seconds = min(
        hard_runtime_cap_seconds,
        remaining + jupiter_timeout_seconds + 2,
    )
    deadline = time.monotonic() + runtime_seconds

    probe = JupiterResearchExitRouteProbe(
        JupiterResearchExitRouteConfig(
            api_key=api_key,
            timeout_seconds=jupiter_timeout_seconds,
            slippage_bps=slippage_bps,
        )
    )
    pacer = ProviderStartPacerV44(interval_ms=exit_start_interval_ms)
    counters: Counter[str] = Counter()
    inflight: dict[Future, object] = {}
    inflight_keys: set[str] = set()
    lateness_seconds: list[int] = []

    def capture(outcome):
        pacer.wait_for_slot()
        return probe.capture(outcome)

    def harvest_done() -> None:
        done = [future for future in inflight if future.done()]
        for future in done:
            outcome = inflight.pop(future)
            inflight_keys.discard(outcome.outcome_key)
            try:
                result = future.result()
                counters[f"provider_{result.attempt.status.lower()}"] += 1
                counters[f"outcome_{result.outcome.status.lower()}"] += 1
                if result.quote is not None:
                    if result.quote.executable:
                        counters["executable_semantic_violations"] += 1
                    lateness_seconds.append(
                        result.quote.observed_at - outcome.target_at
                    )
                print(
                    f"[memory-forward-900] episode={outcome.episode_key[-12:]} "
                    f"horizon={outcome.horizon_seconds}s "
                    f"provider={result.attempt.status} "
                    f"outcome={result.outcome.status}"
                )
            except Exception as exc:
                counters["collector_errors"] += 1
                print(
                    f"[memory-forward-900-error] "
                    f"episode={outcome.episode_key[-12:]} "
                    f"horizon={outcome.horizon_seconds}s "
                    f"error={type(exc).__name__}:{exc}"
                )

    with ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="memory-forward-900",
    ) as executor:
        while time.monotonic() < deadline:
            harvest_done()
            now = int(time.time())
            due = load_due_route_research_outcomes(
                acquisition_run_key=run_key,
                as_of=now,
                limit=max_due_per_poll,
            )
            for outcome in due:
                if outcome.horizon_seconds not in TARGET_HORIZONS:
                    continue
                if outcome.outcome_key in inflight_keys:
                    continue
                inflight_keys.add(outcome.outcome_key)
                inflight[executor.submit(capture, outcome)] = outcome
                counters["submitted"] += 1

            if not inflight:
                snapshot = [
                    item
                    for item in load_route_research_outcomes(
                        acquisition_run_key=run_key
                    )
                    if item.horizon_seconds in TARGET_HORIZONS
                ]
                if snapshot and all(
                    item.status != "PENDING" for item in snapshot
                ):
                    break
            time.sleep(poll_ms / 1000.0)

        for future in list(inflight):
            try:
                future.result(
                    timeout=max(1, jupiter_timeout_seconds + 2)
                )
            except Exception:
                pass
        harvest_done()

    final = [
        item
        for item in load_route_research_outcomes(
            acquisition_run_key=run_key
        )
        if item.horizon_seconds in TARGET_HORIZONS
    ]
    statuses = Counter(item.status for item in final)
    by_horizon_counter: dict[int, Counter[str]] = {}
    for item in final:
        by_horizon_counter.setdefault(
            item.horizon_seconds,
            Counter(),
        )[item.status] += 1

    if (
        counters["collector_errors"]
        or counters["executable_semantic_violations"]
    ):
        classification = "FAIL_MEMORY_FORWARD_900_COLLECTION"
    elif statuses.get("AVAILABLE", 0) == 0:
        classification = "INCONCLUSIVE_MEMORY_NO_AVAILABLE_300_900_OUTCOME"
    elif statuses.get("PENDING", 0) > 0:
        classification = "FAIL_MEMORY_PENDING_300_900_OUTCOME"
    else:
        classification = "PASS_MEMORY_FORWARD_300_900_COMPLETE"

    return ForwardCollection900Summary(
        scheduled_target=len(final),
        statuses_target=dict(statuses),
        by_horizon={
            horizon: dict(values)
            for horizon, values in by_horizon_counter.items()
        },
        submitted=counters["submitted"],
        collector_errors=counters["collector_errors"],
        executable_semantic_violations=(
            counters["executable_semantic_violations"]
        ),
        target_lateness_seconds=tuple(lateness_seconds),
        classification=classification,
    )
