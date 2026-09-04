from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
import time

from src.config import settings
from src.jupiter_research_exit_route import (
    JupiterResearchExitRouteConfig,
    JupiterResearchExitRouteProbe,
)
from src.opportunity_route_research_store import (
    load_due_route_research_outcomes,
    load_route_research_outcomes,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Continuously capture due +5/+15/+60 route-only SELL research outcomes. "
            "No taker, signing, execute, transfer or official forward-outcome writes."
        )
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=3700)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--poll-ms", type=int, default=100)
    parser.add_argument("--jupiter-timeout-seconds", type=int, default=5)
    parser.add_argument("--slippage-bps", type=int, default=100)
    parser.add_argument("--max-due-per-poll", type=int, default=100)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.duration_seconds <= 7200:
        raise SystemExit("--duration-seconds must be between 1 and 7200")
    if args.workers <= 0 or args.poll_ms <= 0 or args.max_due_per_poll <= 0:
        raise SystemExit("workers/poll/max-due must be positive")

    initial = load_route_research_outcomes(acquisition_run_key=args.run_key)
    print("Crypto Copy Trader — Route-Only Forward Collector v40")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — route-only SELL observations; no taker, "
        "no signing, no execute, no transfer, no official outcome completion."
    )
    print(
        f"run_key={args.run_key} scheduled={len(initial)} duration_seconds={args.duration_seconds} "
        f"workers={args.workers} poll_ms={args.poll_ms}"
    )
    if not initial:
        print("classification=INCONCLUSIVE_NO_ROUTE_RESEARCH_SCHEDULE")
        return 0

    probe = JupiterResearchExitRouteProbe(
        JupiterResearchExitRouteConfig(
            api_key=settings.jupiter_api_key,
            timeout_seconds=args.jupiter_timeout_seconds,
            slippage_bps=args.slippage_bps,
        )
    )
    counters: Counter[str] = Counter()
    inflight: dict[Future, object] = {}
    inflight_keys: set[str] = set()
    lateness_seconds: list[int] = []
    deadline = time.monotonic() + args.duration_seconds

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
                    f"[forward-route] episode={outcome.episode_key[-12:]} "
                    f"horizon={outcome.horizon_seconds}s target={outcome.target_at} "
                    f"provider={result.attempt.status} outcome={result.outcome.status} "
                    f"observed_at={result.outcome.observed_at} reused={result.reused_attempt}"
                )
            except Exception as exc:
                counters["collector_errors"] += 1
                print(
                    f"[forward-route-error] episode={outcome.episode_key[-12:]} "
                    f"horizon={outcome.horizon_seconds}s error={type(exc).__name__}:{exc}"
                )

    with ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="route-forward-v40") as executor:
        while time.monotonic() < deadline:
            harvest_done()
            now = int(time.time())
            due = load_due_route_research_outcomes(
                acquisition_run_key=args.run_key,
                as_of=now,
                limit=args.max_due_per_poll,
            )
            for outcome in due:
                if outcome.outcome_key in inflight_keys:
                    continue
                inflight_keys.add(outcome.outcome_key)
                inflight[executor.submit(probe.capture, outcome)] = outcome
                counters["submitted"] += 1
            if not inflight:
                # If all schedules are terminal, there is nothing left to wait for.
                snapshot = load_route_research_outcomes(acquisition_run_key=args.run_key)
                if snapshot and all(item.status != "PENDING" for item in snapshot):
                    break
            time.sleep(args.poll_ms / 1000.0)

        for future in list(inflight):
            try:
                future.result(timeout=max(1, args.jupiter_timeout_seconds + 2))
            except Exception:
                pass
        harvest_done()

    final = load_route_research_outcomes(acquisition_run_key=args.run_key)
    statuses = Counter(item.status for item in final)
    by_horizon: dict[int, Counter[str]] = {}
    for item in final:
        by_horizon.setdefault(item.horizon_seconds, Counter())[item.status] += 1

    print("\nSUMMARY")
    print(
        f"scheduled={len(final)} statuses={dict(statuses)} submitted={counters['submitted']} "
        f"reused_attempts={counters['reused_attempts']} collector_errors={counters['collector_errors']} "
        f"executable_semantic_violations={counters['executable_semantic_violations']}"
    )
    for horizon in sorted(by_horizon):
        print(f"horizon_{horizon}s={dict(by_horizon[horizon])}")
    if lateness_seconds:
        ordered = sorted(lateness_seconds)
        p50 = ordered[(len(ordered) - 1) // 2]
        p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
        print(
            f"target_lateness_seconds p50={p50} p95={p95} max={max(ordered)}"
        )

    if counters["collector_errors"] or counters["executable_semantic_violations"]:
        classification = "FAIL_ROUTE_ONLY_FORWARD_COLLECTION"
    elif statuses.get("AVAILABLE", 0) == 0:
        classification = "INCONCLUSIVE_NO_AVAILABLE_ROUTE_OUTCOME"
    elif statuses.get("PENDING", 0) > 0:
        classification = "PASS_ROUTE_ONLY_FORWARD_COLLECTION_PARTIAL"
    else:
        classification = "PASS_ROUTE_ONLY_FORWARD_COLLECTION_COMPLETE"
    print(f"classification={classification}")
    print(
        "Interpretation: route-only forward outcomes are causal paper research labels. They do not "
        "prove assemblable SELL, landing/fill or profitability after real execution costs."
    )
    return 2 if classification.startswith("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
