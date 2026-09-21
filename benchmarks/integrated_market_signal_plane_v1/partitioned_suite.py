from __future__ import annotations

import argparse
import hashlib
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
from benchmarks.integrated_market_signal_plane_v1.suite import (
    HEADROOM_EPS,
    REPRESENTATIVE_EPS,
    RESEARCH_BUFFER,
    _fixed_arrivals,
    _percentile,
    _simulate_bounded_research_handoff,
    _trigger_snapshot,
)

VERSION = "integrated_market_signal_plane_v1_partitioned_v0"
DEFAULT_SHARDS = (1, 2, 4)


def _token_mint(record: TraceRecord) -> str:
    if record.kind == "trade":
        assert record.trade is not None
        return record.trade.token_mint
    assert record.lifecycle is not None
    return record.lifecycle.token_mint


def _shard_for_token(token_mint: str, shard_count: int) -> int:
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    digest = hashlib.sha256(token_mint.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % shard_count


def _service_report(values: list[float]) -> dict:
    mean = sum(values) / len(values) if values else 0.0
    return {
        "mean_ms": mean * 1000.0,
        "p95_ms": _percentile(values, 95.0) * 1000.0,
        "p99_ms": _percentile(values, 99.0) * 1000.0,
        "capacity_eps_from_mean": (1.0 / mean) if mean > 0 else math.inf,
    }


def _simulate_partitioned_queue(
    *,
    records: tuple[TraceRecord, ...],
    service_s: list[float],
    shard_ids: list[int],
    shard_count: int,
    eps: float,
) -> dict:
    arrivals = _fixed_arrivals(len(records), eps)
    waits_all: list[float] = []
    completion_by_sequence = [0.0] * len(records)
    per_shard: list[dict] = []
    total_backlog = 0
    total_high_water = 0
    max_drain_ms = 0.0

    for shard in range(shard_count):
        indices = [i for i, sid in enumerate(shard_ids) if sid == shard]
        previous_end = 0.0
        completions: list[float] = []
        active: list[float] = []
        high_water = 0
        waits: list[float] = []

        for i in indices:
            arrival = arrivals[i]
            active = [x for x in active if x > arrival]
            started = max(arrival, previous_end)
            ended = started + max(0.0, service_s[i])
            waits.append(started - arrival)
            waits_all.append(started - arrival)
            completions.append(ended)
            completion_by_sequence[i] = ended
            active.append(ended)
            high_water = max(high_water, len(active))
            previous_end = ended

        source_end = arrivals[-1] if arrivals else 0.0
        outstanding = sum(1 for x in completions if x > source_end)
        backlog = max(0, outstanding - (1 if outstanding else 0))
        drain_ms = max(0.0, previous_end - source_end) * 1000.0
        total_backlog += backlog
        total_high_water += high_water
        max_drain_ms = max(max_drain_ms, drain_ms)
        per_shard.append(
            {
                "shard": shard,
                "records": len(indices),
                "backlog_at_source_end": backlog,
                "outstanding_high_water": high_water,
                "queue_wait_p95_ms": _percentile(waits, 95.0) * 1000.0,
                "queue_wait_p99_ms": _percentile(waits, 99.0) * 1000.0,
                "drain_after_source_ms": drain_ms,
            }
        )

    return {
        "shards": shard_count,
        "backlog_at_source_end": total_backlog,
        "outstanding_high_water_sum": total_high_water,
        "queue_wait_p95_ms": _percentile(waits_all, 95.0) * 1000.0,
        "queue_wait_p99_ms": _percentile(waits_all, 99.0) * 1000.0,
        "max_drain_after_source_ms": max_drain_ms,
        "completion_times_s": completion_by_sequence,
        "per_shard": per_shard,
    }


def run_partitioned(records: tuple[TraceRecord, ...], shard_counts: tuple[int, ...]) -> dict:
    if not records:
        raise ValueError("records must be non-empty")
    if not shard_counts or any(x <= 0 for x in shard_counts):
        raise ValueError("shard_counts must be positive")

    reference = ReferenceRadarState()
    expected_by_sequence: dict[int, dict | None] = {}
    for record in records:
        trigger = reference.ingest(record)
        if record.kind == "trade":
            expected_by_sequence[record.sequence] = _trigger_snapshot(trigger)

    reports = {}
    for shard_count in shard_counts:
        states = [IndexedWindowRadarState() for _ in range(shard_count)]
        service_s: list[float] = []
        shard_ids: list[int] = []
        mismatches: list[dict] = []
        trade_matches = 0
        trade_decisions = 0

        for record in records:
            shard = _shard_for_token(_token_mint(record), shard_count)
            shard_ids.append(shard)
            started = time.perf_counter_ns()
            trigger = states[shard].ingest(record)
            service_s.append((time.perf_counter_ns() - started) / 1_000_000_000.0)

            if record.kind == "trade":
                trade_decisions += 1
                expected = expected_by_sequence[record.sequence]
                actual = _trigger_snapshot(trigger)
                if actual == expected:
                    trade_matches += 1
                else:
                    mismatches.append(
                        {
                            "sequence": record.sequence,
                            "shard": shard,
                            "expected": expected,
                            "actual": actual,
                        }
                    )

        service = _service_report(service_s)
        scenarios = {}
        for name, eps in (
            ("representative_5k", REPRESENTATIVE_EPS),
            ("headroom_7_5k", HEADROOM_EPS),
        ):
            queue = _simulate_partitioned_queue(
                records=records,
                service_s=service_s,
                shard_ids=shard_ids,
                shard_count=shard_count,
                eps=eps,
            )
            research = _simulate_bounded_research_handoff(
                queue["completion_times_s"],
                buffer=RESEARCH_BUFFER,
            )
            scenarios[name] = {
                "eps": eps,
                "queue": {k: v for k, v in queue.items() if k != "completion_times_s"},
                "research_handoff": research,
            }

        parity_pct = 100.0 if not trade_decisions else 100.0 * trade_matches / trade_decisions
        checks = {
            "parity_100": parity_pct == 100.0 and not mismatches,
            "5k_no_backlog": scenarios["representative_5k"]["queue"]["backlog_at_source_end"] == 0,
            "7_5k_no_backlog": scenarios["headroom_7_5k"]["queue"]["backlog_at_source_end"] == 0,
            "research_5k_zero_drop": scenarios["representative_5k"]["research_handoff"]["dropped"] == 0,
            "research_7_5k_zero_drop": scenarios["headroom_7_5k"]["research_handoff"]["dropped"] == 0,
        }
        reports[str(shard_count)] = {
            "shards": shard_count,
            "detector_parity_pct": parity_pct,
            "mismatches": mismatches[:20],
            "service": service,
            "scenarios": scenarios,
            "checks": checks,
            "pass": all(checks.values()),
            "late_chain_time_inserts": sum(state.late_chain_time_inserts for state in states),
        }

    passing = [int(k) for k, v in reports.items() if v["pass"]]
    minimum_passing = min(passing) if passing else None
    classification = (
        "PASS_PARTITIONED_INDEXED_SIGNAL_PLANE_V0"
        if minimum_passing is not None
        else "PARTITIONED_INDEXED_CAPACITY_INSUFFICIENT"
    )
    return {
        "type": "partitioned_indexed_signal_plane_report",
        "version": VERSION,
        "record_count": len(records),
        "trade_decision_points": len(expected_by_sequence),
        "shard_counts": list(shard_counts),
        "results": reports,
        "minimum_passing_shards": minimum_passing,
        "classification": classification,
        "interpretation": (
            "Use the minimum passing deterministic per-asset shard count as the next shadow-runtime candidate."
            if minimum_passing is not None
            else "Per-asset Python partitioning did not meet the frozen 5k/7.5k gates; benchmark Rust next."
        ),
    }


def _parse_shards(value: str) -> tuple[int, ...]:
    result = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    if not result or any(item <= 0 for item in result):
        raise argparse.ArgumentTypeError("shards must be positive comma-separated integers")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Partitioned indexed Market Signal Plane benchmark v0")
    parser.add_argument("--events", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=68)
    parser.add_argument("--shards", type=_parse_shards, default=DEFAULT_SHARDS)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("artifacts/integrated_market_signal_plane_v1/partitioned-report.json"),
    )
    args = parser.parse_args()
    if args.events <= 0:
        raise SystemExit("--events must be positive")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        trace = Path(tmp) / "trace.jsonl"
        generate_synthetic_trace(out=trace, events=args.events, seed=args.seed)
        _, records = load_trace(trace)
        report = run_partitioned(records, args.shards)

    args.out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["classification"] != "PASS_PARTITIONED_INDEXED_SIGNAL_PLANE_V0":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
