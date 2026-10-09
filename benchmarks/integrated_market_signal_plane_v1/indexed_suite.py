from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import tempfile
import time

from benchmarks.commodity_signal_plane_v0.benchmark import (
    ReferenceRadarState,
    TraceRecord,
    generate_synthetic_trace,
    load_trace,
)
from benchmarks.integrated_market_signal_plane_v1.indexed_kernel import IndexedWindowRadarState
from benchmarks.integrated_market_signal_plane_v1.optimized_kernel import (
    PrevalidatedBoundedMemoryRadarState,
)
from benchmarks.integrated_market_signal_plane_v1.suite import (
    HEADROOM_EPS,
    REPRESENTATIVE_EPS,
    RESEARCH_BUFFER,
    _fixed_arrivals,
    _simulate_bounded_research_handoff,
    _simulate_single_worker,
    _trigger_snapshot,
    canonical_event_to_record,
    record_to_canonical_event,
)

VERSION = "integrated_market_signal_plane_v1_indexed"


def _service_report(values: list[float], state) -> dict:
    mean = sum(values) / len(values) if values else 0.0
    ordered = sorted(values)

    def pct(p: float) -> float:
        if not ordered:
            return 0.0
        rank = (len(ordered) - 1) * p / 100.0
        lo = math.floor(rank)
        hi = math.ceil(rank)
        if lo == hi:
            return ordered[lo]
        weight = rank - lo
        return ordered[lo] * (1.0 - weight) + ordered[hi] * weight

    return {
        "mean_ms": mean * 1000.0,
        "p95_ms": pct(95.0) * 1000.0,
        "p99_ms": pct(99.0) * 1000.0,
        "capacity_eps_from_mean": (1.0 / mean) if mean > 0 else math.inf,
        "late_chain_time_inserts": int(getattr(state, "late_chain_time_inserts", 0)),
        "compactions": int(getattr(state, "compactions", 0)),
    }


def run_indexed(records: tuple[TraceRecord, ...]) -> dict:
    reference = ReferenceRadarState()
    prevalidated = PrevalidatedBoundedMemoryRadarState()
    indexed = IndexedWindowRadarState()

    adapter_exact = 0
    decisions = 0
    prevalidated_matches = 0
    indexed_matches = 0
    prevalidated_mismatches: list[dict] = []
    indexed_mismatches: list[dict] = []
    prevalidated_service: list[float] = []
    indexed_service: list[float] = []

    for record in records:
        decoded = canonical_event_to_record(record_to_canonical_event(record))
        if decoded == record:
            adapter_exact += 1

        expected_trigger = reference.ingest(record)

        started = time.perf_counter_ns()
        prevalidated_trigger = prevalidated.ingest(decoded)
        prevalidated_service.append((time.perf_counter_ns() - started) / 1_000_000_000.0)

        started = time.perf_counter_ns()
        indexed_trigger = indexed.ingest(decoded)
        indexed_service.append((time.perf_counter_ns() - started) / 1_000_000_000.0)

        if record.kind == "trade":
            decisions += 1
            expected = _trigger_snapshot(expected_trigger)
            p_actual = _trigger_snapshot(prevalidated_trigger)
            i_actual = _trigger_snapshot(indexed_trigger)
            if p_actual == expected:
                prevalidated_matches += 1
            else:
                prevalidated_mismatches.append(
                    {"sequence": record.sequence, "expected": expected, "actual": p_actual}
                )
            if i_actual == expected:
                indexed_matches += 1
            else:
                indexed_mismatches.append(
                    {"sequence": record.sequence, "expected": expected, "actual": i_actual}
                )

    prevalidated_report = _service_report(prevalidated_service, prevalidated)
    indexed_report = _service_report(indexed_service, indexed)
    indexed_report["capacity_gain_pct_vs_prevalidated"] = (
        100.0
        * (
            indexed_report["capacity_eps_from_mean"]
            / prevalidated_report["capacity_eps_from_mean"]
            - 1.0
        )
    )

    scenarios = {}
    for name, eps in (("representative_5k", REPRESENTATIVE_EPS), ("headroom_7_5k", HEADROOM_EPS)):
        arrivals = _fixed_arrivals(len(records), eps)
        pre_q = _simulate_single_worker(arrivals, prevalidated_service)
        idx_q = _simulate_single_worker(arrivals, indexed_service)
        research = _simulate_bounded_research_handoff(
            idx_q["completion_times_s"], buffer=RESEARCH_BUFFER
        )
        scenarios[name] = {
            "eps": eps,
            "prevalidated_queue": {k: v for k, v in pre_q.items() if k != "completion_times_s"},
            "indexed_queue": {k: v for k, v in idx_q.items() if k != "completion_times_s"},
            "research_handoff": research,
        }

    burst = _simulate_bounded_research_handoff(
        [0.0 for _ in records], buffer=RESEARCH_BUFFER, burst=True
    )
    checks = {
        "adapter_exact": adapter_exact == len(records),
        "prevalidated_parity_100": prevalidated_matches == decisions and not prevalidated_mismatches,
        "indexed_parity_100": indexed_matches == decisions and not indexed_mismatches,
        "indexed_5k_no_backlog": scenarios["representative_5k"]["indexed_queue"]["backlog_at_source_end"] == 0,
        "indexed_7_5k_no_backlog": scenarios["headroom_7_5k"]["indexed_queue"]["backlog_at_source_end"] == 0,
        "research_5k_zero_drop": scenarios["representative_5k"]["research_handoff"]["dropped"] == 0,
        "research_7_5k_zero_drop": scenarios["headroom_7_5k"]["research_handoff"]["dropped"] == 0,
        "burst_accounted": burst["accounted"] == len(records),
        "burst_worker_reconciled": burst["worker_completed"] == burst["accepted"],
        "burst_drop_explicit": burst["dropped"] > 0,
    }

    if all(checks.values()):
        classification = "PASS_INDEXED_MARKET_SIGNAL_PLANE_V1"
        interpretation = (
            "Indexed rolling-window state preserves 100% frozen Radar semantics while removing the "
            "270-second baseline scan from each decision and sustaining 5k plus 7.5k events/s headroom."
        )
    elif not checks["indexed_parity_100"]:
        classification = "FAIL_INDEXED_KERNEL_SEMANTICS"
        interpretation = "Indexed window semantics diverged; candidate is rejected until exact parity is restored."
    else:
        classification = "INDEXED_KERNEL_CAPACITY_INSUFFICIENT"
        interpretation = (
            "Indexed semantics hold but single-process Python still lacks the frozen capacity target; "
            "next test is process partitioning or moving the kernel to Rust."
        )

    return {
        "type": "integrated_market_signal_plane_indexed_report",
        "version": VERSION,
        "record_count": len(records),
        "trade_decision_points": decisions,
        "frozen_rates": {
            "representative_eps": REPRESENTATIVE_EPS,
            "headroom_eps": HEADROOM_EPS,
        },
        "adapter": {
            "exact_records": adapter_exact,
            "parity_pct": 100.0 if not records else 100.0 * adapter_exact / len(records),
        },
        "detector_parity": {
            "prevalidated_pct": 100.0 if not decisions else 100.0 * prevalidated_matches / decisions,
            "indexed_pct": 100.0 if not decisions else 100.0 * indexed_matches / decisions,
            "indexed_mismatches": indexed_mismatches[:20],
        },
        "service": {
            "prevalidated": prevalidated_report,
            "indexed": indexed_report,
        },
        "scenarios": scenarios,
        "burst_research_handoff": burst,
        "checks": checks,
        "classification": classification,
        "interpretation": interpretation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Indexed Market Signal Plane replay v1")
    parser.add_argument("--events", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=68)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/integrated_market_signal_plane_v1/indexed-report.json"),
    )
    args = parser.parse_args()
    if args.events <= 0:
        raise SystemExit("--events must be positive")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        trace = Path(tmp) / "trace.jsonl"
        generate_synthetic_trace(out=trace, events=args.events, seed=args.seed)
        _, records = load_trace(trace)
        report = run_indexed(records)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["classification"] != "PASS_INDEXED_MARKET_SIGNAL_PLANE_V1":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
