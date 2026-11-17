from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from benchmarks.market_first_capacity_harness_v0.run import (
    DualClockSamplerV0,
    StageRecorderV0,
    _instrument_pipeline,
    _load_identity_observations,
    _materialize_trace,
    _trace_paths,
)
from benchmarks.market_first_live_discovery_v0.pipeline import (
    LiveDiscoveryPipelineStateV0,
    process_trace_chunk_v0,
    seed_bootstrap_identities_v0,
)
from src import database
from src import market_observation_store


PROFILE_VERSION = "market_first_capacity_profile_v1_one_chunk"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _persistence_share_percent(stage_timings: dict[str, dict[str, float | int]]) -> float:
    chunk_ms = float(stage_timings.get("chunk_total", {}).get("total_ms", 0.0) or 0.0)
    persistence_ms = float(
        stage_timings.get("market_trade_persistence", {}).get("total_ms", 0.0) or 0.0
    ) + float(
        stage_timings.get("market_lifecycle_persistence", {}).get("total_ms", 0.0) or 0.0
    )
    if chunk_ms <= 0:
        return 0.0
    return min(100.0, max(0.0, 100.0 * persistence_ms / chunk_ms))


def _database_connection_profiler(recorder: StageRecorderV0):
    @contextmanager
    def profiled_connection():
        open_started = time.monotonic_ns()
        conn = sqlite3.connect(
            database.settings.database_path,
            timeout=10.0,
            isolation_level="IMMEDIATE",
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        recorder.observe("sqlite_connection_open", time.monotonic_ns() - open_started)
        try:
            yield conn
            commit_started = time.monotonic_ns()
            conn.commit()
            recorder.observe("sqlite_commit", time.monotonic_ns() - commit_started)
        finally:
            close_started = time.monotonic_ns()
            conn.close()
            recorder.observe("sqlite_close", time.monotonic_ns() - close_started)

    return profiled_connection


class CheckpointHeartbeatV1:
    def __init__(
        self,
        *,
        output: Path,
        recorder: StageRecorderV0,
        chunk_name: str,
        interval_seconds: float,
    ) -> None:
        self.output = output
        self.recorder = recorder
        self.chunk_name = chunk_name
        self.interval_seconds = max(1.0, float(interval_seconds))
        self.started_monotonic_ns = time.monotonic_ns()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _payload(self, status: str) -> dict[str, Any]:
        timings = self.recorder.summary()
        return {
            "type": "market_first_capacity_profile_checkpoint",
            "version": PROFILE_VERSION,
            "status": status,
            "chunk": self.chunk_name,
            "elapsed_seconds": (
                time.monotonic_ns() - self.started_monotonic_ns
            ) / 1_000_000_000.0,
            "stage_timings": timings,
            "persistence_share_percent": _persistence_share_percent(timings),
        }

    def start(self) -> None:
        _atomic_write_json(self.output, self._payload("RUNNING"))

        def run() -> None:
            while not self._stop.wait(self.interval_seconds):
                _atomic_write_json(self.output, self._payload("RUNNING"))

        self._thread = threading.Thread(target=run, name="market-first-profile-heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_seconds + 1.0)


def run_profile_one_chunk_v1(
    *,
    live_report_path: Path,
    raw_dir: Path,
    bootstrap_identities_path: Path,
    database_source_path: Path,
    api_key: str,
    cargo: str,
    chunk_index: int = 0,
    checkpoint_path: Path,
    heartbeat_seconds: float = 10.0,
    clock_sample_seconds: float = 5.0,
) -> dict[str, Any]:
    report = json.loads(Path(live_report_path).read_text(encoding="utf-8"))
    run = report.get("run") or {}
    identity = report.get("identity") or {}
    acquisition_run_key = str(
        run.get("acquisition_run_key") or identity.get("acquisition_run_key") or ""
    ).strip()
    if not acquisition_run_key:
        raise ValueError("live report lacks acquisition_run_key")

    traces = _trace_paths(Path(raw_dir))
    if not traces:
        raise ValueError("raw_dir contains no chunk traces")
    if chunk_index < 0 or chunk_index >= len(traces):
        raise ValueError(f"chunk_index out of range: {chunk_index}; available={len(traces)}")

    source = traces[chunk_index]
    identities = _load_identity_observations(Path(bootstrap_identities_path))
    discovery_start_wall_ns = int(report["discovery_start_wall_ns"])
    discovery_close_wall_ns = int(report["discovery_close_wall_ns"])

    recorder = StageRecorderV0()
    clock = DualClockSamplerV0(clock_sample_seconds)
    heartbeat = CheckpointHeartbeatV1(
        output=checkpoint_path,
        recorder=recorder,
        chunk_name=source.name,
        interval_seconds=heartbeat_seconds,
    )

    with tempfile.TemporaryDirectory(prefix="market-first-profile-v1-") as directory:
        root = Path(directory)
        database_copy = root / "profile.db"
        shutil.copy2(database_source_path, database_copy)
        processed_root = root / "processed"
        raw_path = _materialize_trace(source, root / "raw" / "chunk-profile.jsonl")
        state = LiveDiscoveryPipelineStateV0()
        seed_bootstrap_identities_v0(state, identities)

        print(f"[profile] chunk={source.name} index={chunk_index} status=STARTING", flush=True)
        print(f"[profile] checkpoint={checkpoint_path}", flush=True)
        clock.start()
        heartbeat.start()
        try:
            with ExitStack() as stack:
                stack.enter_context(
                    patch.object(database, "settings", SimpleNamespace(database_path=database_copy))
                )
                stack.enter_context(
                    patch.object(
                        market_observation_store,
                        "connection",
                        _database_connection_profiler(recorder),
                    )
                )
                _instrument_pipeline(stack, recorder)
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
        finally:
            heartbeat.stop()
            clock_samples = clock.stop()

    timings = recorder.summary()
    chunk_ms = float(timings.get("chunk_total", {}).get("total_ms", 0.0) or 0.0)
    trade_persistence_ms = float(
        timings.get("market_trade_persistence", {}).get("total_ms", 0.0) or 0.0
    )
    lifecycle_persistence_ms = float(
        timings.get("market_lifecycle_persistence", {}).get("total_ms", 0.0) or 0.0
    )
    commit_ms = float(timings.get("sqlite_commit", {}).get("total_ms", 0.0) or 0.0)
    persistence_ms = trade_persistence_ms + lifecycle_persistence_ms
    result = {
        "type": "market_first_capacity_profile",
        "version": PROFILE_VERSION,
        "status": "COMPLETE",
        "chunk": source.name,
        "chunk_index": chunk_index,
        "source_chunk_count": len(traces),
        "database_replay_isolated_copy": True,
        "scientific_thresholds_modified": False,
        "chunk_report_status": chunk_report.get("status"),
        "stage_timings": timings,
        "derived": {
            "chunk_total_ms": chunk_ms,
            "persistence_total_ms": persistence_ms,
            "persistence_share_percent": _persistence_share_percent(timings),
            "sqlite_commit_total_ms": commit_ms,
            "commit_share_of_chunk_percent": (
                100.0 * commit_ms / chunk_ms if chunk_ms > 0 else 0.0
            ),
            "commit_share_of_persistence_percent": (
                100.0 * commit_ms / persistence_ms if persistence_ms > 0 else 0.0
            ),
        },
        "clock": {
            "sample_count": len(clock_samples),
            "max_abs_drift_ms": max(
                (abs(int(item["drift_ns"])) / 1_000_000.0 for item in clock_samples),
                default=0.0,
            ),
        },
        "pipeline": state.summary(),
    }
    _atomic_write_json(checkpoint_path, result)
    print(
        "[profile] status=COMPLETE "
        f"chunk_seconds={chunk_ms / 1000.0:.3f} "
        f"persistence_share={result['derived']['persistence_share_percent']:.2f}% "
        f"commit_share={result['derived']['commit_share_of_chunk_percent']:.2f}%",
        flush=True,
    )
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Profile exactly one Market-First trace chunk against an isolated SQLite copy. "
            "Writes a live checkpoint so slow persistence remains observable before completion."
        )
    )
    parser.add_argument("--live-report", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-identities", type=Path, required=True)
    parser.add_argument("--database-source", type=Path, required=True)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--chunk-index", type=int, default=0)
    parser.add_argument("--heartbeat-seconds", type=float, default=10.0)
    parser.add_argument("--clock-sample-seconds", type=float, default=5.0)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = run_profile_one_chunk_v1(
        live_report_path=args.live_report,
        raw_dir=args.raw_dir,
        bootstrap_identities_path=args.bootstrap_identities,
        database_source_path=args.database_source,
        api_key=args.api_key,
        cargo=args.cargo,
        chunk_index=args.chunk_index,
        checkpoint_path=args.output,
        heartbeat_seconds=args.heartbeat_seconds,
        clock_sample_seconds=args.clock_sample_seconds,
    )
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
