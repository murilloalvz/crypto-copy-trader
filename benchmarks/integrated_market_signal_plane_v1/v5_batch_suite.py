from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any

from benchmarks.commodity_signal_plane_v0.benchmark import (
    TraceRecord,
    generate_synthetic_trace,
    load_trace,
)
from benchmarks.integrated_market_signal_plane_v1.indexed_kernel import (
    IndexedWindowRadarState,
)
from benchmarks.integrated_market_signal_plane_v1.rust_suite import (
    _json_equivalent,
)
from benchmarks.integrated_market_signal_plane_v1.suite import (
    HEADROOM_EPS,
    REPRESENTATIVE_EPS,
    _percentile,
    _trigger_snapshot,
)


VERSION = "rust_signal_batch_offline_capacity_v0"
BATCH_SIZE = 32
PASS_CLASSIFICATION = "PASS_RUST_SIGNAL_BATCH_OFFLINE_CAPACITY_V0"
SEMANTIC_FAIL = "FAIL_RUST_SIGNAL_BATCH_OFFLINE_SEMANTICS"
CAPACITY_FAIL = "FAIL_RUST_SIGNAL_BATCH_OFFLINE_CAPACITY"


def _signal_record(record: TraceRecord, *, wall_base_ns: int) -> dict[str, Any]:
    observation = record.trade if record.kind == "trade" else record.lifecycle
    if observation is None:
        raise ValueError("trace record missing observation")
    if record.kind == "trade":
        payload = {
            "token_mint": observation.token_mint,
            "side": observation.side,
            "chain_time": observation.chain_time,
            "observed_at": observation.observed_at,
            "wallet_address": observation.wallet_address,
            "notional_usd": observation.notional_usd,
            "price_usd": observation.price_usd,
            "venue": observation.venue,
            "transaction_key": observation.transaction_key,
        }
    else:
        payload = {
            "token_mint": observation.token_mint,
            "market_started_at": observation.market_started_at,
            "observed_at": observation.observed_at,
            "venue": observation.venue,
        }
    source_wall_ns = wall_base_ns + max(0, int(record.arrival_offset_ns))
    return {
        "sequence": int(record.sequence),
        "kind": record.kind,
        "observation": payload,
        "source_received_wall_ns": source_wall_ns,
        "canonical_ready_wall_ns": source_wall_ns + 1_000,
    }


class _RustBatchProcess:
    def __init__(self, *, cargo: str, manifest: Path) -> None:
        self.command = [
            cargo,
            "run",
            "--release",
            "--quiet",
            "--manifest-path",
            str(manifest),
            "--bin",
            "stream",
        ]
        self.process: subprocess.Popen[str] | None = None

    def start(self) -> dict[str, Any]:
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        assert self.process.stdout is not None
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(
                "Rust batch stream exited before ready: "
                + self._stderr_tail()
            )
        row = json.loads(line)
        if row.get("type") != "rust_signal_stream_ready":
            raise RuntimeError(f"unexpected Rust ready row: {row!r}")
        return row

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if (
            self.process is None
            or self.process.stdin is None
            or self.process.stdout is None
        ):
            raise RuntimeError("Rust batch stream not started")
        self.process.stdin.write(
            json.dumps(payload, separators=(",", ":")) + "\n"
        )
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(
                "Rust batch stream exited awaiting response: "
                + self._stderr_tail()
            )
        return json.loads(line)

    def _stderr_tail(self) -> str:
        if self.process is None or self.process.stderr is None:
            return ""
        if self.process.poll() is None:
            return "<process still running>"
        return self.process.stderr.read()[-4000:]

    def close(self) -> None:
        if self.process is None:
            return
        if self.process.stdin is not None and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)


def _latency_ms(values_ns: list[int]) -> dict[str, float | int]:
    values_ms = [max(0, int(value)) / 1_000_000.0 for value in values_ns]
    return {
        "count": len(values_ms),
        "p50_ms": _percentile(values_ms, 50.0),
        "p95_ms": _percentile(values_ms, 95.0),
        "p99_ms": _percentile(values_ms, 99.0),
        "max_ms": max(values_ms) if values_ms else 0.0,
    }


def run_v5_batch_capacity(
    *,
    events: int = 10_000,
    seed: int = 68,
    cargo: str = "cargo",
) -> dict[str, Any]:
    if events <= 0:
        raise ValueError("events must be positive")

    manifest = (
        Path(__file__).resolve().parent
        / "rust_runner"
        / "Cargo.toml"
    )

    with tempfile.TemporaryDirectory(
        prefix="rust-signal-batch-capacity-v0-"
    ) as directory:
        trace_path = Path(directory) / "trace.jsonl"
        generate_synthetic_trace(out=trace_path, events=events, seed=seed)
        _, loaded = load_trace(trace_path)
        records = tuple(loaded)

        rust = _RustBatchProcess(cargo=cargo, manifest=manifest)
        ready = rust.start()
        rust_results: dict[int, dict[str, Any]] = {}
        batch_roundtrip_ns: list[int] = []
        batch_internal_ns: list[int] = []
        batch_sizes: list[int] = []
        wall_base_ns = 1_800_000_000_000_000_000

        started_ns = time.perf_counter_ns()
        active_batch_wall_ns = 0
        process_teardown_ns = 0
        try:
            batch_id = 0
            for offset in range(0, len(records), BATCH_SIZE):
                chunk = records[offset : offset + BATCH_SIZE]
                batch_id += 1
                payload = {
                    "type": "signal_batch",
                    "batch_id": batch_id,
                    "records": [
                        _signal_record(
                            record,
                            wall_base_ns=wall_base_ns,
                        )
                        for record in chunk
                    ],
                }
                request_started = time.perf_counter_ns()
                response = rust.request(payload)
                batch_roundtrip_ns.append(
                    time.perf_counter_ns() - request_started
                )
                if response.get("type") != "signal_batch_result":
                    raise RuntimeError(
                        f"unexpected Rust batch response: {response!r}"
                    )
                if int(response.get("batch_id", -1)) != batch_id:
                    raise RuntimeError("Rust batch_id mismatch")
                rows = response.get("results")
                if not isinstance(rows, list) or len(rows) != len(chunk):
                    raise RuntimeError("Rust batch result count mismatch")
                batch_sizes.append(len(chunk))
                batch_internal_ns.append(
                    int(response.get("batch_service_ns", 0))
                )
                for expected_record, row in zip(chunk, rows):
                    if int(row.get("sequence", -1)) != expected_record.sequence:
                        raise RuntimeError("Rust batch sequence order changed")
                    rust_results[expected_record.sequence] = row
            active_batch_wall_ns = time.perf_counter_ns() - started_ns
        finally:
            teardown_started_ns = time.perf_counter_ns()
            rust.close()
            process_teardown_ns = time.perf_counter_ns() - teardown_started_ns

    python = IndexedWindowRadarState()
    trade_points = 0
    exact_matches = 0
    mismatches: list[dict[str, Any]] = []
    for record in records:
        py_trigger = python.ingest(record)
        if record.kind != "trade":
            continue
        trade_points += 1
        rust_row = rust_results.get(record.sequence)
        actual = None if rust_row is None else rust_row.get("trigger")
        expected = _trigger_snapshot(py_trigger)
        if _json_equivalent(expected, actual):
            exact_matches += 1
        elif len(mismatches) < 20:
            mismatches.append(
                {
                    "sequence": record.sequence,
                    "python": expected,
                    "rust": actual,
                }
            )

    parity_pct = (
        100.0
        if trade_points == 0
        else 100.0 * exact_matches / trade_points
    )
    active_batch_wall_seconds = active_batch_wall_ns / 1_000_000_000.0
    throughput_eps = (
        len(records) / active_batch_wall_seconds
        if active_batch_wall_seconds > 0
        else math.inf
    )

    checks = {
        "stream_transport_v1_signal_batch": (
            ready.get("transport") == "ndjson_stdio_v1_signal_batch"
        ),
        "record_accounting_exact": len(rust_results) == len(records),
        "sequence_order_exact": (
            sorted(rust_results) == [record.sequence for record in records]
        ),
        "trade_decisions_observed": trade_points > 0,
        "trigger_parity_100": (
            parity_pct == 100.0
            and exact_matches == trade_points
            and not mismatches
        ),
        "representative_5k_capacity": throughput_eps >= REPRESENTATIVE_EPS,
        "headroom_7_5k_capacity": throughput_eps >= HEADROOM_EPS,
    }

    if not checks["trigger_parity_100"] or not checks["record_accounting_exact"]:
        classification = SEMANTIC_FAIL
    elif all(checks.values()):
        classification = PASS_CLASSIFICATION
    else:
        classification = CAPACITY_FAIL

    return {
        "type": "rust_signal_batch_offline_capacity_report",
        "version": VERSION,
        "classification": classification,
        "authorization": "systems_only_no_live_no_v68",
        "events_requested": events,
        "seed": seed,
        "record_count": len(records),
        "trade_decision_points": trade_points,
        "batch_size_frozen": BATCH_SIZE,
        "batch_count": len(batch_sizes),
        "batch_sizes": {
            "min": min(batch_sizes) if batch_sizes else 0,
            "max": max(batch_sizes) if batch_sizes else 0,
            "mean": (
                sum(batch_sizes) / len(batch_sizes)
                if batch_sizes else 0.0
            ),
        },
        "throughput": {
            "wall_ms": active_batch_wall_ns / 1_000_000.0,
            "active_batch_wall_ms": active_batch_wall_ns / 1_000_000.0,
            "process_teardown_ms": process_teardown_ns / 1_000_000.0,
            "measurement_contract": (
                "capacity uses active ordered batch construction + stdin/stdout IPC + "
                "Rust processing through the final batch response; process teardown is "
                "reported separately and excluded from capacity"
            ),
            "effective_records_per_second": throughput_eps,
            "representative_target_eps": REPRESENTATIVE_EPS,
            "headroom_target_eps": HEADROOM_EPS,
        },
        "rust_batch_roundtrip": _latency_ms(batch_roundtrip_ns),
        "rust_batch_internal_service": _latency_ms(batch_internal_ns),
        "trigger_parity": {
            "exact_matches": exact_matches,
            "mismatches": trade_points - exact_matches,
            "parity_pct": parity_pct,
            "first_mismatches": mismatches,
        },
        "late_chain_time_inserts": {
            "python": python.late_chain_time_inserts,
            "rust": (
                max(
                    (
                        int(row.get("late_chain_time_inserts", 0))
                        for row in rust_results.values()
                    ),
                    default=0,
                )
            ),
        },
        "checks": checks,
        "scientific_thresholds_modified": False,
        "economic_hypothesis_modified": False,
        "interpretation": (
            "PASS proves the ordered Rust V5 signal-batch process preserves "
            "frozen Radar trigger semantics and clears the existing 5k/7.5k "
            "offline capacity targets including batched stdin/stdout IPC. "
            "It does not prove live network stability or economic edge."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Offline capacity/parity test for V5 ordered Rust signal batches."
        )
    )
    parser.add_argument("--events", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=68)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "artifacts/integrated_market_signal_plane_v1/"
            "v5-signal-batch-offline-capacity.json"
        ),
    )
    args = parser.parse_args()

    report = run_v5_batch_capacity(
        events=args.events,
        seed=args.seed,
        cargo=args.cargo,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["classification"] == PASS_CLASSIFICATION else 1


if __name__ == "__main__":
    raise SystemExit(main())
