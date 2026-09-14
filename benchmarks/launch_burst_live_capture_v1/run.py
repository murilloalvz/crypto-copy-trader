from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import time
import uuid
from typing import Any

from benchmarks.helius_standard_wss_shadow_v0.collect import (
    Counters,
    _run_session,
    helius_wss_url,
    redact_secret,
)
from benchmarks.market_first_live_discovery_v0.pipeline import (
    LiveDiscoveryPipelineStateV0,
    process_trace_chunk_v0,
    seed_bootstrap_identities_v0,
)
from benchmarks.market_first_live_discovery_v0.rotating_trace import (
    DEFAULT_CHUNK_MAX_BYTES,
    RotatingTraceHandleV0,
)
from benchmarks.market_first_live_discovery_v0.contracts import (
    load_bootstrap_evidence_v0,
    validate_bootstrap_before_discovery_start_v0,
)


CAPTURE_VERSION = "launch_burst_live_capture_v1_rotating"
DEFAULT_DURATION_SECONDS = 900
DEFAULT_ARTIFACTS_ROOT = Path("artifacts") / CAPTURE_VERSION
ACTIVE_TIMEOUT_SECONDS = 30.0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _capture_id() -> str:
    return f"{CAPTURE_VERSION}-{int(time.time())}-{uuid.uuid4().hex[:10]}"


async def _collect_rotating(
    *,
    api_key: str,
    raw_dir: Path,
    finalized_queue: asyncio.Queue[Path | None],
    active_event: asyncio.Event,
    duration_seconds: int,
    chunk_max_bytes: int,
) -> dict[str, Any]:
    counters = Counters()
    started_wall_ns = time.time_ns()
    started_monotonic = time.monotonic()
    global_deadline = started_monotonic + float(duration_seconds)
    handle = RotatingTraceHandleV0(
        raw_dir=raw_dir,
        finalized_queue=finalized_queue,
        active_event=active_event,
        counters=counters,
        duration_seconds=float(duration_seconds),
        max_bytes=int(chunk_max_bytes),
    )
    websocket_url = helius_wss_url(api_key)
    stop_reason = "duration_elapsed"
    session_number = 0

    try:
        while time.monotonic() < global_deadline:
            session_number += 1
            try:
                stop_reason = await _run_session(
                    websocket_url=websocket_url,
                    handle=handle,
                    counters=counters,
                    session_number=session_number,
                    global_deadline=global_deadline,
                    max_log_notifications=0,
                    ack_timeout_seconds=20.0,
                )
                if stop_reason == "duration_elapsed":
                    break
            except (OSError, TimeoutError, RuntimeError, asyncio.TimeoutError):
                counters.transport_errors += 1
                if counters.reconnects >= 5 or time.monotonic() >= global_deadline:
                    stop_reason = "transport_error_reconnect_budget_exhausted"
                    break
                counters.reconnects += 1
                await asyncio.sleep(min(2.0, max(0.0, global_deadline - time.monotonic())))
    finally:
        handle.close(stop_reason=stop_reason)

    return {
        "type": "launch_burst_rotating_acquisition_v1",
        "version": CAPTURE_VERSION,
        "started_wall_ns": started_wall_ns,
        "ended_wall_ns": time.time_ns(),
        "elapsed_seconds": max(0.0, time.monotonic() - started_monotonic),
        "configured_duration_seconds": int(duration_seconds),
        "stop_reason": stop_reason,
        "chunk_count": handle.chunk_count,
        "chunk_max_bytes": int(chunk_max_bytes),
        "counters": asdict(counters),
        "log_notifications": counters.log_notifications,
        "valid_operational_shadow": counters.sessions_activated > 0,
        "chain_complete_coverage_claimed": False,
    }


async def _consume_chunks(
    *,
    queue: asyncio.Queue[Path | None],
    state: LiveDiscoveryPipelineStateV0,
    api_key: str,
    cargo: str,
    acquisition_run_key: str,
    processed_root: Path,
    discovery_start_wall_ns: int,
    discovery_close_wall_ns: int,
) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    while True:
        raw_path = await queue.get()
        try:
            if raw_path is None:
                break
            report = await asyncio.to_thread(
                process_trace_chunk_v0,
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
            reports.append(report)
        finally:
            queue.task_done()
    return reports


def _classification_gates(
    *,
    acquisition: dict[str, Any],
    state: LiveDiscoveryPipelineStateV0,
    chunk_reports: list[dict[str, Any]],
) -> dict[str, bool]:
    counters = acquisition.get("counters") or {}
    chunk_count = int(acquisition.get("chunk_count") or 0)
    return {
        "operational_shadow_active": acquisition.get("valid_operational_shadow") is True,
        "duration_elapsed": acquisition.get("stop_reason") == "duration_elapsed",
        "no_transport_errors": int(counters.get("transport_errors") or 0) == 0,
        "no_reconnects": int(counters.get("reconnects") or 0) == 0,
        "no_rpc_errors": int(counters.get("rpc_errors") or 0) == 0,
        "no_write_errors": int(counters.get("write_errors") or 0) == 0,
        "chunks_bounded": int(acquisition.get("chunk_max_bytes") or 0) > 0,
        "all_chunks_consumed": chunk_count > 0 and len(chunk_reports) == chunk_count,
        "all_chunks_processed": bool(chunk_reports)
        and all(item.get("status") in {"PROCESSED", "NO_TARGET_EVENTS"} for item in chunk_reports),
        "no_chunk_errors": not state.chunk_errors,
        "no_semantic_errors": not state.semantic_errors,
        "no_persistence_errors": not state.persistence_errors,
        "no_research_errors": not state.research_errors,
        "causal_lifecycle_seen": state.lifecycle_events_ingested > 0,
        "causal_trade_seen": state.market_trade_adapted_events > 0,
    }


async def _run_capture_async(
    *,
    api_key: str,
    bootstrap_report: Path,
    artifacts_root: Path,
    duration_seconds: int,
    cargo: str,
    chunk_max_bytes: int,
) -> dict[str, Any]:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if chunk_max_bytes <= 0:
        raise ValueError("chunk_max_bytes must be positive")

    evidence = load_bootstrap_evidence_v0(bootstrap_report)
    capture_id = _capture_id()
    run_dir = Path(artifacts_root) / capture_id
    raw_dir = run_dir / "raw-chunks"
    processed_root = run_dir / "processed-chunks"
    report_path = run_dir / "report.json"
    raw_dir.mkdir(parents=True, exist_ok=False)
    processed_root.mkdir(parents=True, exist_ok=True)

    discovery_start_wall_ns = time.time_ns()
    validate_bootstrap_before_discovery_start_v0(
        evidence,
        discovery_start_wall_ns=discovery_start_wall_ns,
    )
    discovery_close_wall_ns = discovery_start_wall_ns + int(duration_seconds) * 1_000_000_000

    queue: asyncio.Queue[Path | None] = asyncio.Queue()
    active_event = asyncio.Event()
    state = LiveDiscoveryPipelineStateV0()
    seed_bootstrap_identities_v0(state, evidence.identities)

    collector_task = asyncio.create_task(
        _collect_rotating(
            api_key=api_key,
            raw_dir=raw_dir,
            finalized_queue=queue,
            active_event=active_event,
            duration_seconds=duration_seconds,
            chunk_max_bytes=chunk_max_bytes,
        )
    )
    consumer_task = asyncio.create_task(
        _consume_chunks(
            queue=queue,
            state=state,
            api_key=api_key,
            cargo=cargo,
            acquisition_run_key=capture_id,
            processed_root=processed_root,
            discovery_start_wall_ns=discovery_start_wall_ns,
            discovery_close_wall_ns=discovery_close_wall_ns,
        )
    )

    fatal_error: str | None = None
    try:
        await asyncio.wait_for(active_event.wait(), timeout=ACTIVE_TIMEOUT_SECONDS)
        acquisition = await collector_task
        chunk_reports = await consumer_task
    except Exception as exc:
        fatal_error = f"{type(exc).__name__}:{redact_secret(str(exc), api_key)}"
        if not collector_task.done():
            collector_task.cancel()
            try:
                await collector_task
            except (asyncio.CancelledError, Exception):
                pass
        if not consumer_task.done():
            try:
                chunk_reports = await consumer_task
            except Exception:
                chunk_reports = []
        else:
            try:
                chunk_reports = consumer_task.result()
            except Exception:
                chunk_reports = []
        if collector_task.done() and not collector_task.cancelled():
            try:
                acquisition = collector_task.result()
            except Exception:
                acquisition = {
                    "type": "launch_burst_rotating_acquisition_v1",
                    "version": CAPTURE_VERSION,
                    "stop_reason": "fatal_error",
                    "chunk_count": len(chunk_reports),
                    "chunk_max_bytes": int(chunk_max_bytes),
                    "counters": {},
                    "valid_operational_shadow": False,
                }
        else:
            acquisition = {
                "type": "launch_burst_rotating_acquisition_v1",
                "version": CAPTURE_VERSION,
                "stop_reason": "fatal_error",
                "chunk_count": len(chunk_reports),
                "chunk_max_bytes": int(chunk_max_bytes),
                "counters": {},
                "valid_operational_shadow": False,
            }

    gates = _classification_gates(
        acquisition=acquisition,
        state=state,
        chunk_reports=chunk_reports,
    )
    gates["no_fatal_error"] = fatal_error is None
    passed = all(gates.values())

    report = {
        "type": "launch_burst_live_capture",
        "version": CAPTURE_VERSION,
        "capture_id": capture_id,
        "acquisition_run_key": capture_id,
        "duration_seconds": int(duration_seconds),
        "discovery_start_wall_ns": discovery_start_wall_ns,
        "discovery_close_wall_ns": discovery_close_wall_ns,
        "bootstrap": {
            "report_path": str(evidence.report_path.resolve()),
            "run_id": evidence.run_id,
            "decoded_identity_count": evidence.decoded_identity_count,
        },
        "acquisition": acquisition,
        "pipeline": state.summary(),
        "chunk_report_count": len(chunk_reports),
        "chunk_reports": chunk_reports,
        "fatal_error": fatal_error,
        "artifacts": {
            "run_dir": str(run_dir.resolve()),
            "raw_chunks": str(raw_dir.resolve()),
            "processed_root": str(processed_root.resolve()),
            "report": str(report_path.resolve()),
        },
        "gates": gates,
        "classification": (
            "PASS_LAUNCH_BURST_LIVE_CAPTURE_V1"
            if passed
            else "FAIL_LAUNCH_BURST_LIVE_CAPTURE_V1"
        ),
        "scientific_scope": {
            "feature_research_only": True,
            "economic_edge_evaluated": False,
            "future_outcomes_loaded": False,
            "chain_complete_coverage_claimed": False,
            "received_wall_ns_preserved_in_processed_manifest": True,
            "matched_unit_reconstructable_from_processed_evidence": True,
            "bounded_raw_chunk_processing": True,
            "raw_chunks_processed_incrementally": True,
        },
    }
    _write_json(report_path, report)
    return report


def run_capture(
    *,
    api_key: str,
    bootstrap_report: Path,
    artifacts_root: Path,
    duration_seconds: int,
    cargo: str = "cargo",
    chunk_max_bytes: int = DEFAULT_CHUNK_MAX_BYTES,
) -> dict[str, Any]:
    return asyncio.run(
        _run_capture_async(
            api_key=api_key,
            bootstrap_report=bootstrap_report,
            artifacts_root=artifacts_root,
            duration_seconds=duration_seconds,
            cargo=cargo,
            chunk_max_bytes=chunk_max_bytes,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotating bounded-memory Launch Burst live capture v1")
    parser.add_argument("--bootstrap-report", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument(
        "--chunk-max-mib",
        type=int,
        default=DEFAULT_CHUNK_MAX_BYTES // (1024 * 1024),
    )
    args = parser.parse_args()
    api_key = os.environ.get("HELIUS_API_KEY", "").strip()
    if not api_key:
        print("HELIUS_API_KEY is required in the environment", flush=True)
        return 2
    if args.chunk_max_mib <= 0:
        print("--chunk-max-mib must be positive", flush=True)
        return 2
    try:
        report = run_capture(
            api_key=api_key,
            bootstrap_report=args.bootstrap_report,
            artifacts_root=args.artifacts_root,
            duration_seconds=args.duration_seconds,
            cargo=args.cargo,
            chunk_max_bytes=args.chunk_max_mib * 1024 * 1024,
        )
    except Exception as exc:
        print(f"Launch Burst live capture v1 failed: {type(exc).__name__}: {exc}", flush=True)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    return 0 if report["classification"] == "PASS_LAUNCH_BURST_LIVE_CAPTURE_V1" else 2


if __name__ == "__main__":
    raise SystemExit(main())
