from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import time
from typing import Any, Sequence
import uuid

from benchmarks.helius_standard_wss_shadow_v0.collect import (
    COVERAGE_CLASSIFICATION,
    SOURCE_PROVIDER,
    Counters,
    _run_session,
    helius_wss_url,
    redact_secret,
)
from benchmarks.market_first_live_discovery_v0 import LIVE_DISCOVERY_VERSION
from benchmarks.market_first_live_discovery_v0.contracts import (
    DISCOVERY_DURATION_SECONDS,
    FAIL_CLASSIFICATION,
    PASS_CLASSIFICATION,
    SOURCE_SCOPE,
    classify_live_discovery_v0,
    load_bootstrap_evidence_v0,
    validate_bootstrap_before_discovery_start_v0,
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
from src.market_activity_discovery_audit_v0 import build_market_activity_discovery_audit_v0
from src.market_activity_discovery_run_v0 import (
    close_market_activity_discovery_run_v0,
    create_market_activity_discovery_run_v0,
    interrupt_market_activity_discovery_run_v0,
)
from src.market_activity_discovery_scanner_v0 import scan_open_market_activity_discovery_run_v0


DEFAULT_ARTIFACTS_ROOT = Path("artifacts") / LIVE_DISCOVERY_VERSION
ACQUISITION_PADDING_SECONDS = 120
ACTIVE_TIMEOUT_SECONDS = 30.0
START_GUARD_SECONDS = 2
ACQUISITION_DURATION_SECONDS = DISCOVERY_DURATION_SECONDS + ACQUISITION_PADDING_SECONDS


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _identity(started_at_hint: int) -> dict[str, str]:
    nonce = uuid.uuid4().hex[:12]
    run_id = f"{LIVE_DISCOVERY_VERSION}-{started_at_hint}-{nonce}"
    return {
        "run_id": run_id,
        "acquisition_run_key": run_id,
        "cohort_key": f"{run_id}:market-activity-discovery-v0",
    }


async def _collect_rotating_wss_v0(
    *,
    api_key: str,
    raw_dir: Path,
    finalized_queue: asyncio.Queue[Path | None],
    active_event: asyncio.Event,
    chunk_max_bytes: int,
) -> dict[str, Any]:
    counters = Counters()
    started_wall_ns = time.time_ns()
    started_monotonic = time.monotonic()
    global_deadline = started_monotonic + ACQUISITION_DURATION_SECONDS
    handle = RotatingTraceHandleV0(
        raw_dir=raw_dir,
        finalized_queue=finalized_queue,
        active_event=active_event,
        counters=counters,
        duration_seconds=float(ACQUISITION_DURATION_SECONDS),
        max_bytes=chunk_max_bytes,
    )
    websocket_url = helius_wss_url(api_key)
    stop_reason = "duration_elapsed"
    session_number = 0
    cancelled = False
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
                if stop_reason in {"duration_elapsed", "max_log_notifications"}:
                    break
            except (OSError, TimeoutError, RuntimeError, asyncio.TimeoutError):
                counters.transport_errors += 1
                if counters.reconnects >= 5 or time.monotonic() >= global_deadline:
                    stop_reason = "transport_error_reconnect_budget_exhausted"
                    break
                counters.reconnects += 1
                await asyncio.sleep(min(2.0, max(0.0, global_deadline - time.monotonic())))
    except asyncio.CancelledError:
        cancelled = True
        stop_reason = "cancelled"
        raise
    finally:
        handle.close(stop_reason=stop_reason)

    ended_wall_ns = time.time_ns()
    return {
        "type": "market_first_live_discovery_acquisition",
        "version": LIVE_DISCOVERY_VERSION,
        "source_provider": SOURCE_PROVIDER,
        "source_scope": SOURCE_SCOPE,
        "coverage_classification": COVERAGE_CLASSIFICATION,
        "chain_complete_coverage_claimed": False,
        "valid_chain_complete_coverage": False,
        "started_wall_ns": started_wall_ns,
        "ended_wall_ns": ended_wall_ns,
        "elapsed_seconds": max(0.0, time.monotonic() - started_monotonic),
        "configured_duration_seconds": ACQUISITION_DURATION_SECONDS,
        "stop_reason": stop_reason,
        "cancelled": cancelled,
        "chunk_count": handle.chunk_count,
        "counters": asdict(counters),
        "log_notifications": counters.log_notifications,
        "valid_operational_shadow": counters.sessions_activated > 0,
    }


async def _consume_chunks_v0(
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


def _gates(
    *,
    report: dict[str, Any],
    state: LiveDiscoveryPipelineStateV0,
) -> dict[str, bool]:
    acquisition = report.get("acquisition") or {}
    counters = acquisition.get("counters") or {}
    run = report.get("run") or {}
    audit = report.get("audit") or {}
    pipeline = state.summary()
    adapted = int(pipeline.get("market_trade_adapted_events") or 0)
    ingested = int(pipeline.get("kernel_trade_events_ingested") or 0)
    discovery_close_wall_ns = int(report.get("discovery_close_wall_ns") or 0)
    return {
        "bootstrap_was_real_pass": bool(report.get("bootstrap_validated")),
        "fixed_six_hour_admission_window": (
            int(report.get("discovery_duration_seconds") or 0) == DISCOVERY_DURATION_SECONDS
            and int(run.get("admission_closes_at") or 0) - int(run.get("started_at") or 0)
            == DISCOVERY_DURATION_SECONDS
        ),
        "wss_operational_shadow_active": acquisition.get("valid_operational_shadow") is True,
        "acquisition_spanned_entire_admission_window": (
            int(acquisition.get("ended_wall_ns") or 0) >= discovery_close_wall_ns > 0
        ),
        "no_observed_transport_gap": (
            int(counters.get("transport_errors") or 0) == 0
            and int(counters.get("reconnects") or 0) == 0
            and acquisition.get("stop_reason") == "duration_elapsed"
        ),
        "all_trace_chunks_processed": (
            int(acquisition.get("chunk_count") or 0) == int(pipeline.get("chunks_processed") or 0)
            and int(acquisition.get("chunk_count") or 0) > 0
        ),
        "canonical_trade_reached_kernel": adapted > 0 and ingested == adapted,
        "chunk_processing_healthy": not pipeline.get("chunk_errors"),
        "persistence_healthy": not pipeline.get("persistence_errors"),
        "research_handoff_healthy": not pipeline.get("research_errors"),
        "canonical_semantics_healthy": not pipeline.get("semantic_errors"),
        "pre_economic_integrity_audit_ready": audit.get("integrity_ready_for_close_or_analysis") is True,
        "run_closed_normally": run.get("status") == "CLOSED",
        "coverage_claim_is_operational_only": (
            report.get("coverage_classification") == COVERAGE_CLASSIFICATION
            and report.get("chain_complete_coverage_claimed") is False
        ),
        "no_economic_verdict": report.get("economic_edge_evaluated") is False,
        "clean_shutdown": report.get("clean_shutdown") is True,
        "no_fatal_stage_error": not bool(report.get("fatal_error")),
    }


async def _run_live_discovery_async_v0(
    *,
    api_key: str,
    bootstrap_report_path: Path,
    artifacts_root: Path,
    cargo: str,
    chunk_max_bytes: int,
) -> dict[str, Any]:
    if not api_key.strip():
        raise ValueError("HELIUS_API_KEY cannot be blank")
    evidence = load_bootstrap_evidence_v0(Path(bootstrap_report_path))
    identity = _identity(int(time.time()))
    run_id = identity["run_id"]
    run_dir = Path(artifacts_root) / run_id
    raw_dir = run_dir / "raw-chunks"
    processed_root = run_dir / "processed-chunks"
    report_path = run_dir / "report.json"
    run_dir.mkdir(parents=True, exist_ok=False)
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_root.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "type": "market_first_live_discovery",
        "live_discovery_version": LIVE_DISCOVERY_VERSION,
        "identity": identity,
        "bootstrap": {
            "report_path": str(evidence.report_path),
            "run_id": evidence.run_id,
            "identities_path": str(evidence.identities_path),
            "observed_pool_count": evidence.observed_pool_count,
            "decoded_identity_count": evidence.decoded_identity_count,
            "unresolved_pool_count": evidence.unresolved_pool_count,
        },
        "discovery_duration_seconds": DISCOVERY_DURATION_SECONDS,
        "coverage_classification": COVERAGE_CLASSIFICATION,
        "chain_complete_coverage_claimed": False,
        "economic_edge_evaluated": False,
        "clean_shutdown": False,
        "artifacts": {
            "run_dir": str(run_dir),
            "raw_chunks": str(raw_dir),
            "processed_chunks": str(processed_root),
            "report": str(report_path),
        },
    }

    queue: asyncio.Queue[Path | None] = asyncio.Queue()
    active_event = asyncio.Event()
    collector_task = asyncio.create_task(
        _collect_rotating_wss_v0(
            api_key=api_key,
            raw_dir=raw_dir,
            finalized_queue=queue,
            active_event=active_event,
            chunk_max_bytes=chunk_max_bytes,
        )
    )
    run_created = False
    state = LiveDiscoveryPipelineStateV0()
    consumer_task: asyncio.Task[list[dict[str, Any]]] | None = None

    try:
        active_wait = asyncio.create_task(active_event.wait())
        done, _pending = await asyncio.wait(
            {active_wait, collector_task},
            timeout=ACTIVE_TIMEOUT_SECONDS,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not active_event.is_set():
            if collector_task in done:
                await collector_task
            raise RuntimeError("WSS did not become active before live discovery start")
        if not active_wait.done():
            active_wait.cancel()

        started_at = int(time.time()) + START_GUARD_SECONDS
        discovery_start_wall_ns = started_at * 1_000_000_000
        discovery_close_wall_ns = (
            started_at + DISCOVERY_DURATION_SECONDS
        ) * 1_000_000_000
        validate_bootstrap_before_discovery_start_v0(
            evidence,
            discovery_start_wall_ns=discovery_start_wall_ns,
        )
        report["bootstrap_validated"] = True
        report["discovery_start_wall_ns"] = discovery_start_wall_ns
        report["discovery_close_wall_ns"] = discovery_close_wall_ns

        run = create_market_activity_discovery_run_v0(
            acquisition_run_key=identity["acquisition_run_key"],
            cohort_key=identity["cohort_key"],
            started_at=started_at,
        )
        run_created = True
        report["run"] = asdict(run)
        seed_bootstrap_identities_v0(state, evidence.identities)

        consumer_task = asyncio.create_task(
            _consume_chunks_v0(
                queue=queue,
                state=state,
                api_key=api_key,
                cargo=cargo,
                acquisition_run_key=run.acquisition_run_key,
                processed_root=processed_root,
                discovery_start_wall_ns=discovery_start_wall_ns,
                discovery_close_wall_ns=discovery_close_wall_ns,
            )
        )

        acquisition = await collector_task
        report["acquisition"] = acquisition
        if int(acquisition.get("ended_wall_ns") or 0) < discovery_close_wall_ns:
            raise RuntimeError("WSS acquisition ended before the six-hour admission window closed")

        chunk_reports = await consumer_task
        report["chunk_report_count"] = len(chunk_reports)
        report["pipeline"] = state.summary()

        if (
            state.chunk_errors
            or state.persistence_errors
            or state.research_errors
            or state.semantic_errors
        ):
            raise RuntimeError("live discovery pipeline recorded integrity errors")

        scan = scan_open_market_activity_discovery_run_v0(
            acquisition_run_key=run.acquisition_run_key,
        )
        report["catch_up_scan"] = asdict(scan)
        audit = build_market_activity_discovery_audit_v0(
            acquisition_run_key=run.acquisition_run_key,
        )
        report["audit"] = asdict(audit)
        if not audit.integrity_ready_for_close_or_analysis:
            raise RuntimeError("pre-economic discovery integrity audit is not ready")
        if int(time.time()) < run.admission_closes_at:
            raise RuntimeError("acquisition padding did not outlive the frozen admission deadline")
        closed = close_market_activity_discovery_run_v0(
            acquisition_run_key=run.acquisition_run_key,
            observed_at=int(time.time()),
        )
        report["run"] = asdict(closed)
    except Exception as exc:
        report["fatal_error"] = f"{type(exc).__name__}:{redact_secret(str(exc), api_key)}"
        if not collector_task.done():
            collector_task.cancel()
            try:
                await collector_task
            except (asyncio.CancelledError, Exception):
                pass
        if consumer_task is not None and not consumer_task.done():
            # The rotating collector closes its queue in finally. Give already-durable
            # finalized chunks a chance to drain before marking the run interrupted.
            try:
                await consumer_task
            except Exception:
                pass
        if run_created:
            try:
                interrupted = interrupt_market_activity_discovery_run_v0(
                    acquisition_run_key=identity["acquisition_run_key"],
                    observed_at=int(time.time()),
                    reason=str(report["fatal_error"]),
                )
                report["run"] = asdict(interrupted)
            except Exception as interrupt_exc:
                report["interrupt_error"] = (
                    f"{type(interrupt_exc).__name__}:{redact_secret(str(interrupt_exc), api_key)}"
                )
    finally:
        report["pipeline"] = state.summary()
        report["ended_at"] = int(time.time())
        report["clean_shutdown"] = True
        report["gates"] = _gates(report=report, state=state)
        report["classification"] = classify_live_discovery_v0(report["gates"])
        report["valid_live_discovery"] = report["classification"] == PASS_CLASSIFICATION
        _write_json(report_path, report)

    return report


def run_live_discovery_v0(
    *,
    api_key: str,
    bootstrap_report_path: Path,
    artifacts_root: Path = DEFAULT_ARTIFACTS_ROOT,
    cargo: str = "cargo",
    chunk_max_bytes: int = DEFAULT_CHUNK_MAX_BYTES,
) -> dict[str, Any]:
    return asyncio.run(
        _run_live_discovery_async_v0(
            api_key=api_key,
            bootstrap_report_path=Path(bootstrap_report_path),
            artifacts_root=Path(artifacts_root),
            cargo=cargo,
            chunk_max_bytes=chunk_max_bytes,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=LIVE_DISCOVERY_VERSION,
        description=(
            "Fixed six-hour Market-First live discovery coordinator. Requires a real "
            "PumpSwap identity bootstrap PASS; no economic verdict is produced."
        ),
    )
    parser.add_argument("--bootstrap-report", type=Path, required=True)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument(
        "--chunk-max-mib",
        type=int,
        default=DEFAULT_CHUNK_MAX_BYTES // (1024 * 1024),
        help="Operational evidence rotation size only; does not change the six-hour protocol.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    api_key = os.environ.get("HELIUS_API_KEY", "")
    if not api_key.strip():
        print("HELIUS_API_KEY is required in the environment", flush=True)
        return 2
    if args.chunk_max_mib <= 0:
        print("--chunk-max-mib must be positive", flush=True)
        return 2
    report = run_live_discovery_v0(
        api_key=api_key,
        bootstrap_report_path=args.bootstrap_report,
        artifacts_root=args.artifacts_root,
        cargo=args.cargo,
        chunk_max_bytes=args.chunk_max_mib * 1024 * 1024,
    )
    print(json.dumps(report, sort_keys=True, indent=2), flush=True)
    return 0 if report.get("valid_live_discovery") else 1


if __name__ == "__main__":
    raise SystemExit(main())
