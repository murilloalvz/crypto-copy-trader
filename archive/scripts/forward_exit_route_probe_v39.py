from __future__ import annotations

import argparse
from collections import Counter
import time

from src.config import settings
from src.jupiter_forward_exit_route import (
    JupiterForwardExitRouteConfig,
    JupiterForwardExitRouteProbe,
)
from src.opportunity_forward_due import load_due_opportunity_forward_outcomes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read due official forward schedules and capture Jupiter SELL route-only evidence. "
            "This runner never completes an official outcome and never signs/submits a transaction."
        )
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--max-outcomes", type=int, default=12)
    parser.add_argument("--timeout-seconds", type=int, default=5)
    parser.add_argument("--slippage-bps", type=int, default=100)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.max_outcomes <= 0:
        raise SystemExit("--max-outcomes must be positive")

    now = int(time.time())
    due = load_due_opportunity_forward_outcomes(
        as_of=now,
        acquisition_run_key=args.run_key,
        limit=args.max_outcomes,
    )

    print("Crypto Copy Trader — Forward Exit Route-Only Probe v39")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — no official outcome completion, "
        "no taker, no signing, no execute."
    )
    print(
        f"run_key={args.run_key} due={len(due)} max_outcomes={args.max_outcomes} "
        f"as_of={now}"
    )

    if not due:
        print("\nSUMMARY")
        print("due=0 attempts=0 route_available=0 provider_errors=0 reused=0")
        print("classification=INCONCLUSIVE_NO_DUE_OFFICIAL_FORWARD_OUTCOMES")
        return 0

    probe = JupiterForwardExitRouteProbe(
        JupiterForwardExitRouteConfig(
            api_key=settings.jupiter_api_key,
            timeout_seconds=args.timeout_seconds,
            slippage_bps=args.slippage_bps,
        )
    )

    statuses: Counter[str] = Counter()
    reused = 0
    route_available = 0
    non_executable_available = 0
    official_completion_violations = 0
    lateness: list[int] = []

    print("\nOUTCOMES")
    for index, outcome in enumerate(due, start=1):
        try:
            result = probe.capture(outcome)
        except Exception as exc:
            statuses["RUNNER_ERROR"] += 1
            print(
                f"[{index:02d}] episode={outcome.episode_key} horizon={outcome.horizon_seconds}s "
                f"target={outcome.target_at} status=RUNNER_ERROR error={type(exc).__name__}:{exc}"
            )
            continue

        statuses[result.attempt.status] += 1
        reused += int(result.reused_attempt)
        if result.attempt.status == "AVAILABLE":
            route_available += 1
            if result.quote is not None and not result.quote.executable:
                non_executable_available += 1
            if bool(result.attempt.details.get("official_forward_outcome_completed")):
                official_completion_violations += 1
            value = result.attempt.details.get("target_lateness_seconds")
            if isinstance(value, int):
                lateness.append(value)

        print(
            f"[{index:02d}] episode={outcome.episode_key} horizon={outcome.horizon_seconds}s "
            f"target={outcome.target_at} status={result.attempt.status} "
            f"route_id={(result.quote.route_id if result.quote else None)} "
            f"executable={(result.quote.executable if result.quote else None)} "
            f"reused={result.reused_attempt}"
        )

    classification = "PASS_ROUTE_ONLY_FORWARD_OBSERVABILITY"
    if statuses.get("RUNNER_ERROR", 0) > 0 or official_completion_violations > 0:
        classification = "FAIL_FORWARD_ROUTE_PLUMBING"
    elif route_available == 0:
        classification = "INCONCLUSIVE_NO_AVAILABLE_FORWARD_ROUTE"
    elif non_executable_available != route_available:
        classification = "FAIL_ROUTE_ONLY_EXECUTABILITY_SEMANTICS"

    print("\nSUMMARY")
    print(
        f"due={len(due)} attempts={sum(statuses.values())} statuses={dict(statuses)} "
        f"route_available={route_available} non_executable_available={non_executable_available} "
        f"reused={reused} official_completion_violations={official_completion_violations}"
    )
    if lateness:
        ordered = sorted(lateness)
        p50 = ordered[(len(ordered) - 1) // 2]
        p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
        print(
            f"target_lateness_seconds p50={p50} p95={p95} max={max(ordered)}"
        )
    print(f"classification={classification}")
    print(
        "Interpretation: PASS here means route-only observability works. It is NOT official "
        "executable-forward-outcome PASS and does not establish economic edge."
    )
    return 0 if not classification.startswith("FAIL") else 2


if __name__ == "__main__":
    raise SystemExit(main())
