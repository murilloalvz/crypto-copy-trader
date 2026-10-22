from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import dataclass
import gzip
import json
from pathlib import Path
import shutil
import statistics
import tempfile
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable, Iterable
from unittest.mock import patch

from benchmarks.market_first_capacity_harness_v0 import CAPACITY_HARNESS_VERSION
from benchmarks.market_first_live_discovery_v0 import pipeline
from benchmarks.market_first_live_discovery_v0.pipeline import (
    LiveDiscoveryPipelineStateV0,
    process_trace_chunk_v0,
    seed_bootstrap_identities_v0,
)
from benchmarks.pumpswap_identity_bootstrap_v0.bootstrap import _load_identity_observations
from src import database
from src.market_signal_kernel import IndexedMarketSignalKernel


DEFAULT_RATE_MULTIPLIERS = (1.0, 1.25, 1.5, 2.0)


@dataclass(frozen=True)
class StageStatsV0:
    count: int
    total_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


class StageRecorderV0:
    def __init__(self) -> None:
        self._samples_ns: dict[str, list[int]] = defaultdict(list)
        self._lock = threading.Lock()

    def observe(self, stage: str, elapsed_ns: int) -> None:
        with self._lock:
            self._samples_ns[str(stage)].append(max(0, int(elapsed_ns)))

    def timed(self, stage: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args, **kwargs):
            started = time.monotonic_ns()
            try:
                return fn(*args, **kwargs)
            finally:
                self.observe(stage, time.monotonic_ns() - started)

        return wrapped

    def summary(self) -> dict[str, dict[str, float | int]]:
        result: dict[str, dict[str, float | int]] = {}
        for stage, values in sorted(self._samples_ns.items()):
            ordered = sorted(values)
            p50 = ordered[(len(ordered) - 1) // 2]
            p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
            result[stage] = {
                "count": len(ordered),
                "total_ms": sum(ordered) / 1_000_000.0,
                "p50_ms": p50 / 1_000_000.0,
                "p95_ms": p95 / 1_000_000.0,
                "max_ms": max(ordered) / 1_000_000.0,
            }
        return result


class DualClockSamplerV0:
    def __init__(self, interval_seconds: float) -> None:
        if interval_seconds <= 0:
            raise ValueError("clock sample interval must be positive")
        self.interval_seconds = float(interval_seconds)
        self.samples: list[dict[str, int]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._base_wall_ns = 0
        self._base_monotonic_ns = 0

    def _sample(self) -> None:
        wall_ns = time.time_ns()
        monotonic_ns = time.monotonic_ns()
        self.samples.append(
            {
                "wall_ns": wall_ns,
                "monotonic_ns": monotonic_ns,
                "wall_elapsed_ns": wall_ns - self._base_wall_ns,
                "monotonic_elapsed_ns": monotonic_ns - self._base_monotonic_ns,
                "drift_ns": (wall_ns - self._base_wall_ns)
                - (monotonic_ns - self._base_monotonic_ns),
            }
        )

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("clock sampler already started")
        self._base_wall_ns = time.time_ns()
        self._base_monotonic_ns = time.monotonic_ns()
        self._sample()

        def run() -> None:
            while not self._stop.wait(self.interval_seconds):
                self._sample()

        self._thread = threading.Thread(target=run, name="market-first-clock-v0", daemon=True)
        self._thread.start()

    def stop(self) -> list[dict[str, int]]:
        if self._thread is None:
            return self.samples
        self._stop.set()
        self._thread.join(timeout=max(1.0, self.interval_seconds + 1.0))
        self._sample()
        return self.samples


@dataclass(frozen=True)
class QueueSimulationV0:
    multiplier: float
    chunk_count: int
    producer_duration_seconds: float
    consumer_duration_seconds: float
    producer_chunks_per_second: float
    consumer_chunks_per_second: float
    max_queue_depth: int
    p50_wait_seconds: float
    p95_wait_seconds: float
    max_wait_seconds: float
    final_lag_seconds: float
    backlog_slope_chunks_per_second: float
    stable_service_ratio: bool


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return float(ordered[index])


def simulate_single_consumer_queue_v0(
    *,
    producer_offsets_seconds: Iterable[float],
    service_seconds: Iterable[float],
    multiplier: float,
) -> QueueSimulationV0:
    factor = float(multiplier)
    if factor <= 0:
        raise ValueError("multiplier must be positive")
    arrivals = [float(item) / factor for item in producer_offsets_seconds]
    services = [max(0.0, float(item)) for item in service_seconds]
    if not arrivals or len(arrivals) != len(services):
        raise ValueError("producer offsets and service times must be non-empty and aligned")
    if any(item < 0 for item in arrivals):
        raise ValueError("producer offsets must be non-negative")
    if any(right < left for left, right in zip(arrivals, arrivals[1:])):
        raise ValueError("producer offsets must be non-decreasing")

    finish_times: list[float] = []
    waits: list[float] = []
    queue_depths: list[int] = []
    previous_finish = 0.0
    for index, (arrival, service) in enumerate(zip(arrivals, services)):
        start = max(arrival, previous_finish)
        finish = start + service
        waits.append(start - arrival)
        finish_times.append(finish)
        previous_finish = finish
        queue_depths.append(sum(1 for prior in finish_times[:index] if prior > arrival))

    producer_duration = max(arrivals[-1] - arrivals[0], 0.0)
    consumer_duration = max(finish_times[-1] - arrivals[0], 0.0)
    producer_rate = (
        (len(arrivals) - 1) / producer_duration if len(arrivals) > 1 and producer_duration > 0 else 0.0
    )
    consumer_rate = len(services) / sum(services) if sum(services) > 0 else float("inf")
    mean_interarrival = (
        producer_duration / (len(arrivals) - 1) if len(arrivals) > 1 and producer_duration > 0 else float("inf")
    )
    mean_service = statistics.fmean(services)
    stable_ratio = mean_service <= mean_interarrival
    final_lag = max(0.0, finish_times[-1] - arrivals[-1])
    backlog_slope = (
        max(queue_depths) / producer_duration if producer_duration > 0 else float("inf")
    )
    return QueueSimulationV0(
        multiplier=factor,
        chunk_count=len(arrivals),
        producer_duration_seconds=producer_duration,
        consumer_duration_seconds=consumer_duration,
        producer_chunks_per_second=producer_rate,
        consumer_chunks_per_second=consumer_rate,
        max_queue_depth=max(queue_depths) if queue_depths else 0,
        p50_wait_seconds=_percentile(waits, 0.50),
        p95_wait_seconds=_percentile(waits, 0.95),
        max_wait_seconds=max(waits) if waits else 0.0,
        final_lag_seconds=final_lag,
        backlog_slope_chunks_per_second=backlog_slope,
        stable_service_ratio=stable_ratio,
    )


def _read_first_json_row(path: Path) -> dict[str, Any]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"trace first row is not an object: {path}")
                return row
    raise ValueError(f"trace is empty: {path}")


def _trace_paths(raw_dir: Path) -> list[Path]:
    candidates = list(raw_dir.glob("chunk-*.jsonl")) + list(raw_dir.glob("chunk-*.jsonl.gz"))
    by_stem: dict[str, Path] = {}
    for path in sorted(candidates):
        logical = path.name.removesuffix(".gz")
        by_stem.setdefault(logical, path)
    return [by_stem[key] for key in sorted(by_stem)]


def _producer_offsets_seconds(paths: list[Path]) -> list[float]:
    starts: list[int] = []
    for path in paths:
        header = _read_first_json_row(path)
        if header.get("type") != "trace_header":
            raise ValueError(f"trace does not start with trace_header: {path}")
        starts.append(int(header["started_wall_ns"]))
    base = starts[0]
    return [(item - base) / 1_000_000_000.0 for item in starts]


def _materialize_trace(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix == ".gz":
        with gzip.open(source, "rb") as src, destination.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    else:
        shutil.copy2(source, destination)
    return destination


def _instrument_pipeline(stack: ExitStack, recorder: StageRecorderV0) -> None:
    for name, stage in (
        ("reduce_shadow", "reduce"),
        ("_run_carbon_decoder", "carbon_decoder"),
        ("process_canonical_chunk_v0", "canonical_total"),
        ("fetch_pool_account_inputs", "dynamic_identity_rpc"),
        ("_run_account_decoder", "account_decoder"),
        ("record_market_trade", "market_trade_persistence"),
        ("record_market_lifecycle", "market_lifecycle_persistence"),
        ("assign_market_opportunity_trigger", "episode_persistence"),
        ("seal_market_activity_discovery_signal_boundary_v0", "signal_boundary"),
        ("process_market_activity_discovery_handoff_v0", "research_handoff"),
        ("_gzip_and_remove", "gzip"),
    ):
        original = getattr(pipeline, name)
        stack.enter_context(patch.object(pipeline, name, recorder.timed(stage, original)))

    original_ingest_trade = IndexedMarketSignalKernel.ingest_trade
    original_ingest_lifecycle = IndexedMarketSignalKernel.ingest_lifecycle

    def timed_ingest_trade(self, *args, **kwargs):
        started = time.monotonic_ns()
        try:
            return original_ingest_trade(self, *args, **kwargs)
        finally:
            recorder.observe("kernel_trade", time.monotonic_ns() - started)

    def timed_ingest_lifecycle(self, *args, **kwargs):
        started = time.monotonic_ns()
        try:
            return original_ingest_lifecycle(self, *args, **kwargs)
        finally:
            recorder.observe("kernel_lifecycle", time.monotonic_ns() - started)

    stack.enter_context(patch.object(IndexedMarketSignalKernel, "ingest_trade", timed_ingest_trade))
    stack.enter_context(
        patch.object(IndexedMarketSignalKernel, "ingest_lifecycle", timed_ingest_lifecycle)
    )


def run_capacity_replay_v0(
    *,
    live_report_path: Path,
    raw_dir: Path,
    bootstrap_identities_path: Path,
    database_source_path: Path,
    api_key: str,
    cargo: str,
    rate_multipliers: tuple[float, ...] = DEFAULT_RATE_MULTIPLIERS,
    clock_sample_seconds: float = 10.0,
    clock_drift_fail_ms: float = 2000.0,
) -> dict[str, Any]:
    report = json.loads(Path(live_report_path).read_text(encoding="utf-8"))
    run = report.get("run") or {}
    identity = report.get("identity") or {}
    acquisition_run_key = str(
        run.get("acquisition_run_key") or identity.get("acquisition_run_key") or ""
    ).strip()
    if not acquisition_run_key:
        raise ValueError("live report lacks acquisition_run_key")
    discovery_start_wall_ns = int(report["discovery_start_wall_ns"])
    discovery_close_wall_ns = int(report["discovery_close_wall_ns"])

    traces = _trace_paths(Path(raw_dir))
    if not traces:
        raise ValueError("raw_dir contains no chunk traces")
    producer_offsets = _producer_offsets_seconds(traces)
    identities = _load_identity_observations(Path(bootstrap_identities_path))

    recorder = StageRecorderV0()
    service_seconds: list[float] = []
    chunk_results: list[dict[str, Any]] = []
    clock = DualClockSamplerV0(clock_sample_seconds)

    with tempfile.TemporaryDirectory(prefix="market-first-capacity-v0-") as directory:
        root = Path(directory)
        database_copy = root / "capacity-replay.db"
        shutil.copy2(database_source_path, database_copy)
        processed_root = root / "processed"
        materialized_root = root / "raw"
        state = LiveDiscoveryPipelineStateV0()
        seed_bootstrap_identities_v0(state, identities)
        clock.start()
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(database, "settings", SimpleNamespace(database_path=database_copy))
            )
            _instrument_pipeline(stack, recorder)
            for index, source in enumerate(traces):
                raw_path = _materialize_trace(
                    source,
                    materialized_root / f"chunk-{index + 1:06d}.jsonl",
                )
                started = time.monotonic_ns()
                chunk_report = process_trace_chunk_v0(
                    state=state,
                    api_key=api_key,
                    cargo=cargo,
                    acquisition_run_key=acquisition_run_key,
                    raw_trace_path=raw_path,
                    processed_root=processed_root,
                    discovery_start_wall_ns=discovery_start_wall_ns,
                    discovery_close_wall_ns=discovery_close_wall_ns,
                    compress_evidence=True,
                )
                elapsed_ns = time.monotonic_ns() - started
                recorder.observe("chunk_total", elapsed_ns)
                service_seconds.append(elapsed_ns / 1_000_000_000.0)
                chunk_results.append(
                    {
                        "chunk": source.name,
                        "status": chunk_report.get("status"),
                        "service_seconds": service_seconds[-1],
                    }
                )
        clock_samples = clock.stop()

    simulations = [
        simulate_single_consumer_queue_v0(
            producer_offsets_seconds=producer_offsets,
            service_seconds=service_seconds,
            multiplier=multiplier,
        )
        for multiplier in rate_multipliers
    ]
    max_abs_drift_ms = max(
        (abs(int(item["drift_ns"])) / 1_000_000.0 for item in clock_samples),
        default=0.0,
    )
    clock_gate = max_abs_drift_ms <= float(clock_drift_fail_ms)
    return {
        "type": "market_first_capacity_harness",
        "version": CAPACITY_HARNESS_VERSION,
        "source_live_report": str(live_report_path),
        "source_database": str(database_source_path),
        "source_chunk_count": len(traces),
        "database_replay_isolated_copy": True,
        "scientific_thresholds_modified": False,
        "stage_timings": recorder.summary(),
        "chunks": chunk_results,
        "clock": {
            "sample_count": len(clock_samples),
            "max_abs_drift_ms": max_abs_drift_ms,
            "engineering_fail_threshold_ms": float(clock_drift_fail_ms),
            "gate_pass": clock_gate,
            "samples": clock_samples,
        },
        "capacity": [simulation.__dict__ for simulation in simulations],
        "pipeline": state.summary(),
        "classification": (
            "PASS_CAPACITY_HARNESS_V0"
            if clock_gate and not state.chunk_errors and not state.persistence_errors
            else "FAIL_CAPACITY_HARNESS_V0"
        ),
    }


def _parse_multipliers(value: str) -> tuple[float, ...]:
    result = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    if not result or any(item <= 0 for item in result):
        raise argparse.ArgumentTypeError("rate multipliers must be positive comma-separated numbers")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay Market-First chunks against an isolated database copy, measure stage service "
            "times and dual-clock drift, then simulate FCFS capacity at 1x/1.25x/1.5x/2x."
        )
    )
    parser.add_argument("--live-report", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-identities", type=Path, required=True)
    parser.add_argument("--database-source", type=Path, required=True)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--rate-multipliers", type=_parse_multipliers, default=DEFAULT_RATE_MULTIPLIERS)
    parser.add_argument("--clock-sample-seconds", type=float, default=10.0)
    parser.add_argument("--clock-drift-fail-ms", type=float, default=2000.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = run_capacity_replay_v0(
        live_report_path=args.live_report,
        raw_dir=args.raw_dir,
        bootstrap_identities_path=args.bootstrap_identities,
        database_source_path=args.database_source,
        api_key=args.api_key,
        cargo=args.cargo,
        rate_multipliers=args.rate_multipliers,
        clock_sample_seconds=args.clock_sample_seconds,
        clock_drift_fail_ms=args.clock_drift_fail_ms,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False))
    return 0 if result["classification"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
