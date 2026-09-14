from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import time
import uuid
from typing import Any

from dotenv import load_dotenv

from benchmarks.helius_standard_wss_shadow_v0.collect import Counters
from benchmarks.launch_burst_prospective_route_paper_v2.live import (
    _capture_selected_episode,
    _collect,
    _episode,
)
from benchmarks.launch_burst_prospective_route_paper_v2.run import run_route_paper_v2
from benchmarks.launch_burst_prospective_route_live_v3.live import (
    DEFAULT_CHUNK_MAX_BYTES,
    DEFAULT_CONTRACT,
    DEFAULT_DURATION_SECONDS,
    DEFAULT_ROTATION_SECONDS,
    EXPECTED_ROUTE_CONTRACT_HASH,
    OnlinePumpFeatureState,
    _build_decoder,
    _dispatch_snapshot,
    _processing_summary,
    _read_json,
    _systems_summary,
    _write_json,
    _process_chunk,
)
from benchmarks.market_first_live_discovery_v0.rotating_trace import RotatingTraceHandleV0
from src.launch_burst_route_paper_v2 import validate_contract

LIVE_VERSION = "launch_burst_prospective_route_live_v4"
PASS_SYSTEMS = "PASS_LAUNCH_BURST_PROSPECTIVE_ROUTE_SYSTEMS_V4"
PASS_LIVE = "PASS_LAUNCH_BURST_PROSPECTIVE_ROUTE_LIVE_V4"
FAIL_LIVE = "FAIL_LAUNCH_BURST_PROSPECTIVE_ROUTE_LIVE_V4"
FAIL_CAPACITY = "FAIL_PROCESSING_CAPACITY"
DEFAULT_ARTIFACTS_ROOT = Path("artifacts") / LIVE_VERSION
WATERMARK_EVENT = "coverage_watermark"


def _run_id() -> str:
    return f"{LIVE_VERSION}-{int(time.time())}-{uuid.uuid4().hex[:10]}"


def _default_decoder_target() -> Path:
    configured = os.environ.get("LAUNCH_BURST_V3_DECODER_TARGET_DIR", "").strip()
    if configured:
        return Path(configured)
    if os.name == "nt":
        drive = os.environ.get("SystemDrive", "C:").rstrip("\\/")
        return Path(drive + "\\lbv3-decoder")
    return DEFAULT_ARTIFACTS_ROOT / "_decoder-build"


def _rotate_or_enqueue_watermark(
    *,
    handle: RotatingTraceHandleV0,
    queue: asyncio.Queue[Any],
    now_ns: int | None = None,
) -> dict[str, Any]:
    if getattr(handle, "_closed", False):
        return {"kind": "closed"}
    finalized = handle.rotate_if_nonempty(stop_reason="prospective_timed_rotation_v4")
    if finalized is not None:
        return {"kind": "chunk", "path": str(finalized)}
    watermark_ns = int(now_ns if now_ns is not None else time.time_ns())
    queue.put_nowait((WATERMARK_EVENT, watermark_ns))
    return {"kind": WATERMARK_EVENT, "wall_ns": watermark_ns}


async def _rotation_watermark_loop(
    handle: RotatingTraceHandleV0,
    *,
    queue: asyncio.Queue[Any],
    interval_seconds: float,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        await asyncio.sleep(interval_seconds)
        if stop_event.is_set() or getattr(handle, "_closed", False):
            break
        _rotate_or_enqueue_watermark(handle=handle, queue=queue)


async def run_live(
    *,
    contract_path: Path,
    artifacts_root: Path,
    duration_seconds: int,
    rotation_seconds: float,
    chunk_max_bytes: int,
    cargo: str,
    decoder_target_dir: Path,
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
        raise ValueError("Launch Burst route-paper contract hash changed; V4 refuses to proceed")
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
    queue: asyncio.Queue[Any] = asyncio.Queue()
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
    coverage_source_counts: Counter[str] = Counter()
    stop_rotation = asyncio.Event()

    provider_kwargs = {
        "jupiter_api_key": jupiter_api_key,
        "taker_public_key": taker_public_key,
        "rpc_url": rpc_url,
        "rpc_fallback_urls": rpc_fallback_urls,
    }

    async def dispatch_ready(*, coverage_through_wall_ns: int, coverage_source: str) -> None:
        coverage_source_counts[coverage_source] += 1
        for token_mint, snapshot in online.ready_snapshots(
            coverage_through_wall_ns=coverage_through_wall_ns
        ):
            episode_key = f"pump:{token_mint}:{snapshot['observed_t0_wall_ns']}"
            immediate, task = await _dispatch_snapshot(
                episode_key=episode_key,
                token_mint=token_mint,
                snapshot=snapshot,
                contract=contract,
                systems_only=systems_only,
                provider_factory=_capture_selected_episode,
                provider_kwargs=provider_kwargs,
            )
            if immediate is not None:
                if systems_only:
                    immediate["coverage_source"] = coverage_source
                    immediate["coverage_through_wall_ns"] = int(coverage_through_wall_ns)
                    systems_observations.append(immediate)
                else:
                    collection = immediate.setdefault("collection", {})
                    collection["coverage_source"] = coverage_source
                    collection["coverage_through_wall_ns"] = int(coverage_through_wall_ns)
                    episodes.append(immediate)
            if task is not None:
                provider_tasks.append(task)

    async def consume() -> None:
        while True:
            item = await queue.get()
            try:
                if item is None:
                    break
                if (
                    isinstance(item, tuple)
                    and len(item) == 2
                    and item[0] == WATERMARK_EVENT
                ):
                    await dispatch_ready(
                        coverage_through_wall_ns=int(item[1]),
                        coverage_source=WATERMARK_EVENT,
                    )
                    continue

                raw_path = Path(item)
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
                await dispatch_ready(
                    coverage_through_wall_ns=int(finalized_ns),
                    coverage_source="finalized_chunk",
                )
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
        _rotation_watermark_loop(
            handle,
            queue=queue,
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
        "watermark_scheduler_enabled": True,
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
        "type": "launch_burst_prospective_route_live_report_v4",
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
        "decoder_target_dir": str(decoder_target_dir.resolve()),
        "processing": processing,
        "systems": systems,
        "coverage_source_counts": dict(sorted(coverage_source_counts.items())),
        "gates": gates,
        "artifacts": {
            "report": str(report_path.resolve()),
            "input": None if systems_only else str(input_path.resolve()),
            "result": None if systems_only else str(result_path.resolve()),
        },
        "interpretation": (
            "V4 preserves the frozen V2 route-paper contract but decouples causal snapshot readiness from "
            "future market activity. A timed rotation emits a finalized chunk when payload exists, or an "
            "explicit local receive-time coverage watermark when the current chunk is empty. Queue ordering "
            "ensures all earlier finalized evidence is processed before a watermark can release a snapshot. "
            "Systems-only mode opens no Jupiter/RPC economic outcomes."
        ),
    }
    _write_json(report_path, report)
    if systems_only:
        _write_json(run_dir / "systems-observations.json", {"observations": systems_observations})
    return report


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Launch Burst prospective live V4 with causal idle watermarks and direct Carbon decoder"
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--duration-seconds", type=int, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--rotation-seconds", type=float, default=DEFAULT_ROTATION_SECONDS)
    parser.add_argument("--chunk-max-mib", type=int, default=DEFAULT_CHUNK_MAX_BYTES // (1024 * 1024))
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--decoder-target-dir", type=Path, default=None)
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
                decoder_target_dir=args.decoder_target_dir or _default_decoder_target(),
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
