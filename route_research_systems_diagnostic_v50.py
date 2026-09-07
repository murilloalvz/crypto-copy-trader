from __future__ import annotations

import argparse
import contextlib
import io
import sys

from src.opportunity_route_research_store import load_route_research_outcomes
import route_research_forward_cohort_v43 as v43
import route_research_forward_cohort_v44 as v44
import unified_market_execution_quote_smoke_v31 as v31
import unified_market_route_research_smoke_v50 as v50


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


def diagnostic_capture_complete_v50(output: str) -> bool:
    """Accept v50 attribution only when the tracer explicitly proves full coverage."""

    return (
        "V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC" in output
        and "trace_attribution_complete=True" in output
        and "dominant_clock=insufficient_trace" not in output
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fresh v50 systems-only diagnostic over v49 scheduling. It attributes PumpSwap "
            "global sequence HOL delay and intentionally prevents forward SELL collection."
        )
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--hazard-start-interval-ms", type=int, default=650)
    parser.add_argument("--entry-start-interval-ms", type=int, default=1000)
    parser.add_argument("--exit-start-interval-ms", type=int, default=250)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    run_key = args.run_key.strip()
    if not run_key:
        raise SystemExit("--run-key cannot be empty")
    if min(
        args.hazard_start_interval_ms,
        args.entry_start_interval_ms,
        args.exit_start_interval_ms,
    ) < 0:
        raise SystemExit("provider pacing intervals cannot be negative")
    if load_route_research_outcomes(acquisition_run_key=run_key):
        raise SystemExit(
            "v50 systems diagnostic run-key already has persisted route research outcomes; "
            "use a fresh key"
        )

    original_v42_run = v43.v42.run_smoke_v42
    original_pump_prepare_workers = v31.PASS_PUMP_PREPARE_WORKERS
    original_schedule_audit = v43._cohort_schedule_audit
    original_argv = list(sys.argv)

    def _systems_only_schedule_audit(_run_key: str) -> tuple[int, int, bool]:
        return 0, 0, False

    capture = io.StringIO()
    tee = _Tee(sys.stdout, capture)

    v43.v42.run_smoke_v42 = v50.run_smoke_v50
    v31.PASS_PUMP_PREPARE_WORKERS = v50.v49.V49_PUMP_PREPARE_WORKERS
    v43._cohort_schedule_audit = _systems_only_schedule_audit
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
            v44.main()
    finally:
        sys.argv = original_argv
        v43.v42.run_smoke_v42 = original_v42_run
        v31.PASS_PUMP_PREPARE_WORKERS = original_pump_prepare_workers
        v43._cohort_schedule_audit = original_schedule_audit

    output = capture.getvalue()
    systems_pass = (
        "result=11/11" in output
        and "classification=FAIL_V43_SAME_RUN_SYSTEMS_GATE" not in output
    )
    collector_started = "V43 FORWARD COLLECTION START" in output
    diagnostic_present = "V50 PUMPSWAP CAUSAL CLOCK ATTRIBUTION DIAGNOSTIC" in output
    diagnostic_complete = diagnostic_capture_complete_v50(output)

    print("\nV50 SYSTEMS DIAGNOSTIC GUARD")
    print(
        f"systems_11_of_11={systems_pass} diagnostic_present={diagnostic_present} "
        f"diagnostic_complete={diagnostic_complete} forward_collector_started={collector_started}"
    )
    if collector_started:
        print("classification=FAIL_V50_SYSTEMS_ONLY_GUARD")
        return 2
    if not diagnostic_present:
        print("classification=FAIL_V50_DIAGNOSTIC_MISSING")
        return 2
    if not diagnostic_complete:
        print("classification=FAIL_V50_DIAGNOSTIC_INCOMPLETE")
        print(
            "Interpretation: the same-run systems result remains valid on its own, but no causal "
            "clock attribution may be accepted from an incomplete v50 trace."
        )
        return 2

    print("classification=PASS_V50_DIAGNOSTIC_CAPTURE")
    print(
        "Interpretation: v50 successfully captured complete observational causal-clock attribution. "
        "The same-run 11/11 result, if present, remains a separate systems result; v50 itself "
        "does not validate Flow60 or any economic edge."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
