from __future__ import annotations

import argparse
import base64
import json
import math
from pathlib import Path
import struct
import subprocess
import threading
import time
from typing import Any

PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
BUY_EVENT_DISCRIMINATOR = bytes([103, 244, 82, 31, 44, 245, 119, 119])
VERSION = "carbon_stream_bridge_v0"
DEFAULT_EVENTS = 5000
DEFAULT_TARGET_RATE = 5000.0
P95_GATE_MS = 25.0
P99_GATE_MS = 75.0
MIN_ACHIEVED_RATE_RATIO = 0.90


def _u64(value: int) -> bytes:
    return struct.pack("<Q", value)


def _i64(value: int) -> bytes:
    return struct.pack("<q", value)


def _borsh_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def synthetic_pumpswap_buy_payload(sequence: int) -> bytes:
    """Create a valid deterministic Carbon PumpSwap BuyEvent payload."""
    payload = bytearray(BUY_EVENT_DISCRIMINATOR)
    payload += _i64(1_700_000_000 + sequence)
    for offset in range(13):
        payload += _u64(sequence + offset + 1)
    for seed in range(1, 8):
        payload += bytes([(sequence + seed) % 251 + 1]) * 32
    payload += _u64(21)
    payload += _u64(22)
    payload += b"\x01"
    payload += _u64(23)
    payload += _u64(24)
    payload += _u64(25)
    payload += _i64(1_700_000_100 + sequence)
    payload += _u64(26)
    payload += _borsh_string("buy_exact_in")
    payload += _u64(27)
    payload += _u64(28)
    return bytes(payload)


def input_row(sequence: int) -> dict[str, Any]:
    return {
        "type": "carbon_decoder_input",
        "event_key": f"stream-{sequence}:0:pumpswap_buy",
        "signature": f"stream-{sequence}",
        "slot": 1_000_000 + sequence,
        "log_index": 0,
        "program_id": PUMPSWAP_PROGRAM_ID,
        "event_type": "pumpswap_buy",
        "payload_base64": base64.b64encode(
            synthetic_pumpswap_buy_payload(sequence)
        ).decode("ascii"),
    }


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
    latency = report["round_trip_latency_ms"]
    achieved = float(report["achieved_ingress_events_per_second"])
    target = float(report["target_ingress_events_per_second"])
    if (
        report["ready_received"] is True
        and report["input_events"] == report["decoded_events"]
        and report["decode_failures"] == 0
        and report["input_errors"] == 0
        and report["order_violations"] == 0
        and report["footer_accounting_valid"] is True
        and achieved >= target * MIN_ACHIEVED_RATE_RATIO
        and latency["p95"] is not None
        and latency["p99"] is not None
        and latency["p95"] <= P95_GATE_MS
        and latency["p99"] <= P99_GATE_MS
    ):
        return "PASS_CARBON_STREAM_BRIDGE_V0"
    return "REJECT_OR_INVESTIGATE_CARBON_STREAM_BRIDGE_V0"


def run_benchmark(*, binary: Path, events: int, target_rate: float) -> dict[str, Any]:
    if events <= 0:
        raise ValueError("events must be positive")
    if target_rate <= 0:
        raise ValueError("target_rate must be positive")

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

    send_times_ns: dict[str, int] = {}
    receive_times_ns: dict[str, int] = {}
    received_keys: list[str] = []
    footer: dict[str, Any] = {}
    output_errors: list[dict[str, Any]] = []
    state_lock = threading.Lock()
    received_count = 0

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
            if row_type == "carbon_canonical_event":
                key = row.get("event_key")
                if isinstance(key, str):
                    receive_times_ns[key] = observed_ns
                    received_keys.append(key)
                if row.get("status") != "decoded":
                    output_errors.append(row)
                with state_lock:
                    received_count += 1
            elif row_type == "carbon_stream_decoder_input_error":
                output_errors.append(row)
            elif row_type == "carbon_stream_decoder_footer":
                footer = row

    reader_thread = threading.Thread(target=reader, name="carbon-stream-reader", daemon=True)
    reader_thread.start()

    interval_ns = int(1_000_000_000 / target_rate)
    source_started_ns = time.perf_counter_ns()
    max_inflight = 0

    for sequence in range(events):
        target_ns = source_started_ns + sequence * interval_ns
        while True:
            now_ns = time.perf_counter_ns()
            remaining_ns = target_ns - now_ns
            if remaining_ns <= 0:
                break
            if remaining_ns > 300_000:
                time.sleep((remaining_ns - 150_000) / 1_000_000_000)

        row = input_row(sequence)
        key = str(row["event_key"])
        send_times_ns[key] = time.perf_counter_ns()
        process.stdin.write(json.dumps(row, separators=(",", ":")) + "\n")
        process.stdin.flush()
        with state_lock:
            max_inflight = max(max_inflight, sequence + 1 - received_count)

    source_finished_ns = time.perf_counter_ns()
    process.stdin.close()
    reader_thread.join(timeout=30.0)
    return_code = process.wait(timeout=10.0)
    stderr = process.stderr.read()

    expected_keys = [f"stream-{sequence}:0:pumpswap_buy" for sequence in range(events)]
    order_violations = sum(
        1 for expected, observed in zip(expected_keys, received_keys) if expected != observed
    ) + abs(len(expected_keys) - len(received_keys))

    latency_ms = [
        (receive_times_ns[key] - send_ns) / 1_000_000.0
        for key, send_ns in send_times_ns.items()
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
        "input_events": events,
        "decoded_events": len(received_keys),
        "decode_failures": sum(
            1
            for item in output_errors
            if item.get("type") == "carbon_canonical_event"
        ),
        "input_errors": sum(
            1
            for item in output_errors
            if item.get("type") == "carbon_stream_decoder_input_error"
        ),
        "output_error_examples": output_errors[:10],
        "order_violations": order_violations,
        "max_inflight_events": max_inflight,
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
            footer.get("input_lines") == events
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
            "This measures persistent local NDJSON IPC plus the already-pinned Carbon event decoder, not provider/network latency.",
            "The frozen file decoder remains unchanged; the stream sidecar includes it as the decoder oracle to avoid semantic duplication.",
            "The benchmark uses deterministic valid synthetic PumpSwap BuyEvent payloads and checks exact output order/accounting.",
            "A CI PASS supports the local bridge architecture only; live Helius WSS and pool lookup remain separate gates.",
        ],
    }
    report["classification"] = classify(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark persistent Python-to-Carbon NDJSON bridge")
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--events", type=int, default=DEFAULT_EVENTS)
    parser.add_argument("--target-rate", type=float, default=DEFAULT_TARGET_RATE)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    report = run_benchmark(binary=args.binary, events=args.events, target_rate=args.target_rate)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["classification"] == "PASS_CARBON_STREAM_BRIDGE_V0" else 1


if __name__ == "__main__":
    raise SystemExit(main())
