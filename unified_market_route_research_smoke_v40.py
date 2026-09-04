from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import time

from src.config import settings
from src.jupiter_research_entry_route import (
    JupiterResearchEntryRouteConfig,
    JupiterResearchEntryRouteProbe,
)
from src.market_opportunity_episode_store import get_market_opportunity_episode
from src.opportunity_onchain_hazard import SolanaRPCMintHazardProbe
from src.opportunity_provider_attempt_store import FINAL_PROVIDER_STATUSES, load_provider_attempt
from src.opportunity_route_research_store import (
    freeze_route_research_decision,
    load_route_research_outcomes,
)
import unified_market_execution_quote_smoke_v31 as v31
import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v30 as v30
import unified_market_onchain_hazard_smoke_v37 as v37


@dataclass(frozen=True)
class ResearchJob:
    episode_key: str
    enqueued_monotonic: float


async def run_smoke_v40(
    *,
    max_research_episodes: int,
    research_workers: int,
    hazard_wait_timeout_seconds: int,
    jupiter_timeout_seconds: int,
    research_notional_usd: float,
    research_slippage_bps: int,
    **v37_kwargs,
) -> None:
    """Retain v37 market/hazard path and freeze a separate route-only research decision clock."""

    if min(max_research_episodes, research_workers, hazard_wait_timeout_seconds, jupiter_timeout_seconds) <= 0:
        raise ValueError("research counts/timeouts must be positive")
    if research_notional_usd <= 0:
        raise ValueError("research_notional_usd must be positive")
    if not 0 <= research_slippage_bps <= 10_000:
        raise ValueError("research_slippage_bps must be between 0 and 10000")

    original_admit = v19.admit_opportunity_episode
    research_queue: asyncio.Queue[ResearchJob] = asyncio.Queue(maxsize=max_research_episodes)
    selected: set[str] = set()
    counters: Counter[str] = Counter()
    latencies: list[float] = []
    executor = ThreadPoolExecutor(max_workers=research_workers, thread_name_prefix="route-research-v40")
    entry_probe = JupiterResearchEntryRouteProbe(
        JupiterResearchEntryRouteConfig(
            api_key=settings.jupiter_api_key,
            timeout_seconds=jupiter_timeout_seconds,
            notional_usd=research_notional_usd,
            slippage_bps=research_slippage_bps,
        )
    )

    def tracking_admit(**kwargs) -> bool:
        admitted = original_admit(**kwargs)
        if not admitted:
            return False
        counters["new_admissions"] += 1
        episode_key = str(kwargs["episode_key"])
        if len(selected) >= max_research_episodes:
            counters["not_selected_after_predeclared_cap"] += 1
            return True
        if episode_key in selected:
            raise RuntimeError("new episode admission unexpectedly selected twice")
        selected.add(episode_key)
        research_queue.put_nowait(ResearchJob(episode_key=episode_key, enqueued_monotonic=time.monotonic()))
        counters["selected_for_research"] += 1
        return True

    async def wait_for_hazard(episode, *, timeout_seconds: int):
        deadline = time.monotonic() + timeout_seconds
        attempt_key = SolanaRPCMintHazardProbe.attempt_key(episode)
        while True:
            attempt = load_provider_attempt(attempt_key=attempt_key)
            if attempt is not None and attempt.status in FINAL_PROVIDER_STATUSES:
                return attempt
            if time.monotonic() >= deadline:
                return attempt
            await asyncio.sleep(0.05)

    async def research_worker(index: int) -> None:
        loop = asyncio.get_running_loop()
        while True:
            job = await research_queue.get()
            try:
                episode = get_market_opportunity_episode(job.episode_key)
                if episode is None:
                    counters["missing_episode"] += 1
                    continue
                hazard = await wait_for_hazard(episode, timeout_seconds=hazard_wait_timeout_seconds)
                if hazard is None:
                    counters["hazard_wait_timeout"] += 1
                    continue
                if hazard.status != "AVAILABLE":
                    counters[f"hazard_terminal_{hazard.status.lower()}"] += 1
                    continue

                result = await loop.run_in_executor(
                    executor,
                    lambda: entry_probe.capture(episode, hazard_attempt=hazard),
                )
                counters[f"entry_status_{result.attempt.status.lower()}"] += 1
                if result.reused_attempt:
                    counters["reused_entry_attempts"] += 1
                if result.attempt.status != "AVAILABLE" or result.quote is None:
                    continue
                if result.quote.executable:
                    counters["route_only_executable_violations"] += 1
                    continue

                decision = await loop.run_in_executor(
                    executor,
                    lambda: freeze_route_research_decision(
                        episode=episode,
                        entry_attempt=result.attempt,
                        hazard_attempt=hazard,
                    ),
                )
                counters["research_decisions_frozen"] += 1
                if decision.research_decision_as_of < episode.first_trigger_observed_at:
                    counters["research_decision_clock_violations"] += 1
                reloaded_episode = get_market_opportunity_episode(episode.episode_key)
                if reloaded_episode is None or reloaded_episode.decision_as_of is not None:
                    counters["official_decision_mutation_violations"] += 1
                outcomes = load_route_research_outcomes(
                    acquisition_run_key=episode.acquisition_run_key,
                    episode_key=episode.episode_key,
                )
                if [item.horizon_seconds for item in outcomes] != [300, 900, 3600]:
                    counters["research_schedule_violations"] += 1
                counters["research_outcomes_scheduled"] += len(outcomes)
                latencies.append(time.monotonic() - job.enqueued_monotonic)
                print(
                    f"[route-research] worker={index} episode={episode.episode_key[-12:]} "
                    f"entry_status={result.attempt.status} decision_as_of={decision.research_decision_as_of} "
                    f"t0={episode.first_trigger_observed_at} scheduled={len(outcomes)}"
                )
            except Exception as exc:
                counters["research_worker_errors"] += 1
                print(
                    f"[route-research-error] worker={index} episode={job.episode_key[-12:]} "
                    f"error={type(exc).__name__}:{exc}"
                )
            finally:
                research_queue.task_done()

    workers = [
        asyncio.create_task(research_worker(index), name=f"route-research-v40-{index}")
        for index in range(research_workers)
    ]

    v19.admit_opportunity_episode = tracking_admit
    try:
        await v37.run_smoke_v37(**v37_kwargs)
        await research_queue.join()
    finally:
        v19.admit_opportunity_episode = original_admit
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        executor.shutdown(wait=True, cancel_futures=False)

    selected_count = counters["selected_for_research"]
    entry_terminal = sum(
        counters[f"entry_status_{status}"]
        for status in (
            "available",
            "unavailable",
            "config_missing",
            "provider_error",
            "metadata_error",
            "normalization_error",
        )
    )

    print("\nV40 ROUTE-ONLY CAUSAL RESEARCH DECISION DIAGNOSTIC")
    print(
        f"selected={selected_count} predeclared_cap={max_research_episodes} "
        f"research_workers={research_workers} research_notional_usd={research_notional_usd:.2f} "
        f"slippage_bps={research_slippage_bps}"
    )
    print(
        f"entry_statuses={{'AVAILABLE': {counters['entry_status_available']}, "
        f"'UNAVAILABLE': {counters['entry_status_unavailable']}, "
        f"'CONFIG_MISSING': {counters['entry_status_config_missing']}, "
        f"'PROVIDER_ERROR': {counters['entry_status_provider_error']}, "
        f"'METADATA_ERROR': {counters['entry_status_metadata_error']}, "
        f"'NORMALIZATION_ERROR': {counters['entry_status_normalization_error']}}} "
        f"terminal_coverage_pct={(100.0 * entry_terminal / selected_count if selected_count else 0.0):.1f}%"
    )
    print(
        f"research_decisions_frozen={counters['research_decisions_frozen']} "
        f"research_outcomes_scheduled={counters['research_outcomes_scheduled']} "
        f"hazard_wait_timeout={counters['hazard_wait_timeout']} "
        f"reused_entry_attempts={counters['reused_entry_attempts']} "
        f"research_worker_errors={counters['research_worker_errors']}"
    )
    print(
        f"route_only_executable_violations={counters['route_only_executable_violations']} "
        f"research_decision_clock_violations={counters['research_decision_clock_violations']} "
        f"official_decision_mutation_violations={counters['official_decision_mutation_violations']} "
        f"research_schedule_violations={counters['research_schedule_violations']} "
        f"not_selected_after_predeclared_cap={counters['not_selected_after_predeclared_cap']}"
    )
    print(f"episode_to_research_decision_ms {v19._latency_summary_ms(latencies)}")

    if not selected_count:
        classification = "INCONCLUSIVE_NO_SAMPLE"
    elif (
        entry_terminal == selected_count
        and counters["entry_status_available"] > 0
        and counters["entry_status_config_missing"] == 0
        and counters["reused_entry_attempts"] == 0
        and counters["research_worker_errors"] == 0
        and counters["route_only_executable_violations"] == 0
        and counters["research_decision_clock_violations"] == 0
        and counters["official_decision_mutation_violations"] == 0
        and counters["research_schedule_violations"] == 0
        and counters["research_decisions_frozen"] == counters["entry_status_available"]
        and counters["research_outcomes_scheduled"] == 3 * counters["research_decisions_frozen"]
    ):
        classification = "PASS_ROUTE_ONLY_RESEARCH_DECISION_PLUMBING"
    else:
        classification = "FAIL_ROUTE_ONLY_RESEARCH_DECISION_PLUMBING"
    print(f"route_research_decision_classification={classification}")
    print(
        "v40_note=research_decision_as_of is a separate paper-research clock. It does not write "
        "market_opportunity_episodes.decision_as_of and cannot satisfy funded executable entry."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fresh v40 route-only research decision smoke retaining the v37 market/hazard path"
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--commitment", default="confirmed")
    parser.add_argument("--max-hydrations", type=int, default=1500)
    parser.add_argument("--rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--pump-batch-size", type=int, default=32)
    parser.add_argument("--pump-batch-max-wait-ms", type=int, default=25)
    parser.add_argument("--pump-prepare-workers", type=int, default=v31.PASS_PUMP_PREPARE_WORKERS)
    parser.add_argument("--pumpswap-workers", type=int, default=v31.PASS_PUMPSWAP_WORKERS)
    parser.add_argument("--pumpswap-prepare-submitters", type=int, default=v31.PASS_PUMPSWAP_PREPARE_SUBMITTERS)
    parser.add_argument("--pumpswap-prepare-executor-workers", type=int, default=v31.PASS_PUMPSWAP_PREPARE_EXECUTOR_WORKERS)
    parser.add_argument("--pumpswap-writer-batch-size", type=int, default=32)
    parser.add_argument("--pumpswap-writer-batch-max-wait-ms", type=int, default=10)
    parser.add_argument("--max-concurrent-resolutions", type=int, default=18)
    parser.add_argument("--queue-size", type=int, default=5000)
    parser.add_argument("--continuation-batch-size", type=int, default=32)
    parser.add_argument("--continuation-batch-max-wait-ms", type=int, default=5)
    parser.add_argument("--default-io-workers", type=int, default=v31.PASS_DEFAULT_IO_WORKERS)
    parser.add_argument("--hydration-batch-size", type=int, default=64)
    parser.add_argument("--hydration-batch-max-wait-ms", type=int, default=5)
    parser.add_argument("--hedge-endpoints", type=int, default=2)
    parser.add_argument("--max-hazard-episodes", type=int, default=12)
    parser.add_argument("--hazard-workers", type=int, default=2)
    parser.add_argument("--hazard-rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--max-research-episodes", type=int, default=12)
    parser.add_argument("--research-workers", type=int, default=2)
    parser.add_argument("--hazard-wait-timeout-seconds", type=int, default=20)
    parser.add_argument("--jupiter-timeout-seconds", type=int, default=5)
    parser.add_argument("--research-notional-usd", type=float, default=25.0)
    parser.add_argument("--research-slippage-bps", type=int, default=100)
    args = parser.parse_args()

    if not 1 <= args.duration_seconds <= v19.MAX_SMOKE_SECONDS:
        parser.error(f"duration-seconds must be between 1 and {v19.MAX_SMOKE_SECONDS}")
    try:
        v30.validate_capacity_profile(
            pumpswap_workers=args.pumpswap_workers,
            pump_prepare_workers=args.pump_prepare_workers,
            pumpswap_prepare_submitters=args.pumpswap_prepare_submitters,
            pumpswap_prepare_executor_workers=args.pumpswap_prepare_executor_workers,
            default_io_workers=args.default_io_workers,
        )
    except ValueError as exc:
        parser.error(str(exc))

    print("Crypto Copy Trader — Unified Market Route-Only Research Smoke v40")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — fresh market/hazard + Jupiter route-only BUY; "
        "no taker, no signing, no execute, no transfer, no official decision freeze."
    )
    asyncio.run(
        run_smoke_v40(
            max_research_episodes=args.max_research_episodes,
            research_workers=args.research_workers,
            hazard_wait_timeout_seconds=args.hazard_wait_timeout_seconds,
            jupiter_timeout_seconds=args.jupiter_timeout_seconds,
            research_notional_usd=args.research_notional_usd,
            research_slippage_bps=args.research_slippage_bps,
            max_hazard_episodes=args.max_hazard_episodes,
            hazard_workers=args.hazard_workers,
            hazard_rpc_timeout_seconds=args.hazard_rpc_timeout_seconds,
            hydration_batch_size=args.hydration_batch_size,
            hydration_batch_max_wait_ms=args.hydration_batch_max_wait_ms,
            hedge_endpoints=args.hedge_endpoints,
            default_io_workers=args.default_io_workers,
            run_key=args.run_key,
            duration_seconds=args.duration_seconds,
            commitment=args.commitment,
            max_hydrations=args.max_hydrations,
            rpc_timeout_seconds=args.rpc_timeout_seconds,
            pump_batch_size=args.pump_batch_size,
            pump_batch_max_wait_ms=args.pump_batch_max_wait_ms,
            pump_prepare_workers=args.pump_prepare_workers,
            pumpswap_workers=args.pumpswap_workers,
            pumpswap_prepare_submitters=args.pumpswap_prepare_submitters,
            pumpswap_prepare_executor_workers=args.pumpswap_prepare_executor_workers,
            pumpswap_writer_batch_size=args.pumpswap_writer_batch_size,
            pumpswap_writer_batch_max_wait_ms=args.pumpswap_writer_batch_max_wait_ms,
            max_concurrent_resolutions=args.max_concurrent_resolutions,
            queue_size=args.queue_size,
            continuation_batch_size=args.continuation_batch_size,
            continuation_batch_max_wait_ms=args.continuation_batch_max_wait_ms,
        )
    )


if __name__ == "__main__":
    main()
