from __future__ import annotations

import argparse
import ast
import asyncio
import contextlib
from dataclasses import dataclass
import io
import re
import sys

from src.config import settings
from src.opportunity_route_research_store import load_route_research_outcomes
from src.route_research_evaluation import evaluate_route_research_run
from src.route_research_forward_collection_v43 import collect_route_research_forward_v43
import unified_market_execution_quote_smoke_v31 as v31
import unified_market_latency_smoke_v19 as v19
import unified_market_latency_smoke_v30 as v30
import unified_market_route_research_smoke_v42 as v42


@dataclass(frozen=True)
class SystemsGateV43:
    passed: bool
    passed_count: int
    coverage_pct: float
    true_backlog_pct: float
    pump_p95_ms: float
    pumpswap_p95_ms: float
    checks: tuple[tuple[str, bool], ...]


class _Tee(io.TextIOBase):
    def __init__(self, *streams) -> None:
        self._streams = streams

    def write(self, text: str) -> int:
        for stream in self._streams:
            stream.write(text)
            stream.flush()
        return len(text)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


def _last_float(pattern: str, text: str) -> float | None:
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    return float(matches[-1]) if matches else None


def _all_ints(pattern: str, text: str) -> tuple[int, ...]:
    return tuple(int(item) for item in re.findall(pattern, text, flags=re.MULTILINE))


def _dict_after(label: str, text: str) -> dict:
    match = re.search(rf"{re.escape(label)}=(\{{[^\n]*\}})", text)
    if not match:
        return {}
    try:
        value = ast.literal_eval(match.group(1))
    except (ValueError, SyntaxError):
        return {}
    return value if isinstance(value, dict) else {}


def audit_systems_gate_v43(output: str) -> SystemsGateV43:
    received = _dict_after("received", output)
    processed = _dict_after("radar_processed", output)
    worker_errors = _dict_after("worker_errors", output)
    dropped = _dict_after("dropped", output)

    total_received = sum(int(value) for value in received.values()) if received else 0
    total_processed = sum(int(value) for value in processed.values()) if processed else 0
    true_backlog_pct = (
        100.0 * max(0, total_received - total_processed) / total_received
        if total_received
        else 100.0
    )
    coverage = _last_float(r"radar_coverage_pct=([0-9.]+)%", output) or 0.0
    pump_p95 = _last_float(
        r"pump_radar_end_to_end_wait_ms[^\n]*p95=([0-9.]+)", output
    ) or float("inf")
    pumpswap_p95 = _last_float(
        r"pumpswap_pipeline_end_to_end_ms[^\n]*p95=([0-9.]+)", output
    ) or float("inf")
    reference_assets = _all_ints(r"reference_asset_episodes=(\d+)", output)
    budget_skips = _all_ints(r"budget_skips=(\d+)", output)
    superset_violations = _all_ints(r"reservation_superset_violations=(\d+)", output)
    bundle_wallets = _last_float(r"bundle_wallets_total=(\d+)", output) or 0.0
    bundle_flow = _last_float(r"bundle_flow30_total=(\d+)", output) or 0.0
    replay_auditable = "continuation_writer_fatal_error=False" in output

    checks = (
        ("no_worker_errors", not worker_errors),
        ("drops_zero", not dropped),
        ("reference_asset_episodes_zero", bool(reference_assets) and max(reference_assets) == 0),
        ("coverage_ge_95pct", coverage >= 95.0),
        ("true_backlog_le_5pct", true_backlog_pct <= 5.0),
        ("pump_p95_le_5s", pump_p95 <= 5000.0),
        ("pumpswap_p95_le_5s", pumpswap_p95 <= 5000.0),
        ("hydration_budget_skips_zero", bool(budget_skips) and max(budget_skips) == 0),
        ("bundles_nonempty", bundle_wallets > 0 and bundle_flow > 0),
        ("replay_auditable", replay_auditable),
        (
            "reservation_superset_violations_zero",
            bool(superset_violations) and max(superset_violations) == 0,
        ),
    )
    passed_count = sum(1 for _, passed in checks if passed)
    return SystemsGateV43(
        passed=passed_count == len(checks),
        passed_count=passed_count,
        coverage_pct=coverage,
        true_backlog_pct=true_backlog_pct,
        pump_p95_ms=pump_p95,
        pumpswap_p95_ms=pumpswap_p95,
        checks=checks,
    )


def _cohort_schedule_audit(run_key: str) -> tuple[int, int, bool]:
    outcomes = load_route_research_outcomes(acquisition_run_key=run_key)
    by_episode: dict[str, set[int]] = {}
    for item in outcomes:
        by_episode.setdefault(item.episode_key, set()).add(item.horizon_seconds)
    complete = sum(1 for horizons in by_episode.values() if horizons == {300, 900, 3600})
    return len(by_episode), len(outcomes), complete == len(by_episode)


def _print_evaluation(run_key: str) -> tuple[int, int]:
    evaluation = evaluate_route_research_run(acquisition_run_key=run_key)
    print("\nV43 DESCRIPTIVE ROUTE-ONLY ECONOMIC EVALUATION")
    print(f"run_key={run_key} lineage_violations={evaluation.lineage_violations}")
    ready_horizons = 0
    for metrics in evaluation.horizons:
        if metrics.classification == "DESCRIPTIVE_SAMPLE_READY_FOR_ANALYSIS":
            ready_horizons += 1
        print(
            f"horizon={metrics.horizon_seconds}s scheduled={metrics.scheduled} "
            f"available={metrics.available} pending={metrics.pending} "
            f"unavailable_or_error={metrics.unavailable_or_error} "
            f"coverage={metrics.coverage_pct:.1f}% positive_share={metrics.positive_share_pct} "
            f"mean={metrics.mean_return_pct} median={metrics.median_return_pct} "
            f"profit_factor={metrics.profit_factor} best={metrics.best_return_pct} "
            f"worst={metrics.worst_return_pct} mean_without_best={metrics.mean_without_best_pct} "
            f"largest_winner_share={metrics.largest_winner_share_of_gross_profit_pct} "
            f"classification={metrics.classification}"
        )
    return evaluation.lineage_violations, ready_horizons


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fresh integrated v43 route-only economic cohort: v42 acquisition + exact forward collector"
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--max-research-episodes", type=int, default=40)
    parser.add_argument("--min-research-decisions", type=int, default=30)
    parser.add_argument("--research-workers", type=int, default=4)
    parser.add_argument("--hazard-workers", type=int, default=4)
    parser.add_argument("--forward-workers", type=int, default=6)
    parser.add_argument("--forward-poll-ms", type=int, default=100)
    parser.add_argument("--target-lateness-p95-max-seconds", type=int, default=2)
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
    parser.add_argument("--hydration-batch-workers", type=int, default=8)
    parser.add_argument("--hazard-rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--hazard-wait-timeout-seconds", type=int, default=30)
    parser.add_argument("--jupiter-timeout-seconds", type=int, default=5)
    parser.add_argument("--research-notional-usd", type=float, default=25.0)
    parser.add_argument("--research-slippage-bps", type=int, default=100)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 1 <= args.duration_seconds <= v19.MAX_SMOKE_SECONDS:
        raise SystemExit(f"--duration-seconds must be between 1 and {v19.MAX_SMOKE_SECONDS}")
    if args.min_research_decisions < 30:
        raise SystemExit("v43 descriptive cohort requires --min-research-decisions >= 30")
    if args.max_research_episodes < args.min_research_decisions:
        raise SystemExit("--max-research-episodes must be >= --min-research-decisions")
    if min(args.research_workers, args.hazard_workers, args.forward_workers) <= 0:
        raise SystemExit("worker counts must be positive")
    try:
        v30.validate_capacity_profile(
            pumpswap_workers=args.pumpswap_workers,
            pump_prepare_workers=args.pump_prepare_workers,
            pumpswap_prepare_submitters=args.pumpswap_prepare_submitters,
            pumpswap_prepare_executor_workers=args.pumpswap_prepare_executor_workers,
            default_io_workers=args.default_io_workers,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.hydration_batch_workers * args.hedge_endpoints > args.max_concurrent_resolutions:
        raise SystemExit(
            "hydration-batch-workers * hedge-endpoints must not exceed max-concurrent-resolutions"
        )

    print("Crypto Copy Trader — Route-Only Forward Economic Cohort v43")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — frozen v42 market path + route-only causal BUY/SELL; "
        "no taker, signing, transaction submission, transfer or official decision freeze."
    )
    print(
        f"run_key={args.run_key} acquisition_seconds={args.duration_seconds} "
        f"cohort_cap={args.max_research_episodes} minimum_clean_decisions={args.min_research_decisions}"
    )

    capture = io.StringIO()
    tee = _Tee(sys.stdout, capture)
    with contextlib.redirect_stdout(tee):
        asyncio.run(
            v42.run_smoke_v42(
                max_research_episodes=args.max_research_episodes,
                research_workers=args.research_workers,
                hazard_wait_timeout_seconds=args.hazard_wait_timeout_seconds,
                jupiter_timeout_seconds=args.jupiter_timeout_seconds,
                research_notional_usd=args.research_notional_usd,
                research_slippage_bps=args.research_slippage_bps,
                hydration_batch_workers=args.hydration_batch_workers,
                max_hazard_episodes=args.max_research_episodes,
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

    systems = audit_systems_gate_v43(capture.getvalue())
    print("\nV43 SAME-RUN SYSTEMS GATE")
    for name, passed in systems.checks:
        print(f"{name}={'PASS' if passed else 'FAIL'}")
    print(
        f"coverage_pct={systems.coverage_pct:.1f} true_backlog_pct={systems.true_backlog_pct:.3f} "
        f"pump_p95_ms={systems.pump_p95_ms:.1f} pumpswap_p95_ms={systems.pumpswap_p95_ms:.1f} "
        f"result={systems.passed_count}/11"
    )
    if not systems.passed:
        print("classification=FAIL_V43_SAME_RUN_SYSTEMS_GATE")
        print("No forward economic collection started because systems evidence did not pass 11/11.")
        return 2

    decision_count, scheduled_count, schedule_complete = _cohort_schedule_audit(args.run_key)
    print("\nV43 FRESH COHORT ADMISSION GATE")
    print(
        f"research_decisions={decision_count} scheduled_outcomes={scheduled_count} "
        f"exact_three_horizons_per_decision={schedule_complete} minimum={args.min_research_decisions}"
    )
    if decision_count < args.min_research_decisions or not schedule_complete:
        print("classification=INCONCLUSIVE_V43_COHORT_LT_MINIMUM")
        print("No forward collector started. This run is preserved as an undersized fresh cohort.")
        return 0

    print("classification=PASS_V43_FRESH_COHORT_ADMISSION")
    print("\nV43 FORWARD COLLECTION START")
    collection = collect_route_research_forward_v43(
        acquisition_run_key=args.run_key,
        api_key=settings.jupiter_api_key,
        workers=args.forward_workers,
        poll_ms=args.forward_poll_ms,
        jupiter_timeout_seconds=args.jupiter_timeout_seconds,
        slippage_bps=args.research_slippage_bps,
    )
    lateness_p95 = collection.target_lateness_p95_seconds
    print("\nV43 FORWARD COLLECTION SUMMARY")
    print(
        f"scheduled={collection.scheduled} statuses={collection.statuses} "
        f"submitted={collection.submitted} reused_attempts={collection.reused_attempts} "
        f"collector_errors={collection.collector_errors} "
        f"executable_semantic_violations={collection.executable_semantic_violations}"
    )
    for horizon in sorted(collection.by_horizon):
        print(f"horizon_{horizon}s={collection.by_horizon[horizon]}")
    if collection.target_lateness_seconds:
        print(
            f"target_lateness_seconds p50={sorted(collection.target_lateness_seconds)[(len(collection.target_lateness_seconds)-1)//2]} "
            f"p95={lateness_p95} max={max(collection.target_lateness_seconds)}"
        )
    print(f"forward_collection_classification={collection.classification}")

    lateness_pass = lateness_p95 is not None and lateness_p95 <= args.target_lateness_p95_max_seconds
    lineage_violations, ready_horizons = _print_evaluation(args.run_key)

    final_pass = (
        collection.classification == "PASS_ROUTE_ONLY_FORWARD_COLLECTION_COMPLETE"
        and lateness_pass
        and lineage_violations == 0
        and ready_horizons == 3
    )
    print("\nV43 FINAL COHORT CLASSIFICATION")
    print(
        f"systems_11_of_11={systems.passed} decisions_ge_minimum={decision_count >= args.min_research_decisions} "
        f"forward_complete={collection.classification == 'PASS_ROUTE_ONLY_FORWARD_COLLECTION_COMPLETE'} "
        f"target_lateness_p95_le_{args.target_lateness_p95_max_seconds}s={lateness_pass} "
        f"lineage_violations={lineage_violations} descriptive_ready_horizons={ready_horizons}/3"
    )
    print(
        "classification="
        + ("READY_FOR_DESCRIPTIVE_RESEARCH_REVIEW" if final_pass else "INCONCLUSIVE_V43_FORWARD_COHORT")
    )
    print(
        "Interpretation: READY means sample/lineage/observability are sufficient for descriptive "
        "research review only. It is not a profitability, executability, landing/fill or live-money PASS."
    )
    return 0 if final_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
