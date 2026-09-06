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


@dataclass(frozen=True)
class ForwardCollectionV43Summary:
    scheduled: int
    statuses: dict[str, int]
    by_horizon: dict[int, dict[str, int]]
    submitted: int
    reused_attempts: int
    collector_errors: int
    executable_semantic_violations: int
    target_lateness_seconds: tuple[int, ...]
    classification: str

    @property
    def target_lateness_p95_seconds(self) -> int | None:
        if not self.target_lateness_seconds:
            return None
        ordered = sorted(self.target_lateness_seconds)
        index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return ordered[index]


def collect_route_research_forward_v43(
    *,
    acquisition_run_key: str,
    api_key: str | None,
    workers: int = 6,
    poll_ms: int = 100,
    jupiter_timeout_seconds: int = 5,
    slippage_bps: int = 100,
    max_due_per_poll: int = 100,
    target_grace_seconds: int = 30,
    hard_runtime_cap_seconds: int = 7200,
) -> ForwardCollectionV43Summary:
    """Collect exact due route-only SELL labels through the final scheduled target.

    The runtime deadline is derived from the latest persisted target plus a small grace window.
    This avoids a magic duration and, more importantly, starts from a fresh schedule that already
    exists before any target is due. No official outcome is written and no backfill is attempted.
    """

    run_key = str(acquisition_run_key).strip()
    if not run_key:
        raise ValueError("acquisition_run_key cannot be empty")
    if min(workers, poll_ms, jupiter_timeout_seconds, max_due_per_poll, target_grace_seconds) <= 0:
        raise ValueError("collector counts/timeouts/grace must be positive")
    if not 0 <= slippage_bps <= 10_000:
        raise ValueError("slippage_bps must be between 0 and 10000")

    initial = load_route_research_outcomes(acquisition_run_key=run_key)
    if not initial:
        return ForwardCollectionV43Summary(
            scheduled=0,
            statuses={},
            by_horizon={},
            submitted=0,
            reused_attempts=0,
            collector_errors=0,
            executable_semantic_violations=0,
            target_lateness_seconds=(),
            classification="INCONCLUSIVE_NO_ROUTE_RESEARCH_SCHEDULE",
        )

    latest_target = max(item.target_at for item in initial)
    remaining = max(0, latest_target + target_grace_seconds - int(time.time()))
    runtime_seconds = min(hard_runtime_cap_seconds, remaining + jupiter_timeout_seconds + 2)
    deadline = time.monotonic() + runtime_seconds

    print(
        f"[v43-forward] scheduled={len(initial)} latest_target={latest_target} "
        f"derived_runtime_seconds={runtime_seconds} workers={workers} poll_ms={poll_ms}"
    )

    probe = JupiterResearchExitRouteProbe(
        JupiterResearchExitRouteConfig(
            api_key=api_key,
            timeout_seconds=jupiter_timeout_seconds,
            slippage_bps=slippage_bps,
        )
    )
    counters: Counter[str] = Counter()
    inflight: dict[Future, object] = {}
    inflight_keys: set[str] = set()
    lateness_seconds: list[int] = []

    def harvest_done() -> None:
        done = [future for future in inflight if future.done()]
        for future in done:
            outcome = inflight.pop(future)
            inflight_keys.discard(outcome.outcome_key)
            try:
                result = future.result()
                counters[f"provider_{result.attempt.status.lower()}"] += 1
                counters[f"outcome_{result.outcome.status.lower()}"] += 1
                counters["reused_attempts"] += int(result.reused_attempt)
                if result.quote is not None:
                    if result.quote.executable:
                        counters["executable_semantic_violations"] += 1
                    lateness_seconds.append(result.quote.observed_at - outcome.target_at)
                print(
                    f"[v43-forward] episode={outcome.episode_key[-12:]} "
                    f"horizon={outcome.horizon_seconds}s target={outcome.target_at} "
                    f"provider={result.attempt.status} outcome={result.outcome.status} "
                    f"observed_at={result.outcome.observed_at} reused={result.reused_attempt}"
                )
            except Exception as exc:
                counters["collector_errors"] += 1
                print(
                    f"[v43-forward-error] episode={outcome.episode_key[-12:]} "
                    f"horizon={outcome.horizon_seconds}s error={type(exc).__name__}:{exc}"
                )

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="route-forward-v43") as executor:
        while time.monotonic() < deadline:
            harvest_done()
            now = int(time.time())
            due = load_due_route_research_outcomes(
                acquisition_run_key=run_key,
                as_of=now,
                limit=max_due_per_poll,
            )
            for outcome in due:
                if outcome.outcome_key in inflight_keys:
                    continue
                inflight_keys.add(outcome.outcome_key)
                inflight[executor.submit(probe.capture, outcome)] = outcome
                counters["submitted"] += 1

            if not inflight:
                snapshot = load_route_research_outcomes(acquisition_run_key=run_key)
                if snapshot and all(item.status != "PENDING" for item in snapshot):
                    break
            time.sleep(poll_ms / 1000.0)

        for future in list(inflight):
            try:
                future.result(timeout=max(1, jupiter_timeout_seconds + 2))
            except Exception:
                pass
        harvest_done()

    final = load_route_research_outcomes(acquisition_run_key=run_key)
    statuses = Counter(item.status for item in final)
    by_horizon_counter: dict[int, Counter[str]] = {}
    for item in final:
        by_horizon_counter.setdefault(item.horizon_seconds, Counter())[item.status] += 1

    if counters["collector_errors"] or counters["executable_semantic_violations"]:
        classification = "FAIL_ROUTE_ONLY_FORWARD_COLLECTION"
    elif statuses.get("AVAILABLE", 0) == 0:
        classification = "INCONCLUSIVE_NO_AVAILABLE_ROUTE_OUTCOME"
    elif statuses.get("PENDING", 0) > 0:
        classification = "FAIL_V43_PENDING_AFTER_FINAL_TARGET"
    else:
        classification = "PASS_ROUTE_ONLY_FORWARD_COLLECTION_COMPLETE"

    return ForwardCollectionV43Summary(
        scheduled=len(final),
        statuses=dict(statuses),
        by_horizon={horizon: dict(values) for horizon, values in by_horizon_counter.items()},
        submitted=counters["submitted"],
        reused_attempts=counters["reused_attempts"],
        collector_errors=counters["collector_errors"],
        executable_semantic_violations=counters["executable_semantic_violations"],
        target_lateness_seconds=tuple(lateness_seconds),
        classification=classification,
    )
