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
        # Tokio mpsc capacity counts buffered messages; one item may be in service.
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


def run_integrated(records: Iterable[TraceRecord]) -> dict:
    records = tuple(records)
    reference = ReferenceRadarState()
    kernel = BoundedMemoryRadarState()

    adapter_exact = 0
    parity_matches = 0
    parity_mismatches: list[dict] = []
    service_s: list[float] = []
    trade_decisions = 0

    for record in records:
        encoded = record_to_canonical_event(record)
        decoded = canonical_event_to_record(encoded)
        if decoded == record:
            adapter_exact += 1

        reference_trigger = reference.ingest(record)
        started = time.perf_counter_ns()
        kernel_trigger = kernel.ingest(decoded)
        service_s.append((time.perf_counter_ns() - started) / 1_000_000_000.0)

        if record.kind == "trade":
            trade_decisions += 1
            expected = _trigger_snapshot(reference_trigger)
            actual = _trigger_snapshot(kernel_trigger)
            if expected == actual:
                parity_matches += 1
            else:
                parity_mismatches.append(
                    {
                        "sequence": record.sequence,
                        "expected": expected,
                        "actual": actual,
                    }
                )

    kernel_p95_ms = _percentile(service_s, 95.0) * 1000.0
    kernel_p99_ms = _percentile(service_s, 99.0) * 1000.0
    mean_service = sum(service_s) / len(service_s) if service_s else 0.0
    measured_capacity_eps = (1.0 / mean_service) if mean_service > 0 else math.inf

    scenarios: dict[str, dict] = {}
    for name, eps in (("representative_5k", REPRESENTATIVE_EPS), ("headroom_7_5k", HEADROOM_EPS)):
        arrivals = _fixed_arrivals(len(records), eps)
        kernel_queue = _simulate_single_worker(arrivals, service_s)
        research = _simulate_bounded_research_handoff(
            kernel_queue["completion_times_s"], buffer=RESEARCH_BUFFER
        )
        kernel_queue = {k: v for k, v in kernel_queue.items() if k != "completion_times_s"}
        scenarios[name] = {
            "eps": eps,
            "kernel_queue": kernel_queue,
            "research_handoff": research,
        }

    burst_arrivals = [0.0 for _ in records]
    burst = _simulate_bounded_research_handoff(
        burst_arrivals, buffer=RESEARCH_BUFFER, burst=True
    )

    checks = {
        "canonical_adapter_exact": adapter_exact == len(records),
        "detector_parity_100": parity_matches == trade_decisions and not parity_mismatches,
        "representative_kernel_no_backlog": scenarios["representative_5k"]["kernel_queue"]["backlog_at_source_end"] == 0,
        "headroom_kernel_no_backlog": scenarios["headroom_7_5k"]["kernel_queue"]["backlog_at_source_end"] == 0,
        "representative_research_zero_drop": scenarios["representative_5k"]["research_handoff"]["dropped"] == 0,
        "headroom_research_zero_drop": scenarios["headroom_7_5k"]["research_handoff"]["dropped"] == 0,
        "burst_accounting_explicit": burst["accounted"] == len(records),
        "burst_worker_reconciled": burst["worker_completed"] == burst["accepted"],
        "burst_exposes_bounded_overload": burst["dropped"] > 0,
    }

    if all(checks.values()):
        classification = "PASS_INTEGRATED_MARKET_SIGNAL_PLANE_V1"
        interpretation = (
            "The canonical adapter and memory-first Radar kernel compose correctly, sustain the frozen "
            "5k events/s representative rate plus 1.5x headroom in the measured replay, and isolate slow "
            "research work behind a bounded handoff with explicit overload accounting."
        )
    elif not checks["canonical_adapter_exact"] or not checks["detector_parity_100"]:
        classification = "FAIL_INTEGRATED_SIGNAL_SEMANTICS"
        interpretation = "Canonical adapter or frozen Radar semantics diverged; do not optimize around this failure."
    elif not checks["representative_kernel_no_backlog"] or not checks["headroom_kernel_no_backlog"]:
        classification = "OPTIMIZE_OR_PARTITION_MEMORY_KERNEL"
        interpretation = "Correctness holds but the Python memory kernel lacks frozen 5k/7.5k capacity headroom."
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
            "exact_matches": parity_matches,
            "mismatches": len(parity_mismatches),
            "parity_pct": 100.0 if trade_decisions == 0 else 100.0 * parity_matches / trade_decisions,
            "first_mismatches": parity_mismatches[:20],
        },
        "kernel_service": {
            "mean_ms": mean_service * 1000.0,
            "p95_ms": kernel_p95_ms,
            "p99_ms": kernel_p99_ms,
            "measured_capacity_eps_from_mean": measured_capacity_eps,
            "late_chain_time_inserts": kernel.late_chain_time_inserts,
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
