from __future__ import annotations

import argparse
import contextlib
import io
import re
import sys

import route_research_forward_cohort_v44 as v44
from src.route_research_multi_evaluation_v46 import evaluate_route_research_runs_v46


SUBCOHORT_SUFFIXES = ("A", "B")
SUBCOHORT_CAP = 40
SUBCOHORT_MIN_DECISIONS = 30


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "v46 dual prospective route-only cohort. Runs two complete frozen v44 subcohorts "
            "sequentially so each acquisition keeps cap=40 and same-run systems 11/11."
        )
    )
    parser.add_argument("--run-key", required=True, help="Base run key; -A and -B are appended")
    parser.add_argument("--hazard-start-interval-ms", type=int, default=650)
    parser.add_argument("--entry-start-interval-ms", type=int, default=1000)
    parser.add_argument("--exit-start-interval-ms", type=int, default=250)
    return parser


def _run_key(base: str, suffix: str) -> str:
    return f"{base}-{suffix}"


def _parse_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text, flags=re.MULTILINE)
    return int(match.group(1)) if match else None


def _subcohort_gate(output: str) -> tuple[bool, dict[str, object]]:
    systems = "result=11/11" in output and "classification=FAIL_V43_SAME_RUN_SYSTEMS_GATE" not in output
    decisions = _parse_int(r"research_decisions=(\d+) scheduled_outcomes=", output)
    forward_complete = "forward_collection_classification=PASS_ROUTE_ONLY_FORWARD_COLLECTION_COMPLETE" in output
    lineage = _parse_int(r"lineage_violations=(\d+)", output)
    lateness = _parse_int(r"target_lateness_seconds[^\n]*p95=(\d+)", output)
    admitted = decisions is not None and decisions >= SUBCOHORT_MIN_DECISIONS
    passed = (
        systems
        and admitted
        and forward_complete
        and lineage == 0
        and lateness is not None
        and lateness <= 2
    )
    return passed, {
        "systems_11_of_11": systems,
        "research_decisions": decisions,
        "forward_complete": forward_complete,
        "lineage_violations": lineage,
        "target_lateness_p95_seconds": lateness,
    }


def _run_v44_subcohort(*, run_key: str, args) -> tuple[int, str]:
    original_argv = list(sys.argv)
    capture = io.StringIO()
    tee = _Tee(sys.stdout, capture)
    try:
        sys.argv = [
            "route_research_forward_cohort_v44.py",
            "--run-key",
            run_key,
            "--hazard-start-interval-ms",
            str(args.hazard_start_interval_ms),
            "--entry-start-interval-ms",
            str(args.entry_start_interval_ms),
            "--exit-start-interval-ms",
            str(args.exit_start_interval_ms),
        ]
        with contextlib.redirect_stdout(tee):
            result = int(v44.main())
    finally:
        sys.argv = original_argv
    return result, capture.getvalue()


def _print_aggregate(run_keys: tuple[str, ...]) -> tuple[int, int]:
    evaluation = evaluate_route_research_runs_v46(acquisition_run_keys=run_keys)
    print("\nV46 AGGREGATED DESCRIPTIVE ROUTE-ONLY ECONOMIC EVALUATION")
    print(f"run_keys={run_keys} lineage_violations={evaluation.lineage_violations}")
    ready = 0
    for metrics in evaluation.horizons:
        if metrics.classification == "DESCRIPTIVE_SAMPLE_READY_FOR_ANALYSIS":
            ready += 1
        print(
            f"horizon={metrics.horizon_seconds}s scheduled={metrics.scheduled} "
            f"available={metrics.available} pending={metrics.pending} "
            f"unavailable_or_error={metrics.unavailable_or_error} coverage={metrics.coverage_pct:.1f}% "
            f"positive_share={metrics.positive_share_pct} mean={metrics.mean_return_pct} "
            f"median={metrics.median_return_pct} profit_factor={metrics.profit_factor} "
            f"best={metrics.best_return_pct} worst={metrics.worst_return_pct} "
            f"mean_without_best={metrics.mean_without_best_pct} "
            f"largest_winner_share={metrics.largest_winner_share_of_gross_profit_pct} "
            f"classification={metrics.classification}"
        )
    return evaluation.lineage_violations, ready


def main() -> int:
    args = build_parser().parse_args()
    base = args.run_key.strip()
    if not base:
        raise SystemExit("--run-key cannot be empty")
    if min(args.hazard_start_interval_ms, args.entry_start_interval_ms, args.exit_start_interval_ms) < 0:
        raise SystemExit("provider pacing intervals cannot be negative")

    run_keys = tuple(_run_key(base, suffix) for suffix in SUBCOHORT_SUFFIXES)
    print("Crypto Copy Trader — Dual Prospective Route-Only Forward Cohort v46")
    print(
        "Mode: PAPER / RESEARCH / READ ONLY — two complete v44 subcohorts run sequentially; "
        "each keeps cap=40/minimum=30 and must independently pass systems/collector gates."
    )
    print(
        f"base_run_key={base} subcohorts={run_keys} cap_per_subcohort={SUBCOHORT_CAP} "
        f"minimum_decisions_per_subcohort={SUBCOHORT_MIN_DECISIONS}"
    )

    gates: list[tuple[str, bool, dict[str, object]]] = []
    for run_key in run_keys:
        print(f"\nV46 SUBCOHORT START run_key={run_key}")
        _, output = _run_v44_subcohort(run_key=run_key, args=args)
        passed, details = _subcohort_gate(output)
        gates.append((run_key, passed, details))
        print(f"\nV46 SUBCOHORT GATE run_key={run_key}")
        print(
            f"systems_11_of_11={details['systems_11_of_11']} "
            f"research_decisions={details['research_decisions']} "
            f"forward_complete={details['forward_complete']} "
            f"target_lateness_p95_seconds={details['target_lateness_p95_seconds']} "
            f"lineage_violations={details['lineage_violations']} "
            f"classification={'PASS_V46_SUBCOHORT' if passed else 'FAIL_V46_SUBCOHORT'}"
        )
        if not passed:
            print("V46 stops fail-closed. The second/aggregate stage is not used to rescue a failed subcohort.")
            return 2

    lineage_violations, ready_horizons = _print_aggregate(run_keys)
    final_pass = lineage_violations == 0 and ready_horizons == 3
    print("\nV46 FINAL AGGREGATE CLASSIFICATION")
    print(
        f"subcohorts_passed={sum(1 for _, passed, _ in gates if passed)}/2 "
        f"aggregate_lineage_violations={lineage_violations} "
        f"descriptive_ready_horizons={ready_horizons}/3"
    )
    print(
        "classification="
        + ("READY_FOR_DESCRIPTIVE_RESEARCH_REVIEW" if final_pass else "INCONCLUSIVE_V46_AGGREGATE")
    )
    print(
        "Interpretation: aggregate READY is descriptive sample/lineage readiness across two "
        "predeclared independent fresh subcohorts. It is not profitability, executability, fill or live-money PASS."
    )
    return 0 if final_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
