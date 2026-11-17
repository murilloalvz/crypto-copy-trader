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

from benchmarks.carbon_kernel_ingress_v0.replay import carbon_input
from benchmarks.carbon_stream_bridge_v1.benchmark import _pace_source_until
from src.carbon_market_trade_adapter import adapt_carbon_matched_unit_to_market_trade_v0
from src.carbon_matched_unit_adapter import ADAPTED, adapt_carbon_pump_trade_v0
from src.market_signal_kernel import IndexedMarketSignalKernel

VERSION = "carbon_kernel_ingress_v1"
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


def classify(report: dict[str, Any]) -> str:
    latency = report["source_to_kernel_latency_ms"]
    achieved = float(report["achieved_ingress_events_per_second"])
    target = float(report["target_ingress_events_per_second"])
    if (
        report["ready_received"] is True
        and report["transport"] == "ndjson_stdio_microbatch_v1"
        and report["input_events"] == report["decoded_events"]
        and report["input_events"] == report["matched_unit_adapted_events"]
        and report["input_events"] == report["market_trade_adapted_events"]
        and report["input_events"] == report["kernel_trade_events_ingested"]
        and report["decode_failures"] == 0
        and report["input_errors"] == 0
        and report["semantic_errors"] == 0
        and report["order_violations"] == 0
        and report["footer_accounting_valid"] is True
        and report["observed_max_batch_size"] <= report["configured_batch_size"]
        and achieved >= target * MIN_ACHIEVED_RATE_RATIO
        and latency["p95"] is not None
        and latency["p99"] is not None
        and latency["p95"] <= P95_GATE_MS
        and latency["p99"] <= P99_GATE_MS
    ):
        return "PASS_CARBON_KERNEL_INGRESS_V1"
    return "REJECT_OR_INVESTIGATE_CARBON_KERNEL_INGRESS_V1"


def run_benchmark(
    *,
    binary: Path,
    events: int = DEFAULT_EVENTS,
    target_rate: float = DEFAULT_TARGET_RATE,
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

    source_available_ns: dict[str, int] = {}
    local_observed_at: dict[str, int] = {}
    kernel_completed_ns: dict[str, int] = {}
    received_keys: list[str] = []
    footer: dict[str, Any] = {}
    output_errors: list[dict[str, Any]] = []
    semantic_error_examples: list[dict[str, Any]] = []
    writer_errors: list[str] = []

    decoded_events = 0
    matched_adapted = 0
    market_trade_adapted = 0
    trigger_count = 0
    received_count = 0
    state_lock = threading.Lock()
    kernel = IndexedMarketSignalKernel()

    produced_queue: queue.Queue[Any] = queue.Queue()
    batch_sizes: list[int] = []
    batch_wait_ms: list[float] = []

    def semantic_error(event_key: str | None, error: str, **extra: Any) -> None:
        if len(semantic_error_examples) < 10:
            item: dict[str, Any] = {"event_key": event_key, "error": error}
            item.update(extra)
            semantic_error_examples.append(item)

    def reader() -> None:
        nonlocal footer, received_count, decoded_events, matched_adapted
        nonlocal market_trade_adapted, trigger_count
        for raw_line in process.stdout:
            if not raw_line.strip():
                continue
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
                for canonical in items:
                    if not isinstance(canonical, dict):
                        output_errors.append({"error": "invalid_batch_item"})
                        continue
                    key = canonical.get("event_key")
                    if not isinstance(key, str):
                        semantic_error(None, "missing_event_key")
                        continue
                    received_keys.append(key)
                    if canonical.get("type") != "carbon_canonical_event" or canonical.get("status") != "decoded":
                        output_errors.append(canonical)
                        with state_lock:
                            received_count += 1
                        continue
                    decoded_events += 1

                    observed_at = local_observed_at.get(key)
                    if observed_at is None:
                        semantic_error(key, "missing_local_observed_at")
                        with state_lock:
                            received_count += 1
                        continue

                    matched = adapt_carbon_pump_trade_v0(canonical, observed_at=observed_at)
                    if matched.status != ADAPTED or matched.observation is None:
                        semantic_error(
                            key,
                            "matched_unit_not_adapted",
                            status=matched.status,
                            flags=list(matched.data_quality_flags),
                        )
                        with state_lock:
                            received_count += 1
                        continue
                    matched_adapted += 1

                    market_trade = adapt_carbon_matched_unit_to_market_trade_v0(canonical, matched)
                    if market_trade.status != ADAPTED or market_trade.observation is None:
                        semantic_error(
                            key,
                            "market_trade_not_adapted",
                            status=market_trade.status,
                            flags=list(market_trade.data_quality_flags),
                        )
                        with state_lock:
                            received_count += 1
                        continue
                    market_trade_adapted += 1
                    observation = market_trade.observation

                    if observation.observed_at != observed_at:
                        semantic_error(key, "local_observed_at_not_preserved")
                        with state_lock:
                            received_count += 1
                        continue
                    if observation.notional_usd is not None or observation.price_usd is not None:
                        semantic_error(key, "usd_or_price_was_manufactured")
                        with state_lock:
                            received_count += 1
                        continue

                    trigger = kernel.ingest_trade(observation)
                    if trigger is not None:
                        trigger_count += 1
                    kernel_completed_ns[key] = time.perf_counter_ns()
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

    reader_thread = threading.Thread(target=reader, name="carbon-kernel-v1-reader", daemon=True)
    writer_thread = threading.Thread(target=batch_writer, name="carbon-kernel-v1-writer", daemon=True)
    reader_thread.start()
    writer_thread.start()

    interval_ns = int(1_000_000_000 / target_rate)
    source_started_ns = time.perf_counter_ns()
    max_inflight = 0

    for sequence in range(events):
        target_ns = source_started_ns + sequence * interval_ns
        _pace_source_until(target_ns)
        row = carbon_input(sequence)
        key = str(row["event_key"])
        available_ns = time.perf_counter_ns()
        source_available_ns[key] = available_ns
        local_observed_at[key] = 2_000_000_000 + sequence
        produced_queue.put((row, available_ns))
        with state_lock:
            max_inflight = max(max_inflight, sequence + 1 - received_count)

    source_finished_ns = time.perf_counter_ns()
    produced_queue.put(_SENTINEL)
    writer_thread.join(timeout=30.0)
    reader_thread.join(timeout=30.0)
    return_code = process.wait(timeout=10.0)
    stderr = process.stderr.read()

    expected_keys = [f"pump-stream-{sequence}:0:pump_trade" for sequence in range(events)]
    order_violations = sum(
        1 for expected, observed in zip(expected_keys, received_keys) if expected != observed
    ) + abs(len(expected_keys) - len(received_keys))

    source_to_kernel_ms = [
        (kernel_completed_ns[key] - available_ns) / 1_000_000.0
        for key, available_ns in source_available_ns.items()
        if key in kernel_completed_ns
    ]
    source_elapsed_seconds = (source_finished_ns - source_started_ns) / 1_000_000_000.0
    achieved_rate = events / source_elapsed_seconds if source_elapsed_seconds > 0 else 0.0
    stats = kernel.stats()

    decode_failures = sum(
        1 for item in output_errors if item.get("type") == "carbon_canonical_event"
    )
    input_errors = sum(
        1 for item in output_errors if item.get("type") == "carbon_stream_decoder_batch_error"
    ) + len(writer_errors)

    report: dict[str, Any] = {
        "type": "carbon_kernel_ingress_benchmark",
        "version": VERSION,
        "binary": str(binary),
        "ready_received": ready_received,
        "carbon_decoder_version": ready.get("carbon_decoder_version"),
        "carbon_release_commit": ready.get("carbon_release_commit"),
        "transport": ready.get("transport"),
        "configured_batch_size": batch_size,
        "configured_max_batch_wait_ms": max_batch_wait_ms,
        "input_events": events,
        "decoded_events": decoded_events,
        "matched_unit_adapted_events": matched_adapted,
        "market_trade_adapted_events": market_trade_adapted,
        "kernel_trade_events_ingested": stats.trade_events_ingested,
        "kernel_retained_trade_rows": stats.retained_trade_rows,
        "kernel_tracked_assets": stats.tracked_assets,
        "kernel_triggers_emitted": trigger_count,
        "decode_failures": decode_failures,
        "input_errors": input_errors,
        "semantic_errors": len(semantic_error_examples),
        "semantic_error_examples": semantic_error_examples,
        "output_error_examples": output_errors[:10],
        "writer_error_examples": writer_errors[:10],
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
        "source_to_kernel_latency_ms": {
            "samples": len(source_to_kernel_ms),
            "min": min(source_to_kernel_ms) if source_to_kernel_ms else None,
            "p50": _percentile(source_to_kernel_ms, 50),
            "p95": _percentile(source_to_kernel_ms, 95),
            "p99": _percentile(source_to_kernel_ms, 99),
            "max": max(source_to_kernel_ms) if source_to_kernel_ms else None,
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
            "This composes the already-selected Carbon 2.0.0 decoder, Pump event-native matched-unit adapter, MarketTrade adapter, and IndexedMarketSignalKernel.",
            "Source availability is measured before the bounded microbatcher; latency ends only after kernel.ingest_trade returns.",
            "Pump is used deliberately so Pool identity lookup cannot contaminate this local integration benchmark.",
            "Local observed_at is assigned outside Carbon and USD fields must remain missing.",
            "This is local synthetic composition evidence only, not provider/network, chain-completeness, PumpSwap-context, or economic evidence.",
        ],
    }
    report["classification"] = classify(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Carbon microbatch bridge through the indexed market signal kernel")
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
    return 0 if report["classification"] == "PASS_CARBON_KERNEL_INGRESS_V1" else 1


if __name__ == "__main__":
    raise SystemExit(main())
