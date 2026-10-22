from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import queue
import subprocess
import threading
import time
from typing import Any

from benchmarks.carbon_stream_bridge_v0.benchmark import input_row

VERSION = "carbon_stream_bridge_v1"
DEFAULT_EVENTS = 5000
DEFAULT_TARGET_RATE = 5000.0
DEFAULT_BATCH_SIZE = 16
DEFAULT_MAX_BATCH_WAIT_MS = 1.0
P95_GATE_MS = 25.0
P99_GATE_MS = 75.0
MIN_ACHIEVED_RATE_RATIO = 0.90

_SENTINEL = object()


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def _pace_source_until(target_ns: int) -> None:
    """Pace the synthetic source without starving bridge worker threads.

    The v1 transport deliberately uses a Python writer thread. A pure busy-spin
    at a 200us source interval can retain the GIL long enough to prevent that
    writer from observing queued events within the frozen 1ms batching window.
    Sleeping/yielding here changes only benchmark scheduling, not the frozen
    transport parameters or latency gates.
    """
    while True:
        remaining_ns = target_ns - time.perf_counter_ns()
        if remaining_ns <= 0:
            return
        if remaining_ns > 100_000:
            time.sleep((remaining_ns - 50_000) / 1_000_000_000.0)
        else:
            time.sleep(0)


def classify(report: dict[str, Any]) -> str:
    latency = report["round_trip_latency_ms"]
    achieved = float(report["achieved_ingress_events_per_second"])
    target = float(report["target_ingress_events_per_second"])
    if (
        report["ready_received"] is True
        and report["transport"] == "ndjson_stdio_microbatch_v1"
        and report["input_events"] == report["decoded_events"]
        and report["decode_failures"] == 0
        and report["input_errors"] == 0
        and report["order_violations"] == 0
        and report["footer_accounting_valid"] is True
        and report["observed_max_batch_size"] <= report["configured_batch_size"]
        and achieved >= target * MIN_ACHIEVED_RATE_RATIO
        and latency["p95"] is not None
        and latency["p99"] is not None
        and latency["p95"] <= P95_GATE_MS
        and latency["p99"] <= P99_GATE_MS
    ):
        return "PASS_CARBON_STREAM_BRIDGE_V1"
    return "REJECT_OR_INVESTIGATE_CARBON_STREAM_BRIDGE_V1"


def run_benchmark(
    *,
    binary: Path,
    events: int,
    target_rate: float,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_batch_wait_ms: float = DEFAULT_MAX_BATCH_WAIT_MS,
) -> dict[str, Any]:
    if events <= 0:
        raise ValueError("events must be positive")
    if target_rate <= 0:
        raise ValueError("target_rate must be positive")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if max_batch_wait_ms <= 0:
        raise ValueError("max_batch_wait_ms must be positive")

    process = subprocess.Popen(
        [str(binary)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    ready_line = process.stdout.readline()
    ready = json.loads(ready_line) if ready_line else {}
    ready_received = ready.get("type") == "carbon_stream_decoder_ready"

    availability_times_ns: dict[str, int] = {}
    receive_times_ns: dict[str, int] = {}
    received_keys: list[str] = []
    footer: dict[str, Any] = {}
    output_errors: list[dict[str, Any]] = []
    received_count = 0
    state_lock = threading.Lock()

    produced_queue: queue.Queue[Any] = queue.Queue()
    batch_sizes: list[int] = []
    batch_wait_ms: list[float] = []
    writer_errors: list[str] = []

    def reader() -> None:
        nonlocal footer, received_count
        for raw_line in process.stdout:
            if not raw_line.strip():
                continue
            observed_ns = time.perf_counter_ns()
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                output_errors.append({"error": f"invalid_output_json:{exc}"})
                continue
            row_type = row.get("type")
            if row_type == "carbon_canonical_batch":
                items = row.get("items")
                if not isinstance(items, list):
                    output_errors.append({"error": "invalid_batch_items"})
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        output_errors.append({"error": "invalid_batch_item"})
                        continue
                    key = item.get("event_key")
                    if isinstance(key, str):
                        receive_times_ns[key] = observed_ns
                        received_keys.append(key)
                    if item.get("status") != "decoded":
                        output_errors.append(item)
                    with state_lock:
                        received_count += 1
            elif row_type == "carbon_stream_decoder_batch_error":
                output_errors.append(row)
            elif row_type == "carbon_stream_decoder_footer":
                footer = row

    def batch_writer() -> None:
        batch_id = 0
        pending: list[dict[str, Any]] = []
        first_available_ns: int | None = None
        max_wait_ns = int(max_batch_wait_ms * 1_000_000)

        def flush_pending() -> None:
            nonlocal batch_id, pending, first_available_ns
            if not pending:
                return
            now_ns = time.perf_counter_ns()
            if first_available_ns is not None:
                batch_wait_ms.append((now_ns - first_available_ns) / 1_000_000.0)
            batch_sizes.append(len(pending))
            payload = {
                "type": "carbon_decoder_batch",
                "batch_id": batch_id,
                "items": pending,
            }
            try:
                process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                writer_errors.append(f"{type(exc).__name__}:{exc}")
                return
            batch_id += 1
            pending = []
            first_available_ns = None

        while True:
            if not pending:
                item = produced_queue.get()
                if item is _SENTINEL:
                    break
                row, available_ns = item
                pending.append(row)
                first_available_ns = available_ns
            else:
                assert first_available_ns is not None
                remaining_ns = max_wait_ns - (time.perf_counter_ns() - first_available_ns)
                if remaining_ns <= 0:
                    flush_pending()
                    continue
                try:
                    item = produced_queue.get(timeout=remaining_ns / 1_000_000_000.0)
                except queue.Empty:
                    flush_pending()
                    continue
                if item is _SENTINEL:
                    flush_pending()
                    break
                row, available_ns = item
                pending.append(row)

            if len(pending) >= batch_size:
                flush_pending()

        flush_pending()
        try:
            process.stdin.close()
        except OSError as exc:
            writer_errors.append(f"close:{type(exc).__name__}:{exc}")

    reader_thread = threading.Thread(target=reader, name="carbon-v1-reader", daemon=True)
    writer_thread = threading.Thread(target=batch_writer, name="carbon-v1-writer", daemon=True)
    reader_thread.start()
    writer_thread.start()

    interval_ns = int(1_000_000_000 / target_rate)
    source_started_ns = time.perf_counter_ns()
    max_inflight = 0

    for sequence in range(events):
        target_ns = source_started_ns + sequence * interval_ns
        _pace_source_until(target_ns)

        row = input_row(sequence)
        key = str(row["event_key"])
        available_ns = time.perf_counter_ns()
        availability_times_ns[key] = available_ns
        produced_queue.put((row, available_ns))
        with state_lock:
            max_inflight = max(max_inflight, sequence + 1 - received_count)

    source_finished_ns = time.perf_counter_ns()
    produced_queue.put(_SENTINEL)
    writer_thread.join(timeout=30.0)
    reader_thread.join(timeout=30.0)
    return_code = process.wait(timeout=10.0)
    stderr = process.stderr.read()

    expected_keys = [f"stream-{sequence}:0:pumpswap_buy" for sequence in range(events)]
    order_violations = sum(
        1 for expected, observed in zip(expected_keys, received_keys) if expected != observed
    ) + abs(len(expected_keys) - len(received_keys))

    latency_ms = [
        (receive_times_ns[key] - available_ns) / 1_000_000.0
        for key, available_ns in availability_times_ns.items()
        if key in receive_times_ns
    ]
    source_elapsed_seconds = (source_finished_ns - source_started_ns) / 1_000_000_000.0
    achieved_rate = events / source_elapsed_seconds if source_elapsed_seconds > 0 else 0.0

    report: dict[str, Any] = {
        "type": "carbon_stream_bridge_benchmark",
        "version": VERSION,
        "binary": str(binary),
        "ready_received": ready_received,
        "carbon_decoder_version": ready.get("carbon_decoder_version"),
        "carbon_release_commit": ready.get("carbon_release_commit"),
        "transport": ready.get("transport"),
        "configured_batch_size": batch_size,
        "configured_max_batch_wait_ms": max_batch_wait_ms,
        "input_events": events,
        "decoded_events": len(received_keys),
        "decode_failures": sum(
            1 for item in output_errors if item.get("type") == "carbon_canonical_event"
        ),
        "input_errors": sum(
            1
            for item in output_errors
            if item.get("type") == "carbon_stream_decoder_batch_error"
        ) + len(writer_errors),
        "writer_error_examples": writer_errors[:10],
        "output_error_examples": output_errors[:10],
        "order_violations": order_violations,
        "max_inflight_events": max_inflight,
        "batches_sent": len(batch_sizes),
        "observed_max_batch_size": max(batch_sizes) if batch_sizes else 0,
        "batch_size": {
            "p50": _percentile([float(v) for v in batch_sizes], 50),
            "p95": _percentile([float(v) for v in batch_sizes], 95),
            "max": max(batch_sizes) if batch_sizes else None,
        },
        "producer_batch_wait_ms": {
            "p50": _percentile(batch_wait_ms, 50),
            "p95": _percentile(batch_wait_ms, 95),
            "p99": _percentile(batch_wait_ms, 99),
            "max": max(batch_wait_ms) if batch_wait_ms else None,
        },
        "target_ingress_events_per_second": target_rate,
        "achieved_ingress_events_per_second": achieved_rate,
        "source_elapsed_seconds": source_elapsed_seconds,
        "round_trip_latency_ms": {
            "samples": len(latency_ms),
            "min": min(latency_ms) if latency_ms else None,
            "p50": _percentile(latency_ms, 50),
            "p95": _percentile(latency_ms, 95),
            "p99": _percentile(latency_ms, 99),
            "max": max(latency_ms) if latency_ms else None,
        },
        "footer": footer,
        "footer_accounting_valid": (
            footer.get("input_events") == events
            and footer.get("decoded_events") == events
            and footer.get("decode_failures") == 0
            and footer.get("input_errors") == 0
        ),
        "process_return_code": return_code,
        "stderr": stderr[-4000:],
        "performance_gates": {
            "min_achieved_rate_ratio": MIN_ACHIEVED_RATE_RATIO,
            "p95_max_ms": P95_GATE_MS,
            "p99_max_ms": P99_GATE_MS,
        },
        "economic_edge_evaluated": False,
        "notes": [
            "v1 keeps the frozen Carbon 2.0.0 decoder and changes only the local transport boundary.",
            "Source availability time is recorded before the bounded batcher, so round-trip latency includes batching wait.",
            "The source pacer explicitly yields the Python GIL so it does not invalidate the async batcher by starving its worker thread.",
            "Input and output are bounded NDJSON microbatches; exact event order/accounting remain mandatory.",
            "This is local IPC/decode only, not provider latency, live coverage, or economic evidence.",
        ],
    }
    report["classification"] = classify(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark bounded microbatch Python-to-Carbon bridge v1")
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--events", type=int, default=DEFAULT_EVENTS)
    parser.add_argument("--target-rate", type=float, default=DEFAULT_TARGET_RATE)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-batch-wait-ms", type=float, default=DEFAULT_MAX_BATCH_WAIT_MS)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    report = run_benchmark(
        binary=args.binary,
        events=args.events,
        target_rate=args.target_rate,
        batch_size=args.batch_size,
        max_batch_wait_ms=args.max_batch_wait_ms,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["classification"] == "PASS_CARBON_STREAM_BRIDGE_V1" else 1


if __name__ == "__main__":
    raise SystemExit(main())
