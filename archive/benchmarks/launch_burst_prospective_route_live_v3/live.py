from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
from typing import Any, Callable

from dotenv import load_dotenv

from benchmarks.helius_standard_wss_shadow_v0.collect import Counters
from benchmarks.helius_standard_wss_shadow_v0.reduce import reduce_shadow
from benchmarks.launch_burst_prospective_route_paper_v2.live import (
    OnlinePumpFeatureState,
    _capture_selected_episode,
    _collect,
    _entry_ready_second,
    _episode,
    _rotation_loop,
)
from benchmarks.launch_burst_prospective_route_paper_v2.run import run_route_paper_v2
from benchmarks.market_first_live_discovery_v0.rotating_trace import RotatingTraceHandleV0
from benchmarks.market_first_live_smoke_v0.run import (
    CARBON_MANIFEST_PATH,
    _decoder_footer_valid,
    _jsonl,
)
from src.launch_burst_route_paper_v2 import selection_decision, validate_contract

LIVE_VERSION = "launch_burst_prospective_route_live_v3"
PASS_SYSTEMS = "PASS_LAUNCH_BURST_PROSPECTIVE_ROUTE_SYSTEMS_V3"
PASS_LIVE = "PASS_LAUNCH_BURST_PROSPECTIVE_ROUTE_LIVE_V3"
FAIL_LIVE = "FAIL_LAUNCH_BURST_PROSPECTIVE_ROUTE_LIVE_V3"
FAIL_CAPACITY = "FAIL_PROCESSING_CAPACITY"
EXPECTED_ROUTE_CONTRACT_HASH = "3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d"
DEFAULT_DURATION_SECONDS = 900
DEFAULT_ROTATION_SECONDS = 1.0
DEFAULT_CHUNK_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_ARTIFACTS_ROOT = Path("artifacts") / LIVE_VERSION
DEFAULT_CONTRACT = (
    Path("benchmarks")
    / "launch_burst_prospective_economic_v1"
    / "pump_route_paper_contract_v2.frozen.json"
)
DECODER_BINARY_NAME = "carbon-decoder-parity-v1-runner"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _run_id() -> str:
    return f"{LIVE_VERSION}-{int(time.time())}-{uuid.uuid4().hex[:10]}"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(item) for item in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _distribution(values: list[float]) -> dict[str, float | None]:
    return {
        "p50": _percentile(values, 0.50),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": max(values) if values else None,
    }


def _decoder_binary_path(target_dir: Path) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return target_dir / "release" / f"{DECODER_BINARY_NAME}{suffix}"


def _build_decoder(*, cargo: str, target_dir: Path) -> dict[str, Any]:
    target_dir = target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    command = [
        cargo,
        "build",
        "--release",
        "--quiet",
        "--manifest-path",
        str(CARBON_MANIFEST_PATH),
    ]
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target_dir)
    started_wall_ns = time.time_ns()
    started = time.perf_counter_ns()
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
        env=env,
    )
    finished_wall_ns = time.time_ns()
    service_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    binary = _decoder_binary_path(target_dir)
    report = {
        "invocations": 1,
        "command": command,
        "target_dir": str(target_dir),
        "binary": str(binary.resolve()),
        "process_return_code": completed.returncode,
        "stderr_tail": completed.stderr[-4000:],
        "stdout_tail": completed.stdout[-4000:],
        "started_wall_ns": started_wall_ns,
        "finished_wall_ns": finished_wall_ns,
        "service_ms": service_ms,
        "binary_exists": binary.exists(),
    }
    if completed.returncode != 0 or not binary.exists():
        raise RuntimeError(
            "Carbon decoder build failed: "
            f"return_code={completed.returncode} binary_exists={binary.exists()} "
            f"stderr={completed.stderr[-1000:]}"
        )
    return report


def _run_decoder_binary(
    *,
    binary: Path,
    carbon_input_path: Path,
    carbon_output_path: Path,
) -> dict[str, Any]:
    command = [str(binary), str(carbon_input_path), str(carbon_output_path)]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    rows = _jsonl(carbon_output_path)
    footer = next(
        (row for row in reversed(rows) if row.get("type") == "carbon_decoder_footer"),
        {},
    )
    expected_inputs = sum(
        1
        for row in _jsonl(carbon_input_path)
        if row.get("type") == "carbon_decoder_input"
    )
    return {
        "command": command,
        "direct_binary": True,
        "cargo_run_used": False,
        "process_return_code": completed.returncode,
        "stderr_tail": completed.stderr[-4000:],
        "stdout_tail": completed.stdout[-4000:],
        "footer": footer,
        "footer_accounting_valid": _decoder_footer_valid(
            footer,
            expected_input_events=expected_inputs,
            process_return_code=completed.returncode,
        ),
    }


def _process_chunk(
    *,
    raw_path: Path,
    processed_root: Path,
    decoder_binary: Path,
    finalized_wall_ns: int,
    queue_depth_at_start: int,
) -> dict[str, Any]:
    chunk_dir = processed_root / raw_path.stem
    chunk_dir.mkdir(parents=True, exist_ok=False)
    carbon_input = chunk_dir / "carbon-input.jsonl"
    manifest = chunk_dir / "target-manifest.jsonl"
    carbon_output = chunk_dir / "carbon-canonical.jsonl"
    report_path = chunk_dir / "chunk-report.json"

    processing_started_wall_ns = time.time_ns()
    total_started = time.perf_counter_ns()
    queue_wait_ms = max(0.0, (processing_started_wall_ns - finalized_wall_ns) / 1_000_000.0)
    reducer_service_ms = 0.0
    decoder_service_ms = 0.0
    report: dict[str, Any] = {
        "chunk": raw_path.stem,
        "status": "STARTED",
        "telemetry": {
            "finalized_wall_ns": int(finalized_wall_ns),
            "processing_started_wall_ns": int(processing_started_wall_ns),
            "queue_wait_ms": queue_wait_ms,
            "queue_depth_at_start": int(queue_depth_at_start),
        },
    }
    try:
        reducer_started = time.perf_counter_ns()
        reducer = reduce_shadow(
            trace_path=raw_path,
            carbon_input_path=carbon_input,
            manifest_path=manifest,
        )
        reducer_service_ms = (time.perf_counter_ns() - reducer_started) / 1_000_000.0
        report["reducer"] = reducer
        accepted = int(reducer.get("accepted_success_target_events") or 0)
        if accepted == 0:
            report["status"] = "NO_TARGET_EVENTS"
        else:
            if not reducer.get("valid_for_carbon_decode"):
                raise RuntimeError("frozen reducer rejected prospective chunk")
            decoder_started = time.perf_counter_ns()
            decoder = _run_decoder_binary(
                binary=decoder_binary,
                carbon_input_path=carbon_input,
                carbon_output_path=carbon_output,
            )
            decoder_service_ms = (time.perf_counter_ns() - decoder_started) / 1_000_000.0
            report["decoder"] = decoder
            if not decoder.get("footer_accounting_valid"):
                raise RuntimeError("Carbon event decoder accounting failed")
            report["status"] = "PROCESSED"
    except Exception as exc:
        report["status"] = "FAILED"
        report["error"] = f"{type(exc).__name__}:{exc}"
    finally:
        finished_wall_ns = time.time_ns()
        total_service_ms = (time.perf_counter_ns() - total_started) / 1_000_000.0
        report["telemetry"].update(
            {
                "processing_finished_wall_ns": int(finished_wall_ns),
                "reducer_service_ms": reducer_service_ms,
                "decoder_service_ms": decoder_service_ms,
                "total_service_ms": total_service_ms,
            }
        )
        _write_json(report_path, report)
    return report


def _dispatch_timing(
    *,
    snapshot: dict[str, Any],
    contract: dict[str, Any],
    snapshot_frozen_wall_ns: int,
) -> dict[str, Any]:
    cutoff_ns = int(snapshot["decision_cutoff_wall_ns"])
    entry_ready_at = _entry_ready_second(snapshot, contract)
    entry_deadline_at = entry_ready_at + int(contract["entry"]["max_quote_wait_seconds"])
    frozen_seconds = snapshot_frozen_wall_ns / 1_000_000_000.0
    return {
        "decision_cutoff_wall_ns": cutoff_ns,
        "snapshot_frozen_wall_ns": int(snapshot_frozen_wall_ns),
        "snapshot_dispatch_lag_ms": (snapshot_frozen_wall_ns - cutoff_ns) / 1_000_000.0,
        "entry_ready_at": int(entry_ready_at),
        "entry_deadline_at": int(entry_deadline_at),
        "would_meet_entry_ready": frozen_seconds <= entry_ready_at,
        "would_meet_entry_deadline": frozen_seconds <= entry_deadline_at,
    }


async def _dispatch_snapshot(
    *,
    episode_key: str,
    token_mint: str,
    snapshot: dict[str, Any],
    contract: dict[str, Any],
    systems_only: bool,
    provider_factory: Callable[..., Any] = _capture_selected_episode,
    provider_kwargs: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, asyncio.Task[dict[str, Any]] | None]:
    snapshot_frozen_wall_ns = time.time_ns()
    admitted, reason = selection_decision(snapshot, contract)
    timing = _dispatch_timing(
        snapshot=snapshot,
        contract=contract,
        snapshot_frozen_wall_ns=snapshot_frozen_wall_ns,
    )
    timing.update(
        {
            "episode_key": episode_key,
            "token_mint": token_mint,
            "selected": bool(admitted),
            "selection_reason": reason,
        }
    )

    if systems_only:
        return (
            {
                **timing,
                "provider_calls_enabled": False,
                "economic_outcome_opened": False,
            },
            None,
        )

    if not admitted:
        return (
            _episode(
                episode_key=episode_key,
                token_mint=token_mint,
                snapshot=snapshot,
                quotes=[],
                collection={
                    **timing,
                    "provider_calls_started": False,
                    "entry_status": reason,
                },
            ),
            None,
        )

    kwargs = dict(provider_kwargs or {})
    task = asyncio.create_task(
        provider_factory(
            episode_key=episode_key,
            token_mint=token_mint,
            snapshot=snapshot,
            contract=contract,
            **kwargs,
        )
    )
    return None, task


def _systems_summary(observations: list[dict[str, Any]]) -> dict[str, Any]:
    selected = [item for item in observations if item.get("selected") is True]
    complete = [item for item in observations if item.get("decision_cutoff_wall_ns") is not None]
    lags = [float(item["snapshot_dispatch_lag_ms"]) for item in complete]
    before_ready = sum(1 for item in selected if item.get("would_meet_entry_ready") is True)
    before_deadline = sum(1 for item in selected if item.get("would_meet_entry_deadline") is True)
    return {
        "snapshot_dispatch_lag_ms": _distribution(lags),
        "selected_count": len(selected),
        "selected_before_entry_ready": before_ready,
        "selected_before_deadline": before_deadline,
        "selected_missed_deadline": len(selected) - before_deadline,
    }


def _processing_summary(chunk_reports: list[dict[str, Any]]) -> dict[str, Any]:
    telemetry = [
        item.get("telemetry") or {}
        for item in chunk_reports
        if isinstance(item.get("telemetry"), dict)
    ]
    queue_wait = [float(item["queue_wait_ms"]) for item in telemetry if item.get("queue_wait_ms") is not None]
    total_service = [float(item["total_service_ms"]) for item in telemetry if item.get("total_service_ms") is not None]
    reducer_service = [float(item["reducer_service_ms"]) for item in telemetry if item.get("reducer_service_ms") is not None]
    decoder_service = [float(item["decoder_service_ms"]) for item in telemetry if item.get("decoder_service_ms") is not None]
    queue_depths = [int(item.get("queue_depth_at_start") or 0) for item in telemetry]
    return {
        "queue_wait_ms": _distribution(queue_wait),
        "total_service_ms": _distribution(total_service),
        "reducer_service_ms": _distribution(reducer_service),
        "decoder_service_ms": _distribution(decoder_service),
        "max_queue_depth": max(queue_depths) if queue_depths else 0,
    }


async def run_live(
    *,
    contract_path: Path,
    artifacts_root: Path,
    duration_seconds: int,
    rotation_seconds: float,
    chunk_max_bytes: int,
    cargo: str,
    helius_api_key: str,
    jupiter_api_key: str,
    taker_public_key: str,
    rpc_url: str,
    rpc_fallback_urls: tuple[str, ...],
    systems_only: bool,
) -> dict[str, Any]:
    contract = _read_json(contract_path)
    validate_contract(contract)
    contract_hash_unchanged = contract.get("contract_hash_sha256") == EXPECTED_ROUTE_CONTRACT_HASH
    if not contract_hash_unchanged:
        raise ValueError("Launch Burst route-paper contract hash changed; V3 refuses to proceed")
    if duration_seconds <= 0 or rotation_seconds <= 0 or chunk_max_bytes <= 0:
        raise ValueError("duration, rotation and chunk size must be positive")
    if not helius_api_key:
        raise ValueError("HELIUS_API_KEY is required")
    if not systems_only and (not jupiter_api_key or not taker_public_key or not rpc_url):
        raise ValueError("economic mode requires JUPITER_API_KEY, JUPITER_TAKER_PUBLIC_KEY and SOLANA_RPC_URL")

    run_id = _run_id()
    run_dir = artifacts_root / run_id
    raw_dir = run_dir / "raw-chunks"
    processed_root = run_dir / "processed-chunks"
    decoder_target_dir = run_dir / "decoder-build"
    report_path = run_dir / "report.json"
    input_path = run_dir / "route-input-v2.json"
    result_path = run_dir / "route-result-v2.json"
    raw_dir.mkdir(parents=True, exist_ok=False)
    processed_root.mkdir(parents=True, exist_ok=True)

    decoder_build = await asyncio.to_thread(
        _build_decoder,
        cargo=cargo,
        target_dir=decoder_target_dir,
    )
    decoder_binary = Path(str(decoder_build["binary"]))

    capture_started_wall_ns = time.time_ns()
    queue: asyncio.Queue[Path | None] = asyncio.Queue()
    active_event = asyncio.Event()
    counters = Counters()
    handle = RotatingTraceHandleV0(
        raw_dir=raw_dir,
        finalized_queue=queue,
        active_event=active_event,
        counters=counters,
        duration_seconds=float(duration_seconds),
        max_bytes=chunk_max_bytes,
    )
    online = OnlinePumpFeatureState()
    episodes: list[dict[str, Any]] = []
    systems_observations: list[dict[str, Any]] = []
    provider_tasks: list[asyncio.Task[dict[str, Any]]] = []
    chunk_reports: list[dict[str, Any]] = []
    processing_errors: list[str] = []
    stop_rotation = asyncio.Event()

    async def consume() -> None:
        while True:
            raw_path = await queue.get()
            try:
                if raw_path is None:
                    break
                finalized_ns = handle.finalized_wall_ns(raw_path)
                if finalized_ns is None:
                    raise RuntimeError("finalized chunk is missing causal finalize clock")
                queue_depth = queue.qsize()
                report = await asyncio.to_thread(
                    _process_chunk,
                    raw_path=raw_path,
                    processed_root=processed_root,
                    decoder_binary=decoder_binary,
                    finalized_wall_ns=finalized_ns,
                    queue_depth_at_start=queue_depth,
                )
                chunk_reports.append(report)
                if report.get("status") == "FAILED":
                    processing_errors.append(str(report.get("error") or "chunk failed"))
                    continue
                online.ingest_processed_chunk(processed_root / raw_path.stem)
                for token_mint, snapshot in online.ready_snapshots(
                    coverage_through_wall_ns=finalized_ns
                ):
                    episode_key = f"pump:{token_mint}:{snapshot['observed_t0_wall_ns']}"
                    immediate, task = await _dispatch_snapshot(
                        episode_key=episode_key,
                        token_mint=token_mint,
                        snapshot=snapshot,
                        contract=contract,
                        systems_only=systems_only,
                        provider_kwargs={
                            "jupiter_api_key": jupiter_api_key,
                            "taker_public_key": taker_public_key,
                            "rpc_url": rpc_url,
                            "rpc_fallback_urls": rpc_fallback_urls,
                        },
                    )
                    if immediate is not None:
                        if systems_only:
                            systems_observations.append(immediate)
                        else:
                            episodes.append(immediate)
                    if task is not None:
                        provider_tasks.append(task)
            finally:
                queue.task_done()

    collector_task = asyncio.create_task(
        _collect(
            handle=handle,
            counters=counters,
            api_key=helius_api_key,
            duration_seconds=duration_seconds,
        )
    )
    consumer_task = asyncio.create_task(consume())
    rotation_task = asyncio.create_task(
        _rotation_loop(
            handle,
            interval_seconds=rotation_seconds,
            stop_event=stop_rotation,
        )
    )

    try:
        await asyncio.wait_for(active_event.wait(), timeout=30.0)
        acquisition = await collector_task
        stop_rotation.set()
        await consumer_task
    except Exception:
        if not collector_task.done():
            collector_task.cancel()
        if not consumer_task.done():
            consumer_task.cancel()
        raise
    finally:
        stop_rotation.set()
        if not rotation_task.done():
            rotation_task.cancel()
            try:
                await rotation_task
            except asyncio.CancelledError:
                pass

    if systems_only:
        for token_mint, snapshot in online.right_censored_snapshots():
            systems_observations.append(
                {
                    "episode_key": f"pump:{token_mint}:{snapshot['observed_t0_wall_ns']}",
                    "token_mint": token_mint,
                    "selected": False,
                    "selection_reason": "RIGHT_CENSORED",
                    "provider_calls_enabled": False,
                    "economic_outcome_opened": False,
                    "right_censored": True,
                }
            )
    else:
        for token_mint, snapshot in online.right_censored_snapshots():
            episodes.append(
                _episode(
                    episode_key=f"pump:{token_mint}:{snapshot['observed_t0_wall_ns']}",
                    token_mint=token_mint,
                    snapshot=snapshot,
                    quotes=[],
                    collection={
                        "snapshot_frozen_wall_ns": time.time_ns(),
                        "provider_calls_started": False,
                        "right_censored": True,
                    },
                )
            )
        if provider_tasks:
            episodes.extend(await asyncio.gather(*provider_tasks))
        episodes.sort(
            key=lambda item: (
                int(item["feature_snapshot"]["observed_t0_wall_ns"]),
                item["token_mint"],
            )
        )

    processing = _processing_summary(chunk_reports)
    systems = _systems_summary(systems_observations) if systems_only else None
    route_result: dict[str, Any] | None = None
    if not systems_only:
        source = {
            "type": "launch_burst_prospective_route_input_v2",
            "version": LIVE_VERSION,
            "contract_hash_sha256": contract["contract_hash_sha256"],
            "source_capture_started_after_contract_freeze": True,
            "feature_snapshot_frozen_before_provider_quotes": True,
            "capture_started_wall_ns": capture_started_wall_ns,
            "capture_ended_wall_ns": time.time_ns(),
            "acquisition_run_key": run_id,
            "episodes": episodes,
        }
        _write_json(input_path, source)
        route_result = run_route_paper_v2(
            contract_path=contract_path,
            input_path=input_path,
            output_path=result_path,
        )

    common_gates = {
        "contract_hash_unchanged": contract_hash_unchanged,
        "decoder_built_once": decoder_build.get("invocations") == 1,
        "decoder_binary_exists": decoder_build.get("binary_exists") is True,
        "duration_elapsed": acquisition.get("stop_reason") == "duration_elapsed",
        "transport_errors_zero": int(counters.transport_errors) == 0,
        "reconnects_zero": int(counters.reconnects) == 0,
        "processing_errors_zero": not processing_errors,
    }

    if systems_only:
        assert systems is not None
        gates = {
            **common_gates,
            "provider_calls_disabled": len(provider_tasks) == 0,
            "economic_outcomes_closed": True,
            "selected_missed_deadline_zero": systems["selected_missed_deadline"] == 0,
        }
        if systems["selected_missed_deadline"] > 0 and all(
            value
            for key, value in gates.items()
            if key != "selected_missed_deadline_zero"
        ):
            classification = FAIL_CAPACITY
        else:
            classification = PASS_SYSTEMS if all(gates.values()) else FAIL_LIVE
    else:
        gates = {
            **common_gates,
            "route_runner_pass": bool(
                route_result
                and route_result.get("classification")
                == "PASS_LAUNCH_BURST_PROSPECTIVE_ROUTE_PAPER_V2"
            ),
        }
        classification = PASS_LIVE if all(gates.values()) else FAIL_LIVE

    report = {
        "type": "launch_burst_prospective_route_live_report_v3",
        "version": LIVE_VERSION,
        "classification": classification,
        "mode": "systems_only" if systems_only else "route_paper_economic",
        "acquisition_run_key": run_id,
        "contract_hash_sha256": contract["contract_hash_sha256"],
        "economic_outcomes_opened": not systems_only,
        "provider_calls_enabled": not systems_only,
        "capture": acquisition,
        "chunk_count": len(chunk_reports),
        "episode_count": len(systems_observations) if systems_only else len(episodes),
        "provider_task_count": len(provider_tasks),
        "processing_errors": processing_errors,
        "decoder_build": decoder_build,
        "processing": processing,
        "systems": systems,
        "gates": gates,
        "artifacts": {
            "report": str(report_path.resolve()),
            "input": None if systems_only else str(input_path.resolve()),
            "result": None if systems_only else str(result_path.resolve()),
        },
        "interpretation": (
            "Systems-only mode opens no Jupiter/RPC economic outcomes and tests whether the frozen signal "
            "can reach its provider dispatch deadline. Route-paper mode retains the frozen V2 contract and "
            "does not claim landed fills or realized PnL."
        ),
    }
    _write_json(report_path, report)
    if systems_only:
        _write_json(run_dir / "systems-observations.json", {"observations": systems_observations})
    return report


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Launch Burst prospective live V3 with prebuilt Carbon decoder and systems-only gate"
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--duration-seconds", type=int, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--rotation-seconds", type=float, default=DEFAULT_ROTATION_SECONDS)
    parser.add_argument("--chunk-max-mib", type=int, default=DEFAULT_CHUNK_MAX_BYTES // (1024 * 1024))
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--systems-only", action="store_true")
    args = parser.parse_args()

    fallback_urls = tuple(
        item.strip()
        for item in os.environ.get("SOLANA_RPC_FALLBACK_URLS", "").split(",")
        if item.strip()
    )
    try:
        report = asyncio.run(
            run_live(
                contract_path=args.contract,
                artifacts_root=args.artifacts_root,
                duration_seconds=args.duration_seconds,
                rotation_seconds=args.rotation_seconds,
                chunk_max_bytes=args.chunk_max_mib * 1024 * 1024,
                cargo=args.cargo,
                helius_api_key=os.environ.get("HELIUS_API_KEY", "").strip(),
                jupiter_api_key=os.environ.get("JUPITER_API_KEY", "").strip(),
                taker_public_key=os.environ.get("JUPITER_TAKER_PUBLIC_KEY", "").strip(),
                rpc_url=os.environ.get("SOLANA_RPC_URL", "").strip(),
                rpc_fallback_urls=fallback_urls,
                systems_only=bool(args.systems_only),
            )
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": FAIL_LIVE,
                    "error": f"{type(exc).__name__}:{exc}",
                },
                indent=2,
            )
        )
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if str(report.get("classification", "")).startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
