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
from benchmarks.helius_standard_wss_shadow_v0.reduce import reduce_shadow
from benchmarks.launch_burst_prospective_route_paper_v2.run import run_route_paper_v2
from benchmarks.launch_burst_shadow_v0.run import (
    _envelope,
    _feature_snapshot,
    _first_anchor,
    _paired_rows,
    _text,
    _nonnegative_int,
)
from benchmarks.market_first_live_discovery_v0.rotating_trace import RotatingTraceHandleV0
from benchmarks.market_first_live_smoke_v0.run import _run_carbon_decoder
from src.assets import USDC_MINT
from src.carbon_matched_unit_adapter import adapt_carbon_pump_trade_v0
from src.jupiter_swap_v2 import JupiterOrderError, JupiterSwapV2Client, jupiter_order_to_causal_quote
from src.launch_burst_route_paper_v2 import selection_decision, validate_contract
from src.solana import SolanaClient, SolanaRPCError

LIVE_VERSION = "launch_burst_prospective_route_live_v2"
DEFAULT_DURATION_SECONDS = 900
DEFAULT_ROTATION_SECONDS = 1.0
DEFAULT_CHUNK_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_ARTIFACTS_ROOT = Path("artifacts") / LIVE_VERSION
DEFAULT_CONTRACT = (
    Path("benchmarks")
    / "launch_burst_prospective_economic_v1"
    / "pump_route_paper_contract_v2.frozen.json"
)
USDC_DECIMALS = 6


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


def _episode(*, episode_key: str, token_mint: str, snapshot: dict[str, Any], quotes: list[dict[str, Any]], collection: dict[str, Any]) -> dict[str, Any]:
    return {
        "episode_key": episode_key,
        "token_mint": token_mint,
        "venue": "pump",
        "feature_snapshot": snapshot,
        "quotes": quotes,
        "collection": collection,
    }


class OnlinePumpFeatureState:
    """Incremental Pump reconstruction using the exact frozen shadow feature implementation."""

    def __init__(self) -> None:
        self.anchors: dict[tuple[str, str], dict[str, Any]] = {}
        self.adapted: list[Any] = []
        self.seen_event_keys: set[str] = set()
        self.emitted: set[tuple[str, str]] = set()

    def ingest_processed_chunk(self, chunk_dir: Path) -> None:
        carbon = chunk_dir / "carbon-canonical.jsonl"
        manifest = chunk_dir / "target-manifest.jsonl"
        if not carbon.exists():
            return
        ordered, errors = _paired_rows(carbon, manifest)
        if errors:
            raise RuntimeError("prospective chunk pairing errors: " + ";".join(errors[:5]))
        for row, manifest_row in ordered:
            event_key = _text(row, "event_key") or ""
            if not event_key or event_key in self.seen_event_keys:
                continue
            self.seen_event_keys.add(event_key)
            if row.get("status") != "decoded":
                continue
            wall_ns = int(manifest_row["first_received_wall_ns"])
            event_type = _text(row, "event_type")
            if event_type == "pump_create":
                mint = _text(row, "mint")
                chain_t0 = _nonnegative_int(row, "timestamp")
                if mint is not None and chain_t0 is not None:
                    _first_anchor(
                        self.anchors,
                        token_mint=mint,
                        venue="pump",
                        chain_t0=chain_t0,
                        observed_wall_ns=wall_ns,
                        event_key=event_key,
                    )
                continue
            if event_type != "pump_trade":
                continue
            result = adapt_carbon_pump_trade_v0(row, observed_at=wall_ns // 1_000_000_000)
            env = _envelope(result, row, wall_ns)
            if env is not None:
                self.adapted.append(env)

    def ready_snapshots(self, *, coverage_through_wall_ns: int) -> list[tuple[str, dict[str, Any]]]:
        ready: list[tuple[str, dict[str, Any]]] = []
        for key, anchor in sorted(
            self.anchors.items(),
            key=lambda item: (int(item[1]["observed_wall_ns"]), item[0][0]),
        ):
            if key in self.emitted:
                continue
            cutoff_ns = int(anchor["observed_wall_ns"]) + 5_000_000_000
            if coverage_through_wall_ns < cutoff_ns:
                continue
            chain_end = int(anchor["chain_t0"]) + 5
            rows = [
                item
                for item in self.adapted
                if item.token_mint == anchor["token_mint"]
                and item.venue == "pump"
                and int(anchor["observed_wall_ns"]) <= item.observed_wall_ns <= cutoff_ns
                and int(anchor["chain_t0"]) <= item.chain_time <= chain_end
            ]
            observed_t0 = int(anchor["observed_wall_ns"]) // 1_000_000_000
            snapshot = {
                "stratum": "pump_launch",
                "complete": True,
                "observed_t0": observed_t0,
                "observed_t0_wall_ns": int(anchor["observed_wall_ns"]),
                "evidence_window_seconds": 5,
                "decision_as_of": observed_t0 + 5,
                "decision_cutoff_wall_ns": cutoff_ns,
                "features": _feature_snapshot(rows, anchor_wall_ns=int(anchor["observed_wall_ns"])),
            }
            self.emitted.add(key)
            ready.append((str(anchor["token_mint"]), snapshot))
        return ready

    def right_censored_snapshots(self) -> list[tuple[str, dict[str, Any]]]:
        output: list[tuple[str, dict[str, Any]]] = []
        for key, anchor in self.anchors.items():
            if key in self.emitted:
                continue
            observed_t0 = int(anchor["observed_wall_ns"]) // 1_000_000_000
            output.append(
                (
                    str(anchor["token_mint"]),
                    {
                        "stratum": "pump_launch",
                        "complete": False,
                        "observed_t0": observed_t0,
                        "observed_t0_wall_ns": int(anchor["observed_wall_ns"]),
                        "evidence_window_seconds": 5,
                        "decision_as_of": observed_t0 + 5,
                        "decision_cutoff_wall_ns": int(anchor["observed_wall_ns"]) + 5_000_000_000,
                        "features": {},
                    },
                )
            )
        return output


def _process_chunk(*, raw_path: Path, processed_root: Path, cargo: str) -> dict[str, Any]:
    chunk_dir = processed_root / raw_path.stem
    chunk_dir.mkdir(parents=True, exist_ok=False)
    carbon_input = chunk_dir / "carbon-input.jsonl"
    manifest = chunk_dir / "target-manifest.jsonl"
    carbon_output = chunk_dir / "carbon-canonical.jsonl"
    report_path = chunk_dir / "chunk-report.json"
    report: dict[str, Any] = {"chunk": raw_path.stem, "status": "STARTED"}
    try:
        reducer = reduce_shadow(
            trace_path=raw_path,
            carbon_input_path=carbon_input,
            manifest_path=manifest,
        )
        report["reducer"] = reducer
        accepted = int(reducer.get("accepted_success_target_events") or 0)
        if accepted == 0:
            report["status"] = "NO_TARGET_EVENTS"
        else:
            if not reducer.get("valid_for_carbon_decode"):
                raise RuntimeError("frozen reducer rejected prospective chunk")
            decoder = _run_carbon_decoder(
                cargo=cargo,
                carbon_input_path=carbon_input,
                carbon_output_path=carbon_output,
            )
            report["decoder"] = decoder
            if not decoder.get("footer_accounting_valid"):
                raise RuntimeError("Carbon event decoder accounting failed")
            report["status"] = "PROCESSED"
    except Exception as exc:
        report["status"] = "FAILED"
        report["error"] = f"{type(exc).__name__}:{exc}"
    _write_json(report_path, report)
    return report


def _resolve_decimals(token_mint: str, *, rpc_url: str, fallback_urls: tuple[str, ...]) -> int:
    result = SolanaClient(rpc_url=rpc_url, timeout=3, fallback_urls=fallback_urls).call(
        "getTokenSupply", [token_mint, {"commitment": "confirmed"}], max_attempts=1
    )
    value = result.get("value") if isinstance(result, dict) else None
    if not isinstance(value, dict) or value.get("decimals") is None:
        raise SolanaRPCError("getTokenSupply did not return token decimals")
    decimals = int(value["decimals"])
    if not 0 <= decimals <= 18:
        raise SolanaRPCError("token decimals outside supported range")
    return decimals


def _entry_ready_second(snapshot: dict[str, Any], contract: dict[str, Any]) -> int:
    ready_ns = int(snapshot["decision_cutoff_wall_ns"]) + int(contract["entry"]["latency_seconds"]) * 1_000_000_000
    return int((ready_ns + 999_999_999) // 1_000_000_000)


async def _capture_selected_episode(
    *,
    episode_key: str,
    token_mint: str,
    snapshot: dict[str, Any],
    contract: dict[str, Any],
    jupiter_api_key: str,
    taker_public_key: str,
    rpc_url: str,
    rpc_fallback_urls: tuple[str, ...],
) -> dict[str, Any]:
    quotes: list[dict[str, Any]] = []
    collection: dict[str, Any] = {
        "snapshot_frozen_wall_ns": time.time_ns(),
        "provider_calls_started": False,
        "entry_status": None,
        "exit_status": None,
    }
    admitted, reason = selection_decision(snapshot, contract)
    if not admitted:
        collection["entry_status"] = reason
        return _episode(episode_key=episode_key, token_mint=token_mint, snapshot=snapshot, quotes=quotes, collection=collection)

    entry_ready_at = _entry_ready_second(snapshot, contract)
    collection["entry_ready_at"] = entry_ready_at
    if time.time() < entry_ready_at:
        await asyncio.sleep(max(0.0, entry_ready_at - time.time()))
    deadline_at = entry_ready_at + int(contract["entry"]["max_quote_wait_seconds"])
    if time.time() > deadline_at:
        collection["entry_status"] = "ENTRY_WINDOW_MISSED_BY_PROCESSING"
        return _episode(episode_key=episode_key, token_mint=token_mint, snapshot=snapshot, quotes=quotes, collection=collection)

    collection["provider_calls_started"] = True
    collection["entry_provider_started_wall_ns"] = time.time_ns()
    try:
        decimals = await asyncio.to_thread(
            _resolve_decimals,
            token_mint,
            rpc_url=rpc_url,
            fallback_urls=rpc_fallback_urls,
        )
        amount_raw = int(round(float(contract["position"]["notional_usd"]) * (10**USDC_DECIMALS)))
        order = await asyncio.to_thread(
            JupiterSwapV2Client(api_key=jupiter_api_key, timeout=5).order,
            input_mint=USDC_MINT,
            output_mint=token_mint,
            amount_raw=amount_raw,
            taker=taker_public_key,
            slippage_bps=int(contract["costs"]["entry_adverse_slippage_bps"]),
        )
        buy = jupiter_order_to_causal_quote(order, token_mint=token_mint, side="buy", token_decimals=decimals)
        quotes.append(asdict(buy))
        collection["entry_status"] = "AVAILABLE_ASSEMBLED" if buy.executable else "ROUTE_ONLY_UNEXPECTED"
    except (JupiterOrderError, SolanaRPCError, ValueError, TypeError) as exc:
        collection["entry_status"] = f"ERROR:{type(exc).__name__}:{redact_secret(str(exc), jupiter_api_key)}"
        return _episode(episode_key=episode_key, token_mint=token_mint, snapshot=snapshot, quotes=quotes, collection=collection)

    if not buy.executable or not buy.output_amount_raw:
        return _episode(episode_key=episode_key, token_mint=token_mint, snapshot=snapshot, quotes=quotes, collection=collection)

    exit_target = int(buy.observed_at) + int(contract["exit"]["horizon_seconds"])
    collection["exit_target_at"] = exit_target
    if time.time() < exit_target:
        await asyncio.sleep(max(0.0, exit_target - time.time()))
    try:
        order = await asyncio.to_thread(
            JupiterSwapV2Client(api_key=jupiter_api_key, timeout=5).order,
            input_mint=token_mint,
            output_mint=USDC_MINT,
            amount_raw=int(buy.output_amount_raw),
            taker=None,
            slippage_bps=int(contract["costs"]["exit_adverse_slippage_bps"]),
        )
        sell = jupiter_order_to_causal_quote(order, token_mint=token_mint, side="sell", token_decimals=decimals)
        if sell.executable:
            raise ValueError("route-only SELL unexpectedly returned executable evidence")
        quotes.append(asdict(sell))
        collection["exit_status"] = "AVAILABLE_ROUTE_ONLY"
    except (JupiterOrderError, ValueError, TypeError) as exc:
        collection["exit_status"] = f"ERROR:{type(exc).__name__}:{redact_secret(str(exc), jupiter_api_key)}"

    return _episode(episode_key=episode_key, token_mint=token_mint, snapshot=snapshot, quotes=quotes, collection=collection)


async def _rotation_loop(handle: RotatingTraceHandleV0, *, interval_seconds: float, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await asyncio.sleep(interval_seconds)
        handle.rotate_if_nonempty(stop_reason="prospective_timed_rotation")


async def _collect(*, handle: RotatingTraceHandleV0, counters: Counters, api_key: str, duration_seconds: int) -> dict[str, Any]:
    started = time.monotonic()
    deadline = started + float(duration_seconds)
    websocket_url = helius_wss_url(api_key)
    stop_reason = "duration_elapsed"
    session = 0
    try:
        while time.monotonic() < deadline:
            session += 1
            try:
                stop_reason = await _run_session(
                    websocket_url=websocket_url,
                    handle=handle,
                    counters=counters,
                    session_number=session,
                    global_deadline=deadline,
                    max_log_notifications=0,
                    ack_timeout_seconds=20.0,
                )
                if stop_reason == "duration_elapsed":
                    break
            except (OSError, TimeoutError, RuntimeError, asyncio.TimeoutError):
                counters.transport_errors += 1
                if counters.reconnects >= 5 or time.monotonic() >= deadline:
                    stop_reason = "transport_error_reconnect_budget_exhausted"
                    break
                counters.reconnects += 1
                await asyncio.sleep(min(2.0, max(0.0, deadline - time.monotonic())))
    finally:
        handle.close(stop_reason=stop_reason)
    return {"stop_reason": stop_reason, "elapsed_seconds": max(0.0, time.monotonic() - started)}


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
) -> dict[str, Any]:
    contract = _read_json(contract_path)
    validate_contract(contract)
    if duration_seconds <= 0 or rotation_seconds <= 0 or chunk_max_bytes <= 0:
        raise ValueError("duration, rotation and chunk size must be positive")
    if not helius_api_key or not jupiter_api_key or not taker_public_key or not rpc_url:
        raise ValueError("HELIUS_API_KEY, JUPITER_API_KEY, JUPITER_TAKER_PUBLIC_KEY and SOLANA_RPC_URL are required")

    run_id = _run_id()
    run_dir = artifacts_root / run_id
    raw_dir = run_dir / "raw-chunks"
    processed_root = run_dir / "processed-chunks"
    input_path = run_dir / "route-input-v2.json"
    result_path = run_dir / "route-result-v2.json"
    report_path = run_dir / "report.json"
    raw_dir.mkdir(parents=True, exist_ok=False)
    processed_root.mkdir(parents=True, exist_ok=True)

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
                report = await asyncio.to_thread(
                    _process_chunk,
                    raw_path=raw_path,
                    processed_root=processed_root,
                    cargo=cargo,
                )
                chunk_reports.append(report)
                if report.get("status") == "FAILED":
                    processing_errors.append(str(report.get("error") or "chunk failed"))
                    continue
                online.ingest_processed_chunk(processed_root / raw_path.stem)
                for token_mint, snapshot in online.ready_snapshots(coverage_through_wall_ns=finalized_ns):
                    episode_key = f"pump:{token_mint}:{snapshot['observed_t0_wall_ns']}"
                    admitted, _ = selection_decision(snapshot, contract)
                    if not admitted:
                        episodes.append(
                            _episode(
                                episode_key=episode_key,
                                token_mint=token_mint,
                                snapshot=snapshot,
                                quotes=[],
                                collection={"snapshot_frozen_wall_ns": time.time_ns(), "provider_calls_started": False},
                            )
                        )
                    else:
                        provider_tasks.append(
                            asyncio.create_task(
                                _capture_selected_episode(
                                    episode_key=episode_key,
                                    token_mint=token_mint,
                                    snapshot=snapshot,
                                    contract=contract,
                                    jupiter_api_key=jupiter_api_key,
                                    taker_public_key=taker_public_key,
                                    rpc_url=rpc_url,
                                    rpc_fallback_urls=rpc_fallback_urls,
                                )
                            )
                        )
            finally:
                queue.task_done()

    collector_task = asyncio.create_task(
        _collect(handle=handle, counters=counters, api_key=helius_api_key, duration_seconds=duration_seconds)
    )
    consumer_task = asyncio.create_task(consume())
    rotation_task = asyncio.create_task(
        _rotation_loop(handle, interval_seconds=rotation_seconds, stop_event=stop_rotation)
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

    for token_mint, snapshot in online.right_censored_snapshots():
        episodes.append(
            _episode(
                episode_key=f"pump:{token_mint}:{snapshot['observed_t0_wall_ns']}",
                token_mint=token_mint,
                snapshot=snapshot,
                quotes=[],
                collection={"snapshot_frozen_wall_ns": time.time_ns(), "provider_calls_started": False, "right_censored": True},
            )
        )
    if provider_tasks:
        episodes.extend(await asyncio.gather(*provider_tasks))
    episodes.sort(key=lambda item: (int(item["feature_snapshot"]["observed_t0_wall_ns"]), item["token_mint"]))

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

    gates = {
        "contract_frozen_and_valid": True,
        "source_capture_started_after_contract_load": True,
        "duration_elapsed": acquisition.get("stop_reason") == "duration_elapsed",
        "transport_errors_zero": int(counters.transport_errors) == 0,
        "reconnects_zero": int(counters.reconnects) == 0,
        "processing_errors_zero": not processing_errors,
        "route_runner_pass": route_result.get("classification") == "PASS_LAUNCH_BURST_PROSPECTIVE_ROUTE_PAPER_V2",
    }
    report = {
        "type": "launch_burst_prospective_route_live_report_v2",
        "version": LIVE_VERSION,
        "classification": "PASS_LAUNCH_BURST_PROSPECTIVE_ROUTE_LIVE_V2" if all(gates.values()) else "FAIL_LAUNCH_BURST_PROSPECTIVE_ROUTE_LIVE_V2",
        "acquisition_run_key": run_id,
        "contract_hash_sha256": contract["contract_hash_sha256"],
        "capture": acquisition,
        "chunk_count": len(chunk_reports),
        "episode_count": len(episodes),
        "provider_task_count": len(provider_tasks),
        "processing_errors": processing_errors,
        "gates": gates,
        "artifacts": {
            "input": str(input_path.resolve()),
            "result": str(result_path.resolve()),
            "report": str(report_path.resolve()),
        },
        "interpretation": "Prospective route-paper evidence only. No transaction is signed or submitted; no landed fill or realized PnL is claimed.",
    }
    _write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Prospective Pump Launch Burst route-paper live collector v2")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--duration-seconds", type=int, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--rotation-seconds", type=float, default=DEFAULT_ROTATION_SECONDS)
    parser.add_argument("--chunk-max-mib", type=int, default=DEFAULT_CHUNK_MAX_BYTES // (1024 * 1024))
    parser.add_argument("--cargo", default="cargo")
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
            )
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": "FAIL_LAUNCH_BURST_PROSPECTIVE_ROUTE_LIVE_V2",
                    "error": f"{type(exc).__name__}:{exc}",
                },
                indent=2,
            )
        )
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["classification"] == "PASS_LAUNCH_BURST_PROSPECTIVE_ROUTE_LIVE_V2" else 2


if __name__ == "__main__":
    raise SystemExit(main())
