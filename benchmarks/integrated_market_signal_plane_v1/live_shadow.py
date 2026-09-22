from __future__ import annotations

import argparse
import asyncio
import base64
from collections import Counter
from dataclasses import asdict
import json
import math
import os
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
import subprocess
import time
from typing import Any

from benchmarks.carbon_decoder_parity_v1.parity import extract_contextual_target_payloads
from benchmarks.commodity_signal_plane_v0.benchmark import TraceRecord
from benchmarks.integrated_market_signal_plane_v1.indexed_kernel import IndexedWindowRadarState
from benchmarks.integrated_market_signal_plane_v1.rust_suite import _json_equivalent
from benchmarks.integrated_market_signal_plane_v1.suite import _trigger_snapshot
from benchmarks.market_first_live_discovery_v0.contracts import (
    identities_available_before_v0,
    load_bootstrap_evidence_v0,
    validate_bootstrap_before_discovery_start_v0,
)
from src.carbon_market_trade_adapter import adapt_carbon_matched_unit_to_market_trade_v0
from src.carbon_matched_unit_adapter import (
    ADAPTED,
    MISSING_CONTEXT,
    adapt_carbon_pump_trade_v0,
    adapt_carbon_pumpswap_trade_v0,
)
from src.config import settings
from src.market_opportunity_radar import MarketLifecycleObservation
from src.pump_bonding_stream import build_logs_subscribe_request as build_pump_subscribe
from src.pump_bonding_stream import rpc_http_to_ws_url
from src.pumpswap_pool_identity import PumpSwapPoolIdentityObservation
from src.pumpswap_stream import (
    PUMPSWAP_PROGRAM_ID,
    build_logs_subscribe_request as build_pumpswap_subscribe,
    decode_pumpswap_pool_account,
)
from src.solana import SolanaClient, SolanaRPCError
from src.signal_plane_episode_admission_v0 import (
    SIGNAL_PLANE_EPISODE_ADMISSION_VERSION,
    admit_signal_plane_trigger_snapshot,
)
from src.signal_plane_research_persistence_v0 import (
    SIGNAL_PLANE_RESEARCH_PERSISTENCE_VERSION,
    persist_signal_plane_research_record,
)


VERSION = "rust_signal_plane_live_shadow_v5_signal_batch"
PASS_CLASSIFICATION = "PASS_RUST_SIGNAL_PLANE_LIVE_SHADOW_V5_SIGNAL_BATCH"
FAIL_CLASSIFICATION = "FAIL_RUST_SIGNAL_PLANE_LIVE_SHADOW_V5_SIGNAL_BATCH"
INGRESS_QUEUE_SIZE = 8192
SURFACE_IDLE_TIMEOUT_SECONDS = 30.0
INGRESS_MICROBATCH_MAX_NOTIFICATIONS = 32
WS_OPEN_TIMEOUT_SECONDS = 30.0
WS_OPEN_BARRIER_TIMEOUT_SECONDS = 35.0
SUBSCRIPTION_ACK_TIMEOUT_SECONDS = 20.0
DEFAULT_DURATION_SECONDS = 120.0
DEFAULT_MAX_LOG_NOTIFICATIONS = 0

CARBON_MANIFEST = (
    Path("benchmarks")
    / "carbon_decoder_parity_v1"
    / "rust_runner"
    / "Cargo.toml"
)
RUST_SIGNAL_MANIFEST = (
    Path("benchmarks")
    / "integrated_market_signal_plane_v1"
    / "rust_runner"
    / "Cargo.toml"
)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * pct / 100.0
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return float(ordered[lo])
    weight = rank - lo
    return float(ordered[lo] * (1.0 - weight) + ordered[hi] * weight)


def _latency_summary_ns(values: list[int]) -> dict[str, float | int]:
    ms = [max(0, int(value)) / 1_000_000.0 for value in values]
    return {
        "count": len(ms),
        "p50_ms": _percentile(ms, 50.0),
        "p95_ms": _percentile(ms, 95.0),
        "p99_ms": _percentile(ms, 99.0),
        "max_ms": max(ms) if ms else 0.0,
    }


def _numeric_summary(values: list[int]) -> dict[str, float | int]:
    numbers = [int(value) for value in values]
    return {
        "count": len(numbers),
        "p50": _percentile(numbers, 50.0),
        "p95": _percentile(numbers, 95.0),
        "p99": _percentile(numbers, 99.0),
        "max": max(numbers) if numbers else 0,
    }


def _text(row: dict[str, Any], name: str) -> str | None:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _nonnegative_int(row: dict[str, Any], name: str) -> int | None:
    value = row.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _first_truncation_index(logs: list[Any]) -> int | None:
    for index, raw in enumerate(logs):
        if str(raw).strip() == "Log truncated":
            return index
    return None


def _endpoint_host(url: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(url).hostname or "<unknown>"


def _websockets_version() -> str:
    try:
        return package_version("websockets")
    except PackageNotFoundError:
        return "unknown"


class AsyncPumpSwapIdentityPlane:
    """Resolve unknown PumpSwap pools off the Signal Plane hot path.

    A resolution becomes usable only from the local RPC response time forward.
    The trade that caused the lookup remains MISSING and is never backfilled.
    """

    def __init__(
        self,
        *,
        identities_by_pool: dict[str, list[PumpSwapPoolIdentityObservation]],
        rpc_url: str,
        batch_size: int = 64,
        queue_size: int = 1024,
        timeout_seconds: int = 8,
        coalesce_seconds: float = 0.01,
    ):
        if batch_size <= 0 or batch_size > 100:
            raise ValueError("batch_size must be in 1..100")
        if queue_size <= 0:
            raise ValueError("queue_size must be positive")
        self.identities_by_pool = identities_by_pool
        if coalesce_seconds < 0:
            raise ValueError("coalesce_seconds cannot be negative")
        self.batch_size = batch_size
        self.coalesce_seconds = coalesce_seconds
        self.queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=queue_size)
        self.client = SolanaClient(
            rpc_url=rpc_url,
            timeout=timeout_seconds,
            fallback_urls=(),
        )
        self.attempted_pools: set[str] = set()
        self.first_unknown_wall_ns: dict[str, int] = {}
        self.rpc_batch_latency_ns: list[int] = []
        self.unknown_to_identity_ready_ns: list[int] = []
        self.counters: Counter[str] = Counter()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("identity plane already started")
        self._task = asyncio.create_task(self._run())

    def enqueue(
        self,
        pool: str,
        *,
        source_wall_ns: int | None = None,
    ) -> bool:
        normalized = str(pool).strip()
        if not normalized:
            return False
        if normalized in self.attempted_pools:
            self.counters["deduplicated"] += 1
            return False
        learned_from_wall_ns = (
            time.time_ns()
            if source_wall_ns is None
            else int(source_wall_ns)
        )
        if learned_from_wall_ns < 0:
            raise ValueError("source_wall_ns must be non-negative")
        self.attempted_pools.add(normalized)
        self.first_unknown_wall_ns[normalized] = learned_from_wall_ns
        try:
            self.queue.put_nowait(normalized)
        except asyncio.QueueFull:
            self.attempted_pools.discard(normalized)
            self.first_unknown_wall_ns.pop(normalized, None)
            self.counters["queue_full"] += 1
            return False
        self.counters["enqueued"] += 1
        self.counters["queue_high_water"] = max(
            self.counters["queue_high_water"],
            self.queue.qsize(),
        )
        return True

    def _resolve_batch_sync(
        self,
        pools: tuple[str, ...],
    ) -> tuple[list[PumpSwapPoolIdentityObservation], Counter[str]]:
        metrics: Counter[str] = Counter()
        metrics["requested_pools"] = len(pools)
        try:
            result = self.client.call(
                "getMultipleAccounts",
                [
                    list(pools),
                    {
                        "encoding": "base64",
                        "commitment": "confirmed",
                    },
                ],
                max_attempts=1,
            ) or {}
        except (SolanaRPCError, ValueError, TypeError) as exc:
            metrics["rpc_batch_failures"] += 1
            metrics[f"rpc_error_type:{type(exc).__name__}"] += 1
            return [], metrics

        context = result.get("context") if isinstance(result, dict) else None
        values = result.get("value") if isinstance(result, dict) else None
        if (
            not isinstance(context, dict)
            or not isinstance(values, list)
            or len(values) != len(pools)
        ):
            metrics["invalid_rpc_shape"] += 1
            return [], metrics

        slot = context.get("slot")
        if not isinstance(slot, int) or isinstance(slot, bool) or slot < 0:
            metrics["invalid_context_slot"] += 1
            return [], metrics

        learned_wall_ns = time.time_ns()
        identities: list[PumpSwapPoolIdentityObservation] = []
        for pool, account in zip(pools, values):
            if account is None:
                metrics["account_missing"] += 1
                continue
            if not isinstance(account, dict):
                metrics["invalid_account_shape"] += 1
                continue
            if account.get("owner") != PUMPSWAP_PROGRAM_ID:
                metrics["owner_mismatch"] += 1
                continue
            data = account.get("data")
            if (
                not isinstance(data, (list, tuple))
                or len(data) < 2
                or not isinstance(data[0], str)
                or str(data[1]) != "base64"
            ):
                metrics["invalid_account_data"] += 1
                continue
            try:
                raw = base64.b64decode(data[0], validate=True)
                decoded = decode_pumpswap_pool_account(raw)
            except Exception:
                metrics["decode_failed"] += 1
                continue

            identities.append(
                PumpSwapPoolIdentityObservation(
                    pool=pool,
                    base_mint=decoded.base_mint,
                    quote_mint=decoded.quote_mint,
                    observed_wall_ns=learned_wall_ns,
                    observed_slot=int(slot),
                    evidence_key=(
                        f"async_getMultipleAccounts:{slot}:{learned_wall_ns}:{pool}"
                    ),
                    source="async_solana_getMultipleAccounts_v0",
                )
            )
            metrics["resolved"] += 1
        return identities, metrics

    async def _run(self) -> None:
        while True:
            first = await self.queue.get()
            if first is None:
                self.queue.task_done()
                return

            batch = [first]
            if self.coalesce_seconds > 0:
                await asyncio.sleep(self.coalesce_seconds)
            else:
                await asyncio.sleep(0)
            while len(batch) < self.batch_size:
                try:
                    item = self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if item is None:
                    self.queue.task_done()
                    break
                batch.append(item)

            rpc_started_ns = time.perf_counter_ns()
            identities, metrics = await asyncio.to_thread(
                self._resolve_batch_sync,
                tuple(batch),
            )
            self.rpc_batch_latency_ns.append(
                time.perf_counter_ns() - rpc_started_ns
            )
            self.counters.update(metrics)
            for identity in identities:
                _add_identity(self.identities_by_pool, identity)
                first_unknown_wall_ns = self.first_unknown_wall_ns.get(
                    identity.pool
                )
                if first_unknown_wall_ns is not None:
                    self.unknown_to_identity_ready_ns.append(
                        max(
                            0,
                            identity.observed_wall_ns
                            - first_unknown_wall_ns,
                        )
                    )

            for _ in batch:
                self.queue.task_done()

    async def stop(self, *, drain_timeout_seconds: float = 5.0) -> None:
        if self._task is None:
            return
        try:
            await asyncio.wait_for(
                self.queue.join(),
                timeout=drain_timeout_seconds,
            )
        except asyncio.TimeoutError:
            self.counters["drain_timeout"] += 1
        try:
            self.queue.put_nowait(None)
        except asyncio.QueueFull:
            self._task.cancel()
        try:
            await asyncio.wait_for(self._task, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self._task.cancel()
        self._task = None

    def summary(self) -> dict[str, Any]:
        return {
            "rpc_host": self.client.rpc_host,
            "attempted_unique_pools": len(self.attempted_pools),
            "queue_depth_at_report": self.queue.qsize(),
            "counters": dict(sorted(self.counters.items())),
            "latency": {
                "rpc_batch": _latency_summary_ns(
                    self.rpc_batch_latency_ns
                ),
                "first_unknown_to_identity_ready": _latency_summary_ns(
                    self.unknown_to_identity_ready_ns
                ),
            },
            "causal_policy": (
                "unknown pool lookup is asynchronous; triggering trade remains MISSING; "
                "resolved identity is usable only for later events whose receive time is "
                ">= identity.observed_wall_ns"
            ),
        }


class JsonLineProcess:
    def __init__(self, command: list[str], *, ready_type: str):
        self.command = list(command)
        self.ready_type = ready_type
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
            stderr = self._stderr_tail()
            raise RuntimeError(
                f"process exited before ready: {self.command!r}; stderr={stderr}"
            )
        row = json.loads(line)
        if row.get("type") != self.ready_type:
            raise RuntimeError(
                f"unexpected process ready row for {self.command!r}: {row!r}"
            )
        return row

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("process is not started")
        self.process.stdin.write(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        )
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(
                f"process ended while awaiting response; stderr={self._stderr_tail()}"
            )
        row = json.loads(line)
        return row

    def send(self, payload: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("process is not started")
        self.process.stdin.write(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        )
        self.process.stdin.flush()

    def receive(self) -> dict[str, Any]:
        if self.process is None or self.process.stdout is None:
            raise RuntimeError("process is not started")
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError(
                f"process ended while awaiting response; stderr={self._stderr_tail()}"
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


def _carbon_command(cargo: str) -> list[str]:
    return [
        cargo,
        "run",
        "--release",
        "--quiet",
        "--manifest-path",
        str(CARBON_MANIFEST),
        "--bin",
        "stream_decode_batches",
    ]


def _rust_signal_command(cargo: str) -> list[str]:
    return [
        cargo,
        "run",
        "--release",
        "--quiet",
        "--manifest-path",
        str(RUST_SIGNAL_MANIFEST),
        "--bin",
        "stream",
    ]


def _identity_source_for_evidence(
    identities: tuple[PumpSwapPoolIdentityObservation, ...],
    evidence_key: str | None,
) -> str | None:
    if evidence_key is None:
        return None
    return next(
        (
            item.source
            for item in identities
            if item.evidence_key == evidence_key
        ),
        None,
    )


def _add_identity(
    by_pool: dict[str, list[PumpSwapPoolIdentityObservation]],
    identity: PumpSwapPoolIdentityObservation,
) -> None:
    bucket = by_pool.setdefault(identity.pool, [])
    key = (identity.observed_wall_ns, identity.observed_slot, identity.evidence_key)
    if any(
        (item.observed_wall_ns, item.observed_slot, item.evidence_key) == key
        for item in bucket
    ):
        return
    bucket.append(identity)
    bucket.sort(
        key=lambda item: (
            item.observed_wall_ns,
            item.observed_slot,
            item.evidence_key,
        )
    )


def _target_inputs_from_notification(
    *,
    normalized: dict[str, Any],
    received_wall_ns: int,
    seen_event_keys: set[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], int]:
    if normalized.get("err") is not None:
        return [], {}, 0
    signature = normalized.get("signature")
    slot = normalized.get("slot")
    logs = normalized.get("logs")
    if (
        not isinstance(signature, str)
        or not signature
        or not isinstance(slot, int)
        or isinstance(slot, bool)
        or not isinstance(logs, list)
    ):
        return [], {}, 0

    targets, stack_errors = extract_contextual_target_payloads(logs)
    first_truncation = _first_truncation_index(logs)
    items: list[dict[str, Any]] = []
    manifests: dict[str, dict[str, Any]] = {}

    for target in targets:
        log_index = int(target["log_index"])
        if first_truncation is not None and log_index >= first_truncation:
            continue
        event_type = str(target["event_type"])
        program_id = str(target["program_id"])
        event_key = f"{signature}:{log_index}:{event_type}"
        if event_key in seen_event_keys:
            continue
        seen_event_keys.add(event_key)
        payload = bytes(target["payload"])
        items.append(
            {
                "type": "carbon_decoder_input",
                "event_key": event_key,
                "signature": signature,
                "slot": slot,
                "log_index": log_index,
                "program_id": program_id,
                "event_type": event_type,
                "payload_base64": base64.b64encode(payload).decode("ascii"),
            }
        )
        manifests[event_key] = {
            "event_key": event_key,
            "first_received_wall_ns": received_wall_ns,
            "slot": slot,
            "signature": signature,
            "event_type": event_type,
        }
    return items, manifests, int(stack_errors)


def _take_ready_ingress_batch(
    queue: asyncio.Queue[dict[str, Any]],
    first: dict[str, Any],
    *,
    max_notifications: int,
) -> list[dict[str, Any]]:
    if max_notifications <= 0:
        raise ValueError("max_notifications must be positive")
    batch = [first]
    while len(batch) < max_notifications:
        try:
            batch.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break
    return batch


def _build_signal_record(
    *,
    sequence: int,
    kind: str,
    observation: Any,
    source_received_wall_ns: int,
    canonical_ready_wall_ns: int,
) -> dict[str, Any]:
    return {
        "type": "signal_record",
        "sequence": sequence,
        "kind": kind,
        "source_received_wall_ns": source_received_wall_ns,
        "canonical_ready_wall_ns": canonical_ready_wall_ns,
        "observation": asdict(observation),
    }


async def _surface_reader_v2(
    *,
    endpoint: str,
    label: str,
    request: dict[str, Any],
    ingress_queue: asyncio.Queue[dict[str, Any]],
    counters: Counter[str],
    opened_event: asyncio.Event,
    subscribe_event: asyncio.Event,
    ready_event: asyncio.Event,
    acquisition_event: asyncio.Event,
    deadline_ref: dict[str, float],
    transport_errors: list[str],
) -> None:
    """Own one WebSocket session and never run Carbon/Radar work in the reader."""
    from websockets.asyncio.client import connect

    subscription_id: int | None = None
    try:
        async with connect(
            endpoint,
            # Alchemy maintains liveness server-side. Disable the library's
            # client-originated keepalive Ping timeout; replies to server Ping
            # control frames remain automatic at the protocol layer.
            ping_interval=None,
            ping_timeout=None,
            open_timeout=WS_OPEN_TIMEOUT_SECONDS,
            close_timeout=5,
            max_size=16 * 1024 * 1024,
            max_queue=1024,
        ) as ws:
            counters[f"{label}_socket_opened"] += 1
            opened_event.set()
            await subscribe_event.wait()

            await ws.send(json.dumps(request, separators=(",", ":")))
            ack_deadline = time.monotonic() + SUBSCRIPTION_ACK_TIMEOUT_SECONDS

            while subscription_id is None:
                remaining = ack_deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"{label} subscription acknowledgement timeout")
                raw = await asyncio.wait_for(
                    ws.recv(),
                    timeout=remaining,
                )
                message = json.loads(raw)
                if message.get("id") != request.get("id"):
                    continue
                if message.get("error") is not None:
                    raise RuntimeError(
                        f"{label} subscription RPC error: {message['error']}"
                    )
                candidate = message.get("result")
                if not isinstance(candidate, int) or isinstance(candidate, bool):
                    raise RuntimeError(
                        f"{label} subscription acknowledgement missing integer id"
                    )
                subscription_id = candidate
                counters[f"{label}_ack"] += 1
                counters[f"{label}_sessions_active"] += 1
                ready_event.set()

            await acquisition_event.wait()
            deadline = float(deadline_ref["deadline"])
            counters[f"{label}_acquisition_started"] += 1

            last_application_message_at = time.monotonic()
            while time.monotonic() < deadline:
                remaining = min(1.0, max(0.0, deadline - time.monotonic()))
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    idle_for = time.monotonic() - last_application_message_at
                    if idle_for >= SURFACE_IDLE_TIMEOUT_SECONDS:
                        raise TimeoutError(
                            f"{label} application stream idle for "
                            f"{idle_for:.3f}s"
                        )
                    continue
                last_application_message_at = time.monotonic()
                received_wall_ns = time.time_ns()
                message = json.loads(raw)
                if not isinstance(message, dict):
                    counters[f"{label}_malformed_messages"] += 1
                    continue
                if message.get("method") != "logsNotification":
                    continue
                params = message.get("params")
                if not isinstance(params, dict):
                    counters[f"{label}_malformed_messages"] += 1
                    continue
                if params.get("subscription") != subscription_id:
                    counters[f"{label}_foreign_subscription_messages"] += 1
                    continue
                result = params.get("result")
                if not isinstance(result, dict):
                    counters[f"{label}_malformed_messages"] += 1
                    continue
                context = result.get("context")
                value = result.get("value")
                if not isinstance(context, dict) or not isinstance(value, dict):
                    counters[f"{label}_malformed_messages"] += 1
                    continue
                slot = context.get("slot")
                signature = value.get("signature")
                logs = value.get("logs")
                if (
                    not isinstance(slot, int)
                    or isinstance(slot, bool)
                    or not isinstance(signature, str)
                    or not signature
                    or not isinstance(logs, list)
                ):
                    counters[f"{label}_malformed_messages"] += 1
                    continue

                normalized = {
                    "subscription_label": label,
                    "slot": slot,
                    "signature": signature,
                    "err": value.get("err"),
                    "logs": logs,
                }
                counters[f"{label}_notifications"] += 1
                item = {
                    "label": label,
                    "received_wall_ns": received_wall_ns,
                    "normalized": normalized,
                }
                try:
                    ingress_queue.put_nowait(item)
                except asyncio.QueueFull:
                    counters[f"{label}_ingress_drops"] += 1
                    continue
                counters[f"{label}_ingress_enqueued"] += 1
                counters["ingress_queue_high_water"] = max(
                    counters["ingress_queue_high_water"],
                    ingress_queue.qsize(),
                )

            counters[f"{label}_reader_duration_elapsed"] += 1
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        transport_errors.append(
            f"{label}:{type(exc).__name__}:{exc}"
        )
    finally:
        if not opened_event.is_set():
            opened_event.set()
        if not ready_event.is_set():
            ready_event.set()
        counters[f"{label}_reader_stopped"] += 1


async def run_live_shadow_v0(
    *,
    bootstrap_report: Path,
    duration_seconds: float,
    max_log_notifications: int,
    cargo: str,
    output: Path,
    episode_bridge_run_key: str | None = None,
    research_plane_run_key: str | None = None,
) -> dict[str, Any]:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if max_log_notifications < 0:
        raise ValueError("max_log_notifications cannot be negative")
    bridge_run_key = (
        str(episode_bridge_run_key).strip()
        if episode_bridge_run_key is not None
        else ""
    )
    if episode_bridge_run_key is not None and not bridge_run_key:
        raise ValueError("episode_bridge_run_key cannot be blank")
    research_run_key = (
        str(research_plane_run_key).strip()
        if research_plane_run_key is not None
        else ""
    )
    if research_plane_run_key is not None and not research_run_key:
        raise ValueError("research_plane_run_key cannot be blank")
    if bridge_run_key and research_run_key:
        raise ValueError(
            "episode_bridge_run_key and research_plane_run_key are mutually exclusive"
        )

    bootstrap = load_bootstrap_evidence_v0(Path(bootstrap_report))
    endpoint = rpc_http_to_ws_url(settings.rpc_url)
    endpoint_host = _endpoint_host(endpoint)
    start_wall_ns: int | None = None

    identities_by_pool: dict[str, list[PumpSwapPoolIdentityObservation]] = {}
    for identity in bootstrap.identities:
        _add_identity(identities_by_pool, identity)

    carbon = JsonLineProcess(
        _carbon_command(cargo),
        ready_type="carbon_stream_decoder_ready",
    )
    rust = JsonLineProcess(
        _rust_signal_command(cargo),
        ready_type="rust_signal_stream_ready",
    )
    carbon_ready = carbon.start()
    rust_ready = rust.start()

    identity_plane = AsyncPumpSwapIdentityPlane(
        identities_by_pool=identities_by_pool,
        rpc_url=settings.rpc_url,
    )
    identity_plane.start()

    seen_event_keys: set[str] = set()
    counters: Counter[str] = Counter()
    matched_statuses: Counter[str] = Counter()
    market_trade_statuses: Counter[str] = Counter()
    mismatches: list[dict[str, Any]] = []
    errors: list[str] = []
    python_audit_service_ns: list[int] = []
    rust_service_ns: list[int] = []
    rust_source_to_signal_ns: list[int] = []
    rust_canonical_to_signal_ns: list[int] = []
    rust_dispatch_to_signal_ns: list[int] = []
    rust_batch_roundtrip_ns: list[int] = []
    rust_batch_service_ns: list[int] = []
    rust_signal_batch_sizes: list[int] = []
    parity_audit_records: list[tuple[TraceRecord, Any, str, str]] = []
    ingress_queue_wait_ns: list[int] = []
    pump_ingress_queue_wait_ns: list[int] = []
    pumpswap_ingress_queue_wait_ns: list[int] = []
    target_extract_service_ns: list[int] = []
    carbon_roundtrip_ns: list[int] = []
    ingress_microbatch_sizes: list[int] = []
    carbon_batch_event_sizes: list[int] = []
    signal_sequence = 0
    batch_id = 0
    signal_batch_id = 0
    log_notifications = 0
    pumpswap_pools_seen: set[str] = set()
    pumpswap_pools_adapted: set[str] = set()
    pumpswap_pools_missing: set[str] = set()
    live_create_pool_seen_at: dict[str, int] = {}
    pumpswap_identity_sources: Counter[str] = Counter()

    episode_bridge_queue: asyncio.Queue[tuple[dict, Any] | None] | None = (
        asyncio.Queue(maxsize=1024)
        if bridge_run_key
        else None
    )
    episode_bridge_task: asyncio.Task[None] | None = None
    research_plane_queue: asyncio.Queue[
        tuple[TraceRecord, dict | None] | None
    ] | None = (
        asyncio.Queue(maxsize=4096)
        if research_run_key
        else None
    )
    research_plane_task: asyncio.Task[None] | None = None

    ingress_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
        maxsize=INGRESS_QUEUE_SIZE
    )
    transport_errors: list[str] = []
    pump_opened = asyncio.Event()
    pumpswap_opened = asyncio.Event()
    subscribe_event = asyncio.Event()
    pump_ready = asyncio.Event()
    pumpswap_ready = asyncio.Event()
    acquisition_event = asyncio.Event()
    deadline_ref: dict[str, float] = {}
    reader_tasks: list[asyncio.Task[None]] = []
    ingress_drained_monotonic: float | None = None
    deadline: float | None = None
    startup_started_monotonic = time.monotonic()
    open_barrier_ms = 0.0
    subscription_barrier_ms = 0.0
    pre_acquisition_queue_depth = 0

    async def episode_bridge_worker() -> None:
        assert episode_bridge_queue is not None
        while True:
            item = await episode_bridge_queue.get()
            try:
                if item is None:
                    return
                trigger_snapshot, observation = item
                result = await asyncio.to_thread(
                    admit_signal_plane_trigger_snapshot,
                    acquisition_run_key=bridge_run_key,
                    trigger_snapshot=trigger_snapshot,
                    observation=observation,
                )
                counters["episode_bridge_completed"] += 1
                if result is None:
                    counters["episode_bridge_none"] += 1
                elif result.admitted:
                    counters["episode_bridge_new_admissions"] += 1
                else:
                    counters["episode_bridge_replays"] += 1
            except Exception as exc:
                counters["episode_bridge_errors"] += 1
                errors.append(
                    f"episode_bridge:{type(exc).__name__}:{exc}"
                )
            finally:
                episode_bridge_queue.task_done()

    if episode_bridge_queue is not None:
        episode_bridge_task = asyncio.create_task(
            episode_bridge_worker(),
            name="signal-plane-episode-bridge-v0",
        )

    async def research_plane_worker() -> None:
        assert research_plane_queue is not None
        expected_sequence = 0
        while True:
            item = await research_plane_queue.get()
            try:
                if item is None:
                    return
                trace_record, trigger_snapshot = item
                if trace_record.sequence != expected_sequence:
                    raise RuntimeError(
                        "research plane sequence mismatch: "
                        f"expected={expected_sequence} actual={trace_record.sequence}"
                    )
                result = await asyncio.to_thread(
                    persist_signal_plane_research_record,
                    acquisition_run_key=research_run_key,
                    record=trace_record,
                    trigger_snapshot=trigger_snapshot,
                )
                counters["research_plane_completed"] += 1
                if result.observation_inserted:
                    counters["research_plane_observations_inserted"] += 1
                else:
                    counters["research_plane_observation_replays"] += 1
                if trace_record.kind == "trade":
                    counters["research_plane_trades_completed"] += 1
                else:
                    counters["research_plane_lifecycles_completed"] += 1
                if result.episode is not None:
                    counters["research_plane_trigger_episodes"] += 1
                    if result.episode.admitted:
                        counters["research_plane_new_admissions"] += 1
                    else:
                        counters["research_plane_admission_replays"] += 1
                expected_sequence += 1
            except Exception as exc:
                counters["research_plane_errors"] += 1
                errors.append(
                    f"research_plane:{type(exc).__name__}:{exc}"
                )
                expected_sequence += 1
            finally:
                research_plane_queue.task_done()

    if research_plane_queue is not None:
        research_plane_task = asyncio.create_task(
            research_plane_worker(),
            name="signal-plane-research-persistence-v0",
        )

    try:
        reader_tasks = [
            asyncio.create_task(
                _surface_reader_v2(
                    endpoint=endpoint,
                    label="pump_logs",
                    request=build_pump_subscribe(
                        request_id=1,
                        commitment="confirmed",
                    ),
                    ingress_queue=ingress_queue,
                    counters=counters,
                    opened_event=pump_opened,
                    subscribe_event=subscribe_event,
                    ready_event=pump_ready,
                    acquisition_event=acquisition_event,
                    deadline_ref=deadline_ref,
                    transport_errors=transport_errors,
                ),
                name="pump-live-reader-v2",
            ),
            asyncio.create_task(
                _surface_reader_v2(
                    endpoint=endpoint,
                    label="pumpswap_logs",
                    request=build_pumpswap_subscribe(
                        request_id=2,
                        commitment="confirmed",
                    ),
                    ingress_queue=ingress_queue,
                    counters=counters,
                    opened_event=pumpswap_opened,
                    subscribe_event=subscribe_event,
                    ready_event=pumpswap_ready,
                    acquisition_event=acquisition_event,
                    deadline_ref=deadline_ref,
                    transport_errors=transport_errors,
                ),
                name="pumpswap-live-reader-v2",
            ),
        ]

        await asyncio.wait_for(
            asyncio.gather(
                pump_opened.wait(),
                pumpswap_opened.wait(),
            ),
            timeout=WS_OPEN_BARRIER_TIMEOUT_SECONDS,
        )
        if (
            counters["pump_logs_socket_opened"] != 1
            or counters["pumpswap_logs_socket_opened"] != 1
        ):
            raise RuntimeError(
                "transport opening incomplete: "
                + " | ".join(transport_errors or ["missing socket open"])
            )
        counters["transport_open_barrier_passed"] += 1
        open_barrier_ms = (
            time.monotonic() - startup_started_monotonic
        ) * 1000.0

        subscribe_event.set()

        await asyncio.wait_for(
            asyncio.gather(
                pump_ready.wait(),
                pumpswap_ready.wait(),
            ),
            timeout=SUBSCRIPTION_ACK_TIMEOUT_SECONDS + 2.0,
        )
        if (
            counters["pump_logs_ack"] != 1
            or counters["pumpswap_logs_ack"] != 1
        ):
            raise RuntimeError(
                "transport subscription incomplete: "
                + " | ".join(transport_errors or ["missing subscription ACK"])
            )

        subscription_barrier_ms = (
            time.monotonic() - startup_started_monotonic
        ) * 1000.0
        pre_acquisition_queue_depth = ingress_queue.qsize()
        if pre_acquisition_queue_depth != 0:
            raise RuntimeError(
                "pre-acquisition ingress queue is not empty: "
                f"{pre_acquisition_queue_depth}"
            )

        start_wall_ns = time.time_ns()
        validate_bootstrap_before_discovery_start_v0(
            bootstrap,
            discovery_start_wall_ns=start_wall_ns,
        )
        source_started_monotonic = time.monotonic()
        deadline = source_started_monotonic + duration_seconds
        deadline_ref["deadline"] = deadline
        counters["sessions_active"] = 2
        counters["transport_subscription_barrier_passed"] += 1
        acquisition_event.set()

        while True:
            source_open = time.monotonic() < deadline
            readers_done = all(task.done() for task in reader_tasks)
            if (
                max_log_notifications > 0
                and log_notifications >= max_log_notifications
            ):
                break
            if not source_open and ingress_queue.empty():
                if ingress_drained_monotonic is None:
                    ingress_drained_monotonic = time.monotonic()
                if readers_done:
                    break

            wait_seconds = (
                min(1.0, max(0.001, deadline - time.monotonic()))
                if source_open
                else 0.1
            )
            try:
                first_ingress = await asyncio.wait_for(
                    ingress_queue.get(),
                    timeout=wait_seconds,
                )
            except asyncio.TimeoutError:
                if (
                    time.monotonic() >= deadline
                    and ingress_queue.empty()
                    and ingress_drained_monotonic is None
                ):
                    ingress_drained_monotonic = time.monotonic()
                continue

            microbatch_limit = INGRESS_MICROBATCH_MAX_NOTIFICATIONS
            if max_log_notifications > 0:
                microbatch_limit = min(
                    microbatch_limit,
                    max(1, max_log_notifications - log_notifications),
                )
            ingress_batch = _take_ready_ingress_batch(
                ingress_queue,
                first_ingress,
                max_notifications=microbatch_limit,
            )
            batch_dequeued_wall_ns = time.time_ns()
            log_notifications += len(ingress_batch)
            ingress_microbatch_sizes.append(len(ingress_batch))
            counters["consumer_microbatches"] += 1
            counters["consumer_microbatch_notifications"] += len(ingress_batch)
            counters["consumer_microbatch_max_observed"] = max(
                counters["consumer_microbatch_max_observed"],
                len(ingress_batch),
            )

            items: list[dict[str, Any]] = []
            manifests: dict[str, dict[str, Any]] = {}
            batch_stack_errors = 0
            batch_target_notifications = 0

            for ingress in ingress_batch:
                normalized = dict(ingress["normalized"])
                label = str(ingress["label"])
                received_wall_ns = int(ingress["received_wall_ns"])
                queue_wait_ns = max(
                    0,
                    batch_dequeued_wall_ns - received_wall_ns,
                )
                ingress_queue_wait_ns.append(queue_wait_ns)
                if label == "pump_logs":
                    pump_ingress_queue_wait_ns.append(queue_wait_ns)
                elif label == "pumpswap_logs":
                    pumpswap_ingress_queue_wait_ns.append(queue_wait_ns)
                counters["consumer_notifications"] += 1

                target_extract_started_ns = time.perf_counter_ns()
                notification_items, notification_manifests, stack_errors = (
                    _target_inputs_from_notification(
                        normalized=normalized,
                        received_wall_ns=received_wall_ns,
                        seen_event_keys=seen_event_keys,
                    )
                )
                target_extract_service_ns.append(
                    time.perf_counter_ns() - target_extract_started_ns
                )
                batch_stack_errors += stack_errors
                if notification_items:
                    batch_target_notifications += 1
                    items.extend(notification_items)
                    manifests.update(notification_manifests)

            counters["stack_errors"] += batch_stack_errors
            counters["target_events"] += len(items)
            counters["consumer_target_notifications"] += batch_target_notifications

            if not items:
                for _ in ingress_batch:
                    ingress_queue.task_done()
                if (
                    time.monotonic() >= deadline
                    and ingress_queue.empty()
                    and ingress_drained_monotonic is None
                ):
                    ingress_drained_monotonic = time.monotonic()
                continue

            carbon_batch_event_sizes.append(len(items))
            counters["carbon_microbatches"] += 1
            counters["carbon_microbatch_events"] += len(items)
            counters["carbon_microbatch_max_events"] = max(
                counters["carbon_microbatch_max_events"],
                len(items),
            )

            batch_id += 1
            carbon_started_ns = time.perf_counter_ns()
            decoder_row = await asyncio.to_thread(
                carbon.request,
                {
                    "type": "carbon_decoder_batch",
                    "batch_id": batch_id,
                    "items": items,
                },
            )
            carbon_roundtrip_ns.append(
                time.perf_counter_ns() - carbon_started_ns
            )
            if (
                decoder_row.get("type") != "carbon_canonical_batch"
                or decoder_row.get("batch_id") != batch_id
            ):
                raise RuntimeError(
                    f"unexpected Carbon stream response: {decoder_row!r}"
                )
            canonical_ready_wall_ns = time.time_ns()
            canonical_items = decoder_row.get("items")
            if not isinstance(canonical_items, list):
                raise RuntimeError("Carbon canonical batch missing items")

            signal_entries: list[
                tuple[
                    dict[str, Any],
                    TraceRecord,
                    str,
                    str,
                    int,
                    int,
                ]
            ] = []

            for row in canonical_items:
                if not isinstance(row, dict):
                    counters["decode_failures"] += 1
                    continue
                event_key = _text(row, "event_key")
                manifest = manifests.get(event_key or "")
                if manifest is None:
                    errors.append(f"canonical_missing_manifest:{event_key}")
                    continue
                source_wall_ns = int(manifest["first_received_wall_ns"])
                observed_at = source_wall_ns // 1_000_000_000
                if row.get("status") != "decoded":
                    counters["decode_failures"] += 1
                    continue
                counters["decoded_events"] += 1
                event_type = _text(row, "event_type")

                observation: Any | None = None
                kind: str | None = None

                if event_type == "pump_create":
                    mint = _text(row, "mint")
                    chain_time = _nonnegative_int(row, "timestamp")
                    if mint is None or chain_time is None:
                        errors.append(f"invalid_pump_create:{event_key}")
                        continue
                    observation = MarketLifecycleObservation(
                        token_mint=mint,
                        market_started_at=chain_time,
                        observed_at=observed_at,
                        venue="pump",
                    )
                    kind = "lifecycle"
                    counters["pump_lifecycle"] += 1

                elif event_type == "pumpswap_create_pool":
                    pool = _text(row, "pool")
                    base_mint = _text(row, "base_mint")
                    quote_mint = _text(row, "quote_mint")
                    chain_time = _nonnegative_int(row, "timestamp")
                    row_slot = _nonnegative_int(row, "slot")
                    if None in (pool, base_mint, quote_mint, chain_time, row_slot):
                        errors.append(f"invalid_pumpswap_create_pool:{event_key}")
                        continue
                    identity = PumpSwapPoolIdentityObservation(
                        pool=str(pool),
                        base_mint=str(base_mint),
                        quote_mint=str(quote_mint),
                        observed_wall_ns=source_wall_ns,
                        observed_slot=int(row_slot),
                        evidence_key=str(event_key),
                        source="carbon_pumpswap_create_pool_event_v0",
                    )
                    _add_identity(identities_by_pool, identity)
                    live_create_pool_seen_at[str(pool)] = source_wall_ns
                    observation = MarketLifecycleObservation(
                        token_mint=str(base_mint),
                        market_started_at=int(chain_time),
                        observed_at=observed_at,
                        venue="pumpswap",
                    )
                    kind = "lifecycle"
                    counters["pumpswap_lifecycle"] += 1

                elif event_type == "pump_trade":
                    matched = adapt_carbon_pump_trade_v0(
                        row,
                        observed_at=observed_at,
                    )
                    matched_statuses[matched.status] += 1
                    market_trade = adapt_carbon_matched_unit_to_market_trade_v0(
                        row,
                        matched,
                    )
                    market_trade_statuses[market_trade.status] += 1
                    if market_trade.status != ADAPTED or market_trade.observation is None:
                        continue
                    observation = market_trade.observation
                    kind = "trade"
                    counters["pump_adapted_trades"] += 1

                elif event_type in {"pumpswap_buy", "pumpswap_sell"}:
                    pool = _text(row, "pool")
                    if pool is not None:
                        pumpswap_pools_seen.add(pool)
                    causal_identities = (
                        identities_available_before_v0(
                            identities_by_pool.get(pool or "", ()),
                            pool=pool or "",
                            event_wall_ns=source_wall_ns,
                        )
                        if pool is not None
                        else ()
                    )
                    matched = adapt_carbon_pumpswap_trade_v0(
                        row,
                        observed_at=observed_at,
                        observed_wall_ns=source_wall_ns,
                        pool_observations=(),
                        pool_identity_observations=causal_identities,
                    )
                    matched_statuses[matched.status] += 1
                    if matched.status == MISSING_CONTEXT:
                        counters["pumpswap_missing_context"] += 1
                        if pool is not None:
                            pumpswap_pools_missing.add(pool)
                            live_create_at = live_create_pool_seen_at.get(pool)
                            if (
                                live_create_at is not None
                                and live_create_at <= source_wall_ns
                            ):
                                counters[
                                    "pumpswap_missing_after_causal_live_create_pool"
                                ] += 1
                            else:
                                counters[
                                    "pumpswap_missing_without_causal_live_create_pool"
                                ] += 1
                            if identity_plane.enqueue(
                                pool,
                                source_wall_ns=source_wall_ns,
                            ):
                                counters[
                                    "pumpswap_identity_async_lookup_enqueued"
                                ] += 1
                    market_trade = adapt_carbon_matched_unit_to_market_trade_v0(
                        row,
                        matched,
                    )
                    market_trade_statuses[market_trade.status] += 1
                    if market_trade.status != ADAPTED or market_trade.observation is None:
                        continue
                    observation = market_trade.observation
                    kind = "trade"
                    counters["pumpswap_adapted_trades"] += 1
                    if pool is not None:
                        pumpswap_pools_adapted.add(pool)
                    identity_evidence_key = (
                        matched.provenance_keys[1]
                        if len(matched.provenance_keys) >= 2
                        else None
                    )
                    identity_source = _identity_source_for_evidence(
                        causal_identities,
                        identity_evidence_key,
                    )
                    pumpswap_identity_sources[
                        identity_source or "UNKNOWN"
                    ] += 1
                else:
                    continue

                assert observation is not None and kind is not None
                sequence = signal_sequence
                signal_record = _build_signal_record(
                    sequence=sequence,
                    kind=kind,
                    observation=observation,
                    source_received_wall_ns=source_wall_ns,
                    canonical_ready_wall_ns=canonical_ready_wall_ns,
                )
                trace_record = TraceRecord(
                    sequence=sequence,
                    arrival_offset_ns=max(
                        0,
                        source_wall_ns - int(start_wall_ns or source_wall_ns),
                    ),
                    kind=kind,
                    event_key=str(event_key),
                    source_provider=f"shadow:{endpoint_host}",
                    trade=(observation if kind == "trade" else None),
                    lifecycle=(observation if kind == "lifecycle" else None),
                )
                signal_entries.append(
                    (
                        signal_record,
                        trace_record,
                        str(event_key),
                        kind,
                        source_wall_ns,
                        canonical_ready_wall_ns,
                    )
                )
                signal_sequence += 1

            if signal_entries:
                signal_batch_id += 1
                rust_signal_batch_sizes.append(len(signal_entries))
                counters["rust_signal_batches"] += 1
                counters["rust_signal_batch_records"] += len(signal_entries)
                counters["rust_signal_batch_max_records"] = max(
                    counters["rust_signal_batch_max_records"],
                    len(signal_entries),
                )

                rust_dispatch_wall_ns = time.time_ns()
                rust_batch_started_ns = time.perf_counter_ns()
                rust_batch_row = await asyncio.to_thread(
                    rust.request,
                    {
                        "type": "signal_batch",
                        "batch_id": signal_batch_id,
                        "records": [
                            entry[0]
                            for entry in signal_entries
                        ],
                    },
                )
                rust_batch_response_wall_ns = time.time_ns()
                rust_batch_roundtrip_ns.append(
                    time.perf_counter_ns() - rust_batch_started_ns
                )

                if rust_batch_row.get("type") == "signal_error":
                    raise RuntimeError(
                        f"rust_signal_batch_error:{rust_batch_row.get('error')}"
                    )
                if (
                    rust_batch_row.get("type") != "signal_batch_result"
                    or int(rust_batch_row.get("batch_id", -1)) != signal_batch_id
                ):
                    raise RuntimeError(
                        f"unexpected Rust signal batch response: {rust_batch_row!r}"
                    )
                rust_results = rust_batch_row.get("results")
                if (
                    not isinstance(rust_results, list)
                    or len(rust_results) != len(signal_entries)
                ):
                    raise RuntimeError(
                        "Rust signal batch result count mismatch: "
                        f"expected={len(signal_entries)} "
                        f"actual={len(rust_results) if isinstance(rust_results, list) else 'invalid'}"
                    )
                rust_batch_service_ns.append(
                    int(rust_batch_row.get("batch_service_ns", 0))
                )

                for entry, rust_row in zip(signal_entries, rust_results):
                    (
                        _signal_record,
                        trace_record,
                        event_key,
                        kind,
                        source_wall_ns,
                        canonical_ready_wall_ns,
                    ) = entry
                    sequence = trace_record.sequence
                    if (
                        not isinstance(rust_row, dict)
                        or rust_row.get("type") != "signal_result"
                        or int(rust_row.get("sequence", -1)) != sequence
                    ):
                        raise RuntimeError(
                            f"rust_sequence_or_type_mismatch:{sequence}:{rust_row!r}"
                        )

                    rust_snapshot = rust_row.get("trigger")
                    counters["signal_records"] += 1
                    if kind == "trade":
                        counters["trade_decision_points"] += 1

                    rust_service_elapsed_ns = int(rust_row["service_ns"])
                    rust_service_ns.append(rust_service_elapsed_ns)
                    rust_source_to_signal_ns.append(
                        max(
                            0,
                            rust_batch_response_wall_ns - source_wall_ns,
                        )
                    )
                    rust_canonical_to_signal_ns.append(
                        max(
                            0,
                            rust_batch_response_wall_ns
                            - canonical_ready_wall_ns,
                        )
                    )
                    rust_dispatch_to_signal_ns.append(
                        max(
                            0,
                            rust_batch_response_wall_ns
                            - rust_dispatch_wall_ns,
                        )
                    )
                    parity_audit_records.append(
                        (
                            trace_record,
                            rust_snapshot,
                            event_key,
                            kind,
                        )
                    )

                    if research_plane_queue is not None:
                        counters["research_plane_attempted"] += 1
                        try:
                            research_plane_queue.put_nowait(
                                (trace_record, rust_snapshot)
                            )
                            counters["research_plane_enqueued"] += 1
                            counters["research_plane_queue_high_water"] = max(
                                counters["research_plane_queue_high_water"],
                                research_plane_queue.qsize(),
                            )
                        except asyncio.QueueFull:
                            counters["research_plane_queue_overflow"] += 1
                            errors.append(
                                "research_plane:QueueFull:bounded persistence overflow"
                            )

                    if (
                        episode_bridge_queue is not None
                        and kind == "trade"
                        and rust_snapshot is not None
                        and trace_record.trade is not None
                    ):
                        counters["episode_bridge_trigger_snapshots"] += 1
                        try:
                            episode_bridge_queue.put_nowait(
                                (rust_snapshot, trace_record.trade)
                            )
                        except asyncio.QueueFull:
                            counters["episode_bridge_queue_overflow"] += 1
                            errors.append(
                                "episode_bridge:QueueFull:bounded admission overflow"
                            )

            for _ in ingress_batch:
                ingress_queue.task_done()
            if (
                time.monotonic() >= deadline
                and ingress_queue.empty()
                and ingress_drained_monotonic is None
            ):
                ingress_drained_monotonic = time.monotonic()

    except Exception as exc:
        errors.append(f"fatal:{type(exc).__name__}:{exc}")
    finally:
        for task in reader_tasks:
            if not task.done():
                task.cancel()
        if reader_tasks:
            await asyncio.gather(*reader_tasks, return_exceptions=True)
        try:
            await identity_plane.stop()
        except Exception as exc:
            errors.append(
                f"identity_plane_stop:{type(exc).__name__}:{exc}"
            )
        if episode_bridge_queue is not None:
            try:
                await asyncio.wait_for(
                    episode_bridge_queue.join(),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                counters["episode_bridge_drain_timeout"] += 1
                errors.append("episode_bridge:TimeoutError:drain")
            if episode_bridge_task is not None:
                try:
                    episode_bridge_queue.put_nowait(None)
                    await asyncio.wait_for(
                        episode_bridge_task,
                        timeout=5.0,
                    )
                except Exception as exc:
                    episode_bridge_task.cancel()
                    errors.append(
                        f"episode_bridge_stop:{type(exc).__name__}:{exc}"
                    )
        if research_plane_queue is not None:
            try:
                await asyncio.wait_for(
                    research_plane_queue.join(),
                    timeout=60.0,
                )
            except asyncio.TimeoutError:
                counters["research_plane_drain_timeout"] += 1
                errors.append("research_plane:TimeoutError:drain")
            if research_plane_task is not None:
                try:
                    research_plane_queue.put_nowait(None)
                    await asyncio.wait_for(
                        research_plane_task,
                        timeout=5.0,
                    )
                except Exception as exc:
                    research_plane_task.cancel()
                    errors.append(
                        f"research_plane_stop:{type(exc).__name__}:{exc}"
                    )
        carbon.close()
        rust.close()

    if deadline is None:
        ingress_drain_after_source_ms = 0.0
    else:
        drain_end = (
            ingress_drained_monotonic
            if ingress_drained_monotonic is not None
            else deadline
        )
        ingress_drain_after_source_ms = max(
            0.0,
            (drain_end - deadline) * 1000.0,
        )

    errors.extend(
        f"transport:{item}"
        for item in transport_errors
        if f"transport:{item}" not in errors
    )

    python_audit_state = IndexedWindowRadarState()
    python_audit_started_ns = time.perf_counter_ns()
    try:
        for trace_record, rust_snapshot, event_key, kind in parity_audit_records:
            py_started_ns = time.perf_counter_ns()
            python_trigger = python_audit_state.ingest(trace_record)
            python_audit_service_ns.append(
                time.perf_counter_ns() - py_started_ns
            )
            counters["python_audit_records"] += 1
            if kind != "trade":
                continue
            counters["python_audit_trade_decision_points"] += 1
            python_snapshot = _trigger_snapshot(python_trigger)
            if _json_equivalent(python_snapshot, rust_snapshot):
                counters["trigger_exact_matches"] += 1
            else:
                counters["trigger_mismatches"] += 1
                if len(mismatches) < 20:
                    mismatches.append(
                        {
                            "sequence": trace_record.sequence,
                            "event_key": event_key,
                            "python": python_snapshot,
                            "rust": rust_snapshot,
                        }
                    )
    except Exception as exc:
        errors.append(f"python_parity_audit:{type(exc).__name__}:{exc}")
    python_audit_total_ns = time.perf_counter_ns() - python_audit_started_ns

    trade_points = int(counters["trade_decision_points"])
    exact_matches = int(counters["trigger_exact_matches"])
    trigger_mismatches = int(counters["trigger_mismatches"])
    parity_pct = (
        100.0
        if trade_points == 0
        else 100.0 * exact_matches / trade_points
    )

    ingress_enqueued_total = (
        int(counters["pump_logs_ingress_enqueued"])
        + int(counters["pumpswap_logs_ingress_enqueued"])
    )
    ingress_consumed_total = int(counters["consumer_notifications"])

    gates = {
        "transport_open_barrier_passed": (
            counters["transport_open_barrier_passed"] == 1
        ),
        "transport_subscription_barrier_passed": (
            counters["transport_subscription_barrier_passed"] == 1
        ),
        "transport_acquisition_started": (
            counters["pump_logs_acquisition_started"] == 1
            and counters["pumpswap_logs_acquisition_started"] == 1
        ),
        "transport_pre_acquisition_ingress_zero": (
            pre_acquisition_queue_depth == 0
        ),
        "subscriptions_active": (
            counters["pump_logs_ack"] == 1
            and counters["pumpswap_logs_ack"] == 1
        ),
        "transport_sessions_isolated": counters["sessions_active"] == 2,
        "pump_reader_duration_elapsed": (
            counters["pump_logs_reader_duration_elapsed"] == 1
        ),
        "pumpswap_reader_duration_elapsed": (
            counters["pumpswap_logs_reader_duration_elapsed"] == 1
        ),
        "transport_zero_ingress_drops": (
            counters["pump_logs_ingress_drops"] == 0
            and counters["pumpswap_logs_ingress_drops"] == 0
        ),
        "transport_ingress_drained": (
            ingress_queue.empty()
            and ingress_consumed_total == ingress_enqueued_total
        ),
        "transport_ingress_accounting_exact": (
            ingress_consumed_total == ingress_enqueued_total
        ),
        "transport_microbatch_exercised": (
            counters["consumer_microbatch_max_observed"] > 1
        ),
        "transport_no_reader_errors": not transport_errors,
        "pump_observed": counters["pump_logs_notifications"] > 0,
        "pumpswap_observed": counters["pumpswap_logs_notifications"] > 0,
        "canonical_events_decoded": counters["decoded_events"] > 0,
        "adapted_trade_reached_signal_plane": (
            counters["pump_adapted_trades"]
            + counters["pumpswap_adapted_trades"]
            > 0
        ),
        "trade_decision_points_observed": trade_points > 0,
        "rust_signal_batch_exercised": counters["rust_signal_batches"] > 0,
        "rust_signal_batch_accounting_exact": (
            counters["signal_records"] > 0
            and counters["rust_signal_batch_records"]
            == counters["signal_records"]
        ),
        "python_parity_audit_complete": (
            counters["signal_records"] > 0
            and counters["trade_decision_points"] > 0
            and counters["python_audit_records"] == counters["signal_records"]
            and counters["python_audit_trade_decision_points"]
            == counters["trade_decision_points"]
        ),
        "trigger_parity_100": (
            trade_points > 0
            and trigger_mismatches == 0
            and parity_pct == 100.0
        ),
        "no_decode_failures": counters["decode_failures"] == 0,
        "identity_plane_enqueued_unknown_pool": (
            identity_plane.counters["enqueued"] > 0
        ),
        "identity_plane_rpc_attempted": (
            identity_plane.counters["requested_pools"] > 0
        ),
        "identity_plane_resolved_identity": (
            identity_plane.counters["resolved"] > 0
        ),
        "identity_plane_no_queue_overflow": (
            identity_plane.counters["queue_full"] == 0
        ),
        "identity_plane_no_rpc_batch_failure": (
            identity_plane.counters["rpc_batch_failures"] == 0
        ),
        "no_fatal_or_signal_errors": not errors,
    }
    if bridge_run_key:
        gates.update(
            {
                "episode_bridge_trigger_observed": (
                    counters["episode_bridge_trigger_snapshots"] > 0
                ),
                "episode_bridge_no_queue_overflow": (
                    counters["episode_bridge_queue_overflow"] == 0
                ),
                "episode_bridge_no_errors": (
                    counters["episode_bridge_errors"] == 0
                    and counters["episode_bridge_drain_timeout"] == 0
                ),
                "episode_bridge_accounting_exact": (
                    counters["episode_bridge_completed"]
                    == counters["episode_bridge_trigger_snapshots"]
                ),
                "episode_bridge_new_admission_observed": (
                    counters["episode_bridge_new_admissions"] > 0
                ),
            }
        )
    if research_run_key:
        gates.update(
            {
                "research_plane_exercised": (
                    counters["research_plane_enqueued"] > 0
                ),
                "research_plane_no_queue_overflow": (
                    counters["research_plane_queue_overflow"] == 0
                ),
                "research_plane_no_errors": (
                    counters["research_plane_errors"] == 0
                    and counters["research_plane_drain_timeout"] == 0
                ),
                "research_plane_accounting_exact": (
                    counters["research_plane_completed"]
                    == counters["research_plane_enqueued"]
                    == counters["signal_records"]
                ),
                "research_plane_observation_accounting_exact": (
                    counters["research_plane_trades_completed"]
                    + counters["research_plane_lifecycles_completed"]
                    == counters["research_plane_completed"]
                ),
                "research_plane_trigger_episode_observed": (
                    counters["research_plane_trigger_episodes"] > 0
                ),
                "research_plane_new_admission_observed": (
                    counters["research_plane_new_admissions"] > 0
                ),
            }
        )
    classification = (
        PASS_CLASSIFICATION if all(gates.values()) else FAIL_CLASSIFICATION
    )

    report = {
        "type": "rust_signal_plane_live_shadow_report",
        "version": VERSION,
        "classification": classification,
        "authorization": "systems_shadow_only_no_v68_no_economic_verdict",
        "endpoint_host": endpoint_host,
        "commitment": "confirmed",
        "duration_seconds": duration_seconds,
        "max_log_notifications": max_log_notifications,
        "bootstrap": {
            "report_path": str(bootstrap.report_path),
            "run_id": bootstrap.run_id,
            "decoded_identity_count": bootstrap.decoded_identity_count,
        },
        "process_ready": {
            "carbon": carbon_ready,
            "rust_signal": rust_ready,
        },
        "counters": dict(sorted(counters.items())),
        "matched_statuses": dict(sorted(matched_statuses.items())),
        "market_trade_statuses": dict(sorted(market_trade_statuses.items())),
        "transport": {
            "mode": "rust_signal_batch_postrun_parity_v5",
            "startup": {
                "open_timeout_seconds": WS_OPEN_TIMEOUT_SECONDS,
                "open_barrier_timeout_seconds": WS_OPEN_BARRIER_TIMEOUT_SECONDS,
                "subscription_ack_timeout_seconds": SUBSCRIPTION_ACK_TIMEOUT_SECONDS,
                "open_barrier_ms": open_barrier_ms,
                "subscription_barrier_ms": subscription_barrier_ms,
                "pre_acquisition_queue_depth": pre_acquisition_queue_depth,
                "acquisition_started": (
                    counters["pump_logs_acquisition_started"] == 1
                    and counters["pumpswap_logs_acquisition_started"] == 1
                ),
            },
            "queue_capacity": INGRESS_QUEUE_SIZE,
            "queue_high_water": int(counters["ingress_queue_high_water"]),
            "queue_depth_at_report": ingress_queue.qsize(),
            "enqueued_total": ingress_enqueued_total,
            "consumed_total": ingress_consumed_total,
            "drain_after_source_ms": ingress_drain_after_source_ms,
            "reader_errors": list(transport_errors),
            "pump_notifications": int(counters["pump_logs_notifications"]),
            "pumpswap_notifications": int(counters["pumpswap_logs_notifications"]),
            "pump_ingress_drops": int(counters["pump_logs_ingress_drops"]),
            "pumpswap_ingress_drops": int(counters["pumpswap_logs_ingress_drops"]),
            "websockets_version": _websockets_version(),
            "client_ping_interval": None,
            "client_ping_timeout": None,
            "surface_idle_timeout_seconds": SURFACE_IDLE_TIMEOUT_SECONDS,
            "microbatch": {
                "max_notifications": INGRESS_MICROBATCH_MAX_NOTIFICATIONS,
                "consumer_microbatches": int(counters["consumer_microbatches"]),
                "consumer_microbatch_max_observed": int(
                    counters["consumer_microbatch_max_observed"]
                ),
                "ingress_microbatch_size": _numeric_summary(
                    ingress_microbatch_sizes
                ),
                "carbon_batch_event_size": _numeric_summary(
                    carbon_batch_event_sizes
                ),
            },
            "rust_signal_batch": {
                "batch_count": int(counters["rust_signal_batches"]),
                "record_count": int(counters["rust_signal_batch_records"]),
                "max_records": int(counters["rust_signal_batch_max_records"]),
                "batch_size": _numeric_summary(rust_signal_batch_sizes),
                "roundtrip": _latency_summary_ns(rust_batch_roundtrip_ns),
                "internal_service": _latency_summary_ns(rust_batch_service_ns),
                "external_ready_clock": "batch_response_wall_ns",
            },
            "latency": {
                "ingress_queue_wait": _latency_summary_ns(ingress_queue_wait_ns),
                "pump_ingress_queue_wait": _latency_summary_ns(
                    pump_ingress_queue_wait_ns
                ),
                "pumpswap_ingress_queue_wait": _latency_summary_ns(
                    pumpswap_ingress_queue_wait_ns
                ),
                "target_extract_service": _latency_summary_ns(
                    target_extract_service_ns
                ),
                "carbon_roundtrip": _latency_summary_ns(carbon_roundtrip_ns),
            },
        },
        "research_plane": {
            "enabled": bool(research_run_key),
            "version": SIGNAL_PLANE_RESEARCH_PERSISTENCE_VERSION,
            "run_key": research_run_key or None,
            "queue_capacity": 4096 if research_run_key else 0,
            "queue_depth_at_report": (
                research_plane_queue.qsize()
                if research_plane_queue is not None
                else 0
            ),
            "attempted": int(counters["research_plane_attempted"]),
            "enqueued": int(counters["research_plane_enqueued"]),
            "completed": int(counters["research_plane_completed"]),
            "observations_inserted": int(
                counters["research_plane_observations_inserted"]
            ),
            "observation_replays": int(
                counters["research_plane_observation_replays"]
            ),
            "trades_completed": int(
                counters["research_plane_trades_completed"]
            ),
            "lifecycles_completed": int(
                counters["research_plane_lifecycles_completed"]
            ),
            "trigger_episodes": int(
                counters["research_plane_trigger_episodes"]
            ),
            "new_admissions": int(
                counters["research_plane_new_admissions"]
            ),
            "admission_replays": int(
                counters["research_plane_admission_replays"]
            ),
            "queue_high_water": int(
                counters["research_plane_queue_high_water"]
            ),
            "queue_overflow": int(
                counters["research_plane_queue_overflow"]
            ),
            "errors": int(counters["research_plane_errors"]),
            "drain_timeout": int(
                counters["research_plane_drain_timeout"]
            ),
            "policy": (
                "ordered off-hot-path durability: observation is persisted before "
                "trigger episode assignment/admission; no hazard/Jupiter/outcome call"
            ),
        },
        "episode_bridge": {
            "enabled": bool(bridge_run_key),
            "version": SIGNAL_PLANE_EPISODE_ADMISSION_VERSION,
            "run_key": bridge_run_key or None,
            "queue_capacity": 1024 if bridge_run_key else 0,
            "queue_depth_at_report": (
                episode_bridge_queue.qsize()
                if episode_bridge_queue is not None
                else 0
            ),
            "trigger_snapshots": int(
                counters["episode_bridge_trigger_snapshots"]
            ),
            "completed": int(counters["episode_bridge_completed"]),
            "new_admissions": int(
                counters["episode_bridge_new_admissions"]
            ),
            "replays": int(counters["episode_bridge_replays"]),
            "errors": int(counters["episode_bridge_errors"]),
            "queue_overflow": int(
                counters["episode_bridge_queue_overflow"]
            ),
            "drain_timeout": int(
                counters["episode_bridge_drain_timeout"]
            ),
            "policy": (
                "off-hot-path durable episode assignment/admission; "
                "does not call hazard, Jupiter, outcomes or V68 evaluator"
            ),
        },
        "identity_plane": identity_plane.summary(),
        "pumpswap_context_diagnostics": {
            "unique_pools_seen": len(pumpswap_pools_seen),
            "unique_pools_adapted": len(pumpswap_pools_adapted),
            "unique_pools_missing": len(pumpswap_pools_missing),
            "live_create_pools_seen": len(live_create_pool_seen_at),
            "adapted_identity_sources": dict(
                sorted(pumpswap_identity_sources.items())
            ),
            "missing_after_causal_live_create_pool": int(
                counters[
                    "pumpswap_missing_after_causal_live_create_pool"
                ]
            ),
            "missing_without_causal_live_create_pool": int(
                counters[
                    "pumpswap_missing_without_causal_live_create_pool"
                ]
            ),
            "policy": (
                "Live CreatePool identity is causal only from its local receive time forward. "
                "Async RPC identity never backfills the triggering trade and is usable only "
                "for later events after the RPC response wall time."
            ),
        },
        "trigger_parity": {
            "decision_points": trade_points,
            "exact_matches": exact_matches,
            "mismatches": trigger_mismatches,
            "parity_pct": parity_pct,
            "first_mismatches": mismatches,
        },
        "python_parity_audit": {
            "mode": "post_run_replay_off_live_hot_path",
            "record_count": int(counters["python_audit_records"]),
            "trade_decision_points": int(
                counters["python_audit_trade_decision_points"]
            ),
            "total_ms": python_audit_total_ns / 1_000_000.0,
            "service": _latency_summary_ns(python_audit_service_ns),
        },
        "latency": {
            "rust_service": _latency_summary_ns(rust_service_ns),
            "rust_source_to_signal": _latency_summary_ns(
                rust_source_to_signal_ns
            ),
            "rust_canonical_to_signal": _latency_summary_ns(
                rust_canonical_to_signal_ns
            ),
            "rust_dispatch_to_signal": _latency_summary_ns(
                rust_dispatch_to_signal_ns
            ),
        },
        "errors": errors,
        "gates": gates,
        "scientific_thresholds_modified": False,
        "economic_hypothesis_modified": False,
        "chain_complete_coverage_claimed": False,
        "interpretation": (
            "PASS means the live hot path used ordered Rust signal batches while Python "
            "parity ran only as a post-run replay over the exact same TraceRecords. "
            "Unknown PumpSwap identity resolution remained asynchronous with no causal "
            "backfill. It does not establish economic edge."
            if classification == PASS_CLASSIFICATION
            else "Shadow is not eligible for promotion; inspect failed systems/parity gates."
        ),
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "V5 Rust signal-batch shadow: V4.1 startup barrier -> burst microbatch -> "
            "ordered Rust-only live hot path -> post-run Python parity replay."
        )
    )
    parser.add_argument("--bootstrap-report", type=Path, required=True)
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=DEFAULT_DURATION_SECONDS,
    )
    parser.add_argument(
        "--max-log-notifications",
        type=int,
        default=DEFAULT_MAX_LOG_NOTIFICATIONS,
    )
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument(
        "--episode-bridge-run-key",
        default=None,
        help=(
            "Optional systems-only durable episode/admission bridge run key. "
            "Do not use a V68 fresh key."
        ),
    )
    parser.add_argument(
        "--research-plane-run-key",
        default=None,
        help=(
            "Optional systems-only ordered durable Research Plane run key. "
            "Persists every Signal Plane observation before any trigger episode admission. "
            "Do not use a V68 fresh key."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "artifacts/rust_signal_plane_live_shadow_v5/report.json"
        ),
    )
    args = parser.parse_args()

    report = asyncio.run(
        run_live_shadow_v0(
            bootstrap_report=args.bootstrap_report,
            duration_seconds=args.duration_seconds,
            max_log_notifications=args.max_log_notifications,
            cargo=args.cargo,
            output=args.out,
            episode_bridge_run_key=args.episode_bridge_run_key,
            research_plane_run_key=args.research_plane_run_key,
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["classification"] == PASS_CLASSIFICATION else 1


if __name__ == "__main__":
    raise SystemExit(main())
