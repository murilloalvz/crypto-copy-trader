from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
import io
import re
import sys

from src.opportunity_route_research_store import load_route_research_outcomes
import route_research_forward_cohort_v43 as v43
import route_research_forward_cohort_v44 as v44
import route_research_systems_diagnostic_v50 as v50_gate
import unified_market_execution_quote_smoke_v31 as v31
import unified_market_route_research_smoke_v49 as v49
import unified_market_route_research_smoke_v54 as v54


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


@dataclass(frozen=True)
class V54Verdict:
    systems_pass: bool
    collector_started: bool
    v50_attribution_ok: bool
    v51_present: bool
    v52_present: bool
    v52_cleanup_present: bool
    v53_present: bool
    v54_present: bool
    v54_prefetcher_ok: bool
    v54_demand_only_ok: bool
    classification: str


def classify_v54_output(output: str) -> V54Verdict:
    systems_pass = (
        "result=11/11" in output
        and "classification=FAIL_V43_SAME_RUN_SYSTEMS_GATE" not in output
    )
    collector_started = "V43 FORWARD COLLECTION START" in output
    v50_attribution_ok = v50_gate.diagnostic_capture_complete_v50(output)
    v51_present = "V51 STATEFUL-PRIORITY READY-QUEUE DIAGNOSTIC" in output
    v52_present = "V52 PUMPSWAP HEDGED RPC WALL-DEADLINE DIAGNOSTIC" in output
    v52_cleanup_present = "hedge_cleanup_ms " in output
    v53_present = "V53 OPPORTUNISTIC PREFETCH / RESOLVER WAIT DIAGNOSTIC" in output
    v54_present = "V54 DEMAND-ONLY RESOLVER ADMISSION DIAGNOSTIC" in output
    v54_prefetcher_ok = "v54_prefetcher_instance=missing" not in output
    v54_match = re.search(
        r"V54 DEMAND-ONLY RESOLVER ADMISSION DIAGNOSTIC\n[^\n]*scheduled=(\d+)[^\n]*skipped_speculative=(\d+)",
        output,
    )
    v54_demand_only_ok = bool(
        v54_match
        and int(v54_match.group(1)) == 0
        and int(v54_match.group(2)) >= 0
    )

    required = (
        v51_present
        and v52_present
        and v52_cleanup_present
        and v53_present
        and v54_present
        and v54_prefetcher_ok
        and v54_demand_only_ok
    )
    if collector_started:
        classification = "FAIL_V54_SYSTEMS_ONLY_GUARD"
    elif not required:
        classification = "FAIL_V54_DIAGNOSTIC_MISSING"
    elif systems_pass and v50_attribution_ok:
        classification = "PASS_V54_DEMAND_ONLY_RESOLUTION_SYSTEMS_PROFILE"
    elif systems_pass:
        classification = "PASS_V54_DEMAND_ONLY_RESOLUTION_SYSTEMS_PROFILE_DIAGNOSTIC_INCOMPLETE"
    elif v50_attribution_ok:
        classification = "FAIL_V54_DEMAND_ONLY_RESOLUTION_SYSTEMS_PROFILE"
    else:
        classification = "FAIL_V54_DEMAND_ONLY_RESOLUTION_SYSTEMS_PROFILE_DIAGNOSTIC_INCOMPLETE"

    return V54Verdict(
        systems_pass=systems_pass,
        collector_started=collector_started,
        v50_attribution_ok=v50_attribution_ok,
        v51_present=v51_present,
        v52_present=v52_present,
        v52_cleanup_present=v52_cleanup_present,
        v53_present=v53_present,
        v54_present=v54_present,
        v54_prefetcher_ok=v54_prefetcher_ok,
        v54_demand_only_ok=v54_demand_only_ok,
        classification=classification,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fresh v54 systems-only validation of demand-only PumpSwap resolver admission. "
            "Forward SELL collection is blocked."
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
            "v54 systems run-key already has persisted route research outcomes; use a fresh key"
        )

    original_v42_run = v43.v42.run_smoke_v42
    original_pump_prepare_workers = v31.PASS_PUMP_PREPARE_WORKERS
    original_schedule_audit = v43._cohort_schedule_audit
    original_argv = list(sys.argv)

    def _systems_only_schedule_audit(_run_key: str) -> tuple[int, int, bool]:
        return 0, 0, False

    capture = io.StringIO()
    tee = _Tee(sys.stdout, capture)

    v43.v42.run_smoke_v42 = v54.run_smoke_v54
    v31.PASS_PUMP_PREPARE_WORKERS = v49.V49_PUMP_PREPARE_WORKERS
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

    verdict = classify_v54_output(capture.getvalue())

    print("\nV54 SYSTEMS STABILITY GUARD")
    print(
        f"systems_11_of_11={verdict.systems_pass} "
        f"v50_causal_attribution_ok={verdict.v50_attribution_ok} "
        f"v51_diagnostic_present={verdict.v51_present} "
        f"v52_diagnostic_present={verdict.v52_present} "
        f"v52_cleanup_present={verdict.v52_cleanup_present} "
        f"v53_diagnostic_present={verdict.v53_present} "
        f"v54_diagnostic_present={verdict.v54_present} "
        f"v54_prefetcher_instance_ok={verdict.v54_prefetcher_ok} "
        f"v54_demand_only_ok={verdict.v54_demand_only_ok} "
        f"forward_collector_started={verdict.collector_started}"
    )
    print(f"classification={verdict.classification}")

    if verdict.collector_started:
        return 2
    if not (
        verdict.v51_present
        and verdict.v52_present
        and verdict.v52_cleanup_present
        and verdict.v53_present
        and verdict.v54_present
        and verdict.v54_prefetcher_ok
        and verdict.v54_demand_only_ok
    ):
        return 2
    if not verdict.systems_pass:
        print(
            "Interpretation: demand-only resolver admission did not stabilize the unchanged 11-gate "
            "profile. Keep Flow60 NOT_EVALUATED. Because speculative resolver ownership is absent, "
            "use the same-run v53 demand pool-lock/capacity waits and v50 barrier clocks to decide "
            "whether remaining HOL is authoritative same-pool single-flight or a different stage."
        )
        return 2
    if not verdict.v50_attribution_ok:
        print(
            "Interpretation: systems passed while exact v50 attribution was incomplete at the frozen "
            "deadline. Preserve the systems PASS independently; do not infer a causal clock from an "
            "incomplete trace."
        )
        return 0

    print(
        "Interpretation: the unchanged systems gate passed with speculative PumpSwap resolver "
        "ownership removed. This validates only a systems profile; it does not validate Flow60, "
        "route-only profitability, fills or live-money readiness."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
