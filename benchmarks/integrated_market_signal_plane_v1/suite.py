from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import tempfile
import time
from typing import Iterable

from benchmarks.commodity_signal_plane_v0.benchmark import (
    BoundedMemoryRadarState,
    ReferenceRadarState,
    TraceRecord,
    generate_synthetic_trace,
    load_trace,
)
from benchmarks.integrated_market_signal_plane_v1.optimized_kernel import (
    PrevalidatedBoundedMemoryRadarState,
)

VERSION = "integrated_market_signal_plane_v1"
REPRESENTATIVE_EPS = 5_000.0
HEADROOM_EPS = 7_500.0
RESEARCH_BUFFER = 1_024
RESEARCH_SLOW_EVERY = 100
RESEARCH_SLOW_MS = 5.0


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * pct / 100.0
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return float(ordered[lo])
    weight = rank - lo
    return float(ordered[lo] * (1.0 - weight) + ordered[hi] * weight)


def _trigger_snapshot(trigger) -> dict | None:
    if trigger is None:
        return None
    return {
        "token_mint": trigger.token_mint,
        "as_of": trigger.as_of,
        "method_version": trigger.method_version,
        "trigger_kind": trigger.trigger_kind,
        "direction": trigger.direction,
        "features": asdict(trigger.features),
    }


def record_to_canonical_event(record: TraceRecord) -> dict:
    payload = {
        "schema_version": "canonical_market_event_v1",
        "sequence": record.sequence,
        "arrival_offset_ns": record.arrival_offset_ns,
        "kind": record.kind,
        "event_key": record.event_key,
        "source_provider": record.source_provider,
    }
    if record.kind == "trade":
        assert record.trade is not None
        payload["observation"] = asdict(record.trade)
    else:
        assert record.lifecycle is not None
        payload["observation"] = asdict(record.lifecycle)
    return payload


def canonical_event_to_record(payload: dict) -> TraceRecord:
    from src.market_opportunity_radar import MarketLifecycleObservation, MarketTradeObservation

    if payload.get("schema_version") != "canonical_market_event_v1":
        raise ValueError("unsupported canonical event schema")
    kind = payload.get("kind")
    observation = payload.get("observation")
    if not isinstance(observation, dict):
        raise ValueError("canonical observation must be an object")

    base = {
        "sequence": int(payload["sequence"]),
        "arrival_offset_ns": int(payload["arrival_offset_ns"]),
        "kind": str(kind),
        "event_key": str(payload["event_key"]),
        "source_provider": str(payload["source_provider"]),
    }
    if kind == "trade":
        return TraceRecord(**base, trade=MarketTradeObservation(**observation))
    if kind == "lifecycle":
        return TraceRecord(**base, lifecycle=MarketLifecycleObservation(**observation))
    raise ValueError(f"unsupported canonical event kind: {kind!r}")


def _simulate_single_worker(arrivals_s: list[float], service_s: list[float]) -> dict:
    if len(arrivals_s) != len(service_s):
        raise ValueError("arrivals/service length mismatch")
    previous_end = 0.0
    waits: list[float] = []
    completions: list[float] = []
    active_completion_times: list[float] = []
    high_water = 0

    for arrival, service in zip(arrivals_s, service_s):
        active_completion_times = [x for x in active_completion_times if x > arrival]
        started = max(arrival, previous_end)
        ended = started + max(0.0, service)
        waits.append(started - arrival)
        completions.append(ended)
        active_completion_times.append(ended)
        high_water = max(high_water, len(active_completion_times))
        previous_end = ended

    if not arrivals_s:
        return {
            "queue_wait_p95_ms": 0.0,
            "queue_wait_p99_ms": 0.0,
            "outstanding_high_water": 0,
            "backlog_at_source_end": 0,
            "drain_after_source_ms": 0.0,
            "completion_times_s": [],
        }

    source_end = arrivals_s[-1]
    outstanding = sum(1 for x in completions if x > source_end)
    backlog = max(0, outstanding - 1)
    return {
        "queue_wait_p95_ms": _percentile(waits, 95.0) * 1000.0,
        "queue_wait_p99_ms": _percentile(waits, 99.0) * 1000.0,
        "outstanding_high_water": high_water,
        "backlog_at_source_end": backlog,
        "drain_after_source_ms": max(0.0, previous_end - source_end) * 1000.0,
        "completion_times_s": completions,
    }


def _simulate_bounded_research_handoff(
    arrivals_s: list[float], *, buffer: int, burst: bool = False
) -> dict:
    if buffer <= 0:
        raise ValueError("buffer must be positive")
    if burst:
        arrivals_s = [0.0 for _ in arrivals_s]

    completion_queue: list[float] = []
    accepted = 0
    dropped = 0
    high_water = 0
    final_completion = 0.0

    for sequence, arrival in enumerate(arrivals_s):
        completion_queue = [x for x in completion_queue if x > arrival]
        if len(completion_queue) >= buffer + 1:
            dropped += 1
            continue

        service_s = (
            RESEARCH_SLOW_MS / 1000.0
            if sequence > 0 and sequence % RESEARCH_SLOW_EVERY == 0
            else 0.0
        )
        started = max(arrival, completion_queue[-1] if completion_queue else arrival)
        ended = started + service_s
        completion_queue.append(ended)
        final_completion = max(final_completion, ended)
        accepted += 1
        high_water = max(high_water, len(completion_queue))

    return {
        "accepted": accepted,
        "dropped": dropped,
        "accounted": accepted + dropped,
        "worker_completed": accepted,
        "outstanding_high_water": high_water,
        "final_completion_ms": final_completion * 1000.0,
    }


def _fixed_arrivals(count: int, eps: float) -> list[float]:
    if eps <= 0:
        raise ValueError("eps must be positive")
    gap = 1.0 / eps
    return [index * gap for index in range(count)]


def _service_report(service_s: list[float], late_inserts: int) -> dict:
    mean_service = sum(service_s) / len(service_s) if service_s else 0.0
    return {
        "mean_ms": mean_service * 1000.0,
        "p95_ms": _percentile(service_s, 95.0) * 1000.0,
        "p99_ms": _percentile(service_s, 99.0) * 1000.0,
        "measured_capacity_eps_from_mean": (1.0 / mean_service) if mean_service > 0 else math.inf,
        "late_chain_time_inserts": late_inserts,
    }


def run_integrated(records: Iterable[TraceRecord]) -> dict:
    records = tuple(records)
    reference = ReferenceRadarState()
    baseline = BoundedMemoryRadarState()
    candidate = PrevalidatedBoundedMemoryRadarState()

    adapter_exact = 0
    baseline_matches = 0
    candidate_matches = 0
    baseline_mismatches: list[dict] = []
    candidate_mismatches: list[dict] = []
    baseline_service_s: list[float] = []
    candidate_service_s: list[float] = []
    trade_decisions = 0

    for record in records:
        encoded = record_to_canonical_event(record)
        decoded = canonical_event_to_record(encoded)
        if decoded == record:
            adapter_exact += 1

        reference_trigger = reference.ingest(record)

        started = time.perf_counter_ns()
        baseline_trigger = baseline.ingest(decoded)
        baseline_service_s.append((time.perf_counter_ns() - started) / 1_000_000_000.0)

        started = time.perf_counter_ns()
        candidate_trigger = candidate.ingest(decoded)
        candidate_service_s.append((time.perf_counter_ns() - started) / 1_000_000_000.0)

        if record.kind == "trade":
            trade_decisions += 1
            expected = _trigger_snapshot(reference_trigger)
            baseline_actual = _trigger_snapshot(baseline_trigger)
            candidate_actual = _trigger_snapshot(candidate_trigger)
            if expected == baseline_actual:
                baseline_matches += 1
            else:
                baseline_mismatches.append(
                    {"sequence": record.sequence, "expected": expected, "actual": baseline_actual}
                )
            if expected == candidate_actual:
                candidate_matches += 1
            else:
                candidate_mismatches.append(
                    {"sequence": record.sequence, "expected": expected, "actual": candidate_actual}
                )

    baseline_report = _service_report(baseline_service_s, baseline.late_chain_time_inserts)
    candidate_report = _service_report(candidate_service_s, candidate.late_chain_time_inserts)
    baseline_capacity = baseline_report["measured_capacity_eps_from_mean"]
    candidate_capacity = candidate_report["measured_capacity_eps_from_mean"]
    candidate_report["capacity_gain_pct_vs_baseline"] = (
        100.0 * (candidate_capacity / baseline_capacity - 1.0)
        if baseline_capacity and math.isfinite(baseline_capacity) and math.isfinite(candidate_capacity)
        else None
    )

    scenarios: dict[str, dict] = {}
    for name, eps in (("representative_5k", REPRESENTATIVE_EPS), ("headroom_7_5k", HEADROOM_EPS)):
        arrivals = _fixed_arrivals(len(records), eps)
        baseline_queue = _simulate_single_worker(arrivals, baseline_service_s)
        candidate_queue = _simulate_single_worker(arrivals, candidate_service_s)
        research = _simulate_bounded_research_handoff(
            candidate_queue["completion_times_s"], buffer=RESEARCH_BUFFER
        )
        scenarios[name] = {
            "eps": eps,
            "baseline_kernel_queue": {
                k: v for k, v in baseline_queue.items() if k != "completion_times_s"
            },
            "candidate_kernel_queue": {
                k: v for k, v in candidate_queue.items() if k != "completion_times_s"
            },
            "research_handoff": research,
        }

    burst = _simulate_bounded_research_handoff(
        [0.0 for _ in records], buffer=RESEARCH_BUFFER, burst=True
    )

    checks = {
        "canonical_adapter_exact": adapter_exact == len(records),
        "baseline_detector_parity_100": baseline_matches == trade_decisions and not baseline_mismatches,
        "candidate_detector_parity_100": candidate_matches == trade_decisions and not candidate_mismatches,
        "representative_candidate_no_backlog": scenarios["representative_5k"]["candidate_kernel_queue"]["backlog_at_source_end"] == 0,
        "headroom_candidate_no_backlog": scenarios["headroom_7_5k"]["candidate_kernel_queue"]["backlog_at_source_end"] == 0,
        "representative_research_zero_drop": scenarios["representative_5k"]["research_handoff"]["dropped"] == 0,
        "headroom_research_zero_drop": scenarios["headroom_7_5k"]["research_handoff"]["dropped"] == 0,
        "burst_accounting_explicit": burst["accounted"] == len(records),
        "burst_worker_reconciled": burst["worker_completed"] == burst["accepted"],
        "burst_exposes_bounded_overload": burst["dropped"] > 0,
    }

    if all(checks.values()):
        classification = "PASS_INTEGRATED_MARKET_SIGNAL_PLANE_V1"
        interpretation = (
            "The prevalidated memory-kernel candidate preserves frozen Radar semantics and sustains "
            "the frozen 5k events/s representative rate plus 1.5x headroom; slow research work remains "
            "isolated behind explicit bounded accounting. Candidate is eligible for production-safe refactor."
        )
    elif not checks["canonical_adapter_exact"] or not checks["candidate_detector_parity_100"]:
        classification = "FAIL_INTEGRATED_SIGNAL_SEMANTICS"
        interpretation = "Canonical adapter or optimized candidate diverged from the frozen Radar oracle."
    elif not checks["representative_candidate_no_backlog"] or not checks["headroom_candidate_no_backlog"]:
        classification = "PARTITION_OR_INCREMENTALIZE_MEMORY_KERNEL"
        interpretation = (
            "Validation removal alone is insufficient. Keep semantics frozen and move to indexed/incremental "
            "rolling-window state or partitioned per-asset execution."
        )
    else:
        classification = "ADAPT_RESEARCH_HANDOFF_POLICY"
        interpretation = "Kernel capacity/correctness holds but bounded downstream handoff policy needs adaptation."

    return {
        "type": "integrated_market_signal_plane_report",
        "version": VERSION,
        "record_count": len(records),
        "trade_decision_points": trade_decisions,
        "frozen_protocol": {
            "representative_eps": REPRESENTATIVE_EPS,
            "headroom_eps": HEADROOM_EPS,
            "research_buffer": RESEARCH_BUFFER,
            "research_slow_every": RESEARCH_SLOW_EVERY,
            "research_slow_ms": RESEARCH_SLOW_MS,
        },
        "adapter": {
            "exact_records": adapter_exact,
            "parity_pct": 100.0 if not records else 100.0 * adapter_exact / len(records),
        },
        "detector": {
            "baseline": {
                "exact_matches": baseline_matches,
                "mismatches": len(baseline_mismatches),
                "parity_pct": 100.0 if trade_decisions == 0 else 100.0 * baseline_matches / trade_decisions,
                "first_mismatches": baseline_mismatches[:20],
            },
            "candidate": {
                "exact_matches": candidate_matches,
                "mismatches": len(candidate_mismatches),
                "parity_pct": 100.0 if trade_decisions == 0 else 100.0 * candidate_matches / trade_decisions,
                "first_mismatches": candidate_mismatches[:20],
            },
        },
        "kernel_service": {
            "baseline": baseline_report,
            "prevalidated_candidate": candidate_report,
        },
        "scenarios": scenarios,
        "burst_research_handoff": burst,
        "checks": checks,
        "classification": classification,
        "interpretation": interpretation,
        "evidence_chain": {
            "decoder_semantics": "PASS_CARBON_DECODER_PARITY_V1 (150/150 exact events)",
            "carbon_runtime_boundary": "ADAPT_CARBON_RUNTIME_BOUNDARY",
            "this_benchmark_boundary": "canonical event -> adapter -> memory kernel -> bounded research handoff",
            "optimization_scope": "benchmark-local prevalidated evaluator; frozen Radar remains unchanged",
        },
    }


def run_suite(*, events: int, seed: int, out: Path) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        trace = Path(tmp) / "synthetic.jsonl"
        generate_synthetic_trace(out=trace, events=events, seed=seed)
        _, records = load_trace(trace)
        report = run_integrated(records)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Integrated Market Signal Plane replay v1")
    parser.add_argument("--events", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=68)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/integrated_market_signal_plane_v1/report.json"),
    )
    args = parser.parse_args()
    if args.events <= 0:
        raise SystemExit("--events must be positive")
    report = run_suite(events=args.events, seed=args.seed, out=args.out)
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["classification"] != "PASS_INTEGRATED_MARKET_SIGNAL_PLANE_V1":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
