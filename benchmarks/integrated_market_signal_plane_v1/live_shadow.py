from __future__ import annotations

import argparse
import asyncio
import base64
from collections import Counter
from dataclasses import asdict
import json
import math
import os
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
from src.pumpswap_stream import build_logs_subscribe_request as build_pumpswap_subscribe


VERSION = "rust_signal_plane_live_shadow_v0"
PASS_CLASSIFICATION = "PASS_RUST_SIGNAL_PLANE_LIVE_SHADOW_V0"
FAIL_CLASSIFICATION = "FAIL_RUST_SIGNAL_PLANE_LIVE_SHADOW_V0"
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


async def run_live_shadow_v0(
    *,
    bootstrap_report: Path,
    duration_seconds: float,
    max_log_notifications: int,
    cargo: str,
    output: Path,
) -> dict[str, Any]:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if max_log_notifications < 0:
        raise ValueError("max_log_notifications cannot be negative")

    bootstrap = load_bootstrap_evidence_v0(Path(bootstrap_report))
    endpoint = rpc_http_to_ws_url(settings.rpc_url)
    endpoint_host = _endpoint_host(endpoint)
    start_wall_ns = time.time_ns()
    validate_bootstrap_before_discovery_start_v0(
        bootstrap,
        discovery_start_wall_ns=start_wall_ns,
    )

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

    python_state = IndexedWindowRadarState()
    seen_event_keys: set[str] = set()
    subscription_labels: dict[int, str] = {}
    request_labels = {1: "pump_logs", 2: "pumpswap_logs"}
    counters: Counter[str] = Counter()
    matched_statuses: Counter[str] = Counter()
    market_trade_statuses: Counter[str] = Counter()
    mismatches: list[dict[str, Any]] = []
    errors: list[str] = []
    python_service_ns: list[int] = []
    rust_service_ns: list[int] = []
    python_source_to_signal_ns: list[int] = []
    rust_source_to_signal_ns: list[int] = []
    python_canonical_to_signal_ns: list[int] = []
    rust_canonical_to_signal_ns: list[int] = []
    rust_dispatch_to_signal_ns: list[int] = []
    signal_sequence = 0
    batch_id = 0
    log_notifications = 0

    try:
        from websockets.asyncio.client import connect

        deadline = time.monotonic() + duration_seconds
        async with connect(
            endpoint,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
            max_size=16 * 1024 * 1024,
            max_queue=256,
        ) as ws:
            requests = [
                build_pump_subscribe(request_id=1, commitment="confirmed"),
                build_pumpswap_subscribe(request_id=2, commitment="confirmed"),
            ]
            for request in requests:
                await ws.send(json.dumps(request, separators=(",", ":")))

            while len(subscription_labels) < 2:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("subscription acknowledgement timeout")
                raw = await asyncio.wait_for(ws.recv(), timeout=min(20.0, remaining))
                message = json.loads(raw)
                request_id = message.get("id")
                if request_id in request_labels:
                    if message.get("error") is not None:
                        raise RuntimeError(
                            f"subscription RPC error for {request_labels[request_id]}: "
                            f"{message['error']}"
                        )
                    subscription_id = message.get("result")
                    if not isinstance(subscription_id, int) or isinstance(subscription_id, bool):
                        raise RuntimeError("subscription acknowledgement missing integer id")
                    subscription_labels[subscription_id] = request_labels[request_id]
                    counters[f"{request_labels[request_id]}_ack"] += 1

            counters["sessions_active"] = 1

            while time.monotonic() < deadline:
                if max_log_notifications > 0 and log_notifications >= max_log_notifications:
                    break
                remaining = min(5.0, max(0.0, deadline - time.monotonic()))
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    continue
                received_wall_ns = time.time_ns()
                message = json.loads(raw)
                if not isinstance(message, dict):
                    counters["malformed_messages"] += 1
                    continue
                if message.get("method") != "logsNotification":
                    continue
                params = message.get("params")
                if not isinstance(params, dict):
                    counters["malformed_messages"] += 1
                    continue
                subscription = params.get("subscription")
                label = (
                    subscription_labels.get(subscription)
                    if isinstance(subscription, int)
                    else None
                )
                if label not in {"pump_logs", "pumpswap_logs"}:
                    continue
                result = params.get("result")
                if not isinstance(result, dict):
                    counters["malformed_messages"] += 1
                    continue
                context = result.get("context")
                value = result.get("value")
                if not isinstance(context, dict) or not isinstance(value, dict):
                    counters["malformed_messages"] += 1
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
                    counters["malformed_messages"] += 1
                    continue

                normalized = {
                    "subscription_label": label,
                    "slot": slot,
                    "signature": signature,
                    "err": value.get("err"),
                    "logs": logs,
                }
                counters[f"{label}_notifications"] += 1
                log_notifications += 1

                items, manifests, stack_errors = _target_inputs_from_notification(
                    normalized=normalized,
                    received_wall_ns=received_wall_ns,
                    seen_event_keys=seen_event_keys,
                )
                counters["stack_errors"] += stack_errors
                counters["target_events"] += len(items)
                if not items:
                    continue

                batch_id += 1
                decoder_row = await asyncio.to_thread(
                    carbon.request,
                    {
                        "type": "carbon_decoder_batch",
                        "batch_id": batch_id,
                        "items": items,
                    },
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
                    else:
                        continue

                    assert observation is not None and kind is not None
                    signal_record = _build_signal_record(
                        sequence=signal_sequence,
                        kind=kind,
                        observation=observation,
                        source_received_wall_ns=source_wall_ns,
                        canonical_ready_wall_ns=canonical_ready_wall_ns,
                    )

                    rust_dispatch_wall_ns = time.time_ns()
                    await asyncio.to_thread(rust.send, signal_record)

                    py_started_ns = time.perf_counter_ns()
                    python_trigger = python_state.ingest(
                        TraceRecord(
                            sequence=signal_sequence,
                            arrival_offset_ns=max(0, source_wall_ns - start_wall_ns),
                            kind=kind,
                            event_key=str(event_key),
                            source_provider=f"shadow:{endpoint_host}",
                            trade=(observation if kind == "trade" else None),
                            lifecycle=(observation if kind == "lifecycle" else None),
                        )
                    )
                    py_service_elapsed_ns = time.perf_counter_ns() - py_started_ns
                    python_signal_ready_wall_ns = time.time_ns()

                    rust_row = await asyncio.to_thread(rust.receive)
                    if rust_row.get("type") == "signal_error":
                        errors.append(
                            f"rust_signal_error:{rust_row.get('error')}"
                        )
                        signal_sequence += 1
                        continue
                    if (
                        rust_row.get("type") != "signal_result"
                        or int(rust_row.get("sequence", -1)) != signal_sequence
                    ):
                        errors.append(
                            f"rust_sequence_or_type_mismatch:{signal_sequence}:{rust_row!r}"
                        )
                        signal_sequence += 1
                        continue

                    python_snapshot = _trigger_snapshot(python_trigger)
                    rust_snapshot = rust_row.get("trigger")
                    counters["signal_records"] += 1
                    if kind == "trade":
                        counters["trade_decision_points"] += 1
                        if _json_equivalent(python_snapshot, rust_snapshot):
                            counters["trigger_exact_matches"] += 1
                        else:
                            counters["trigger_mismatches"] += 1
                            if len(mismatches) < 20:
                                mismatches.append(
                                    {
                                        "sequence": signal_sequence,
                                        "event_key": event_key,
                                        "python": python_snapshot,
                                        "rust": rust_snapshot,
                                    }
                                )

                    rust_signal_ready_wall_ns = int(
                        rust_row["signal_ready_wall_ns"]
                    )
                    rust_service_elapsed_ns = int(rust_row["service_ns"])

                    python_service_ns.append(py_service_elapsed_ns)
                    rust_service_ns.append(rust_service_elapsed_ns)
                    python_source_to_signal_ns.append(
                        max(0, python_signal_ready_wall_ns - source_wall_ns)
                    )
                    rust_source_to_signal_ns.append(
                        max(0, rust_signal_ready_wall_ns - source_wall_ns)
                    )
                    python_canonical_to_signal_ns.append(
                        max(0, python_signal_ready_wall_ns - canonical_ready_wall_ns)
                    )
                    rust_canonical_to_signal_ns.append(
                        max(0, rust_signal_ready_wall_ns - canonical_ready_wall_ns)
                    )
                    rust_dispatch_to_signal_ns.append(
                        max(0, rust_signal_ready_wall_ns - rust_dispatch_wall_ns)
                    )
                    signal_sequence += 1

    except Exception as exc:
        errors.append(f"fatal:{type(exc).__name__}:{exc}")
    finally:
        carbon.close()
        rust.close()

    trade_points = int(counters["trade_decision_points"])
    exact_matches = int(counters["trigger_exact_matches"])
    trigger_mismatches = int(counters["trigger_mismatches"])
    parity_pct = (
        100.0
        if trade_points == 0
        else 100.0 * exact_matches / trade_points
    )

    gates = {
        "subscriptions_active": (
            counters["pump_logs_ack"] == 1
            and counters["pumpswap_logs_ack"] == 1
        ),
        "pump_observed": counters["pump_logs_notifications"] > 0,
        "pumpswap_observed": counters["pumpswap_logs_notifications"] > 0,
        "canonical_events_decoded": counters["decoded_events"] > 0,
        "adapted_trade_reached_signal_plane": (
            counters["pump_adapted_trades"]
            + counters["pumpswap_adapted_trades"]
            > 0
        ),
        "trade_decision_points_observed": trade_points > 0,
        "trigger_parity_100": trigger_mismatches == 0 and parity_pct == 100.0,
        "no_decode_failures": counters["decode_failures"] == 0,
        "no_fatal_or_signal_errors": not errors,
    }
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
        "trigger_parity": {
            "decision_points": trade_points,
            "exact_matches": exact_matches,
            "mismatches": trigger_mismatches,
            "parity_pct": parity_pct,
            "first_mismatches": mismatches,
        },
        "latency": {
            "python_service": _latency_summary_ns(python_service_ns),
            "rust_service": _latency_summary_ns(rust_service_ns),
            "python_source_to_signal": _latency_summary_ns(
                python_source_to_signal_ns
            ),
            "rust_source_to_signal": _latency_summary_ns(
                rust_source_to_signal_ns
            ),
            "python_canonical_to_signal": _latency_summary_ns(
                python_canonical_to_signal_ns
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
            "PASS means the Rust Signal Plane matched the Python indexed Radar on the "
            "same live canonical observations while remaining persistence/RPC/economic free. "
            "It does not establish economic edge."
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
            "Short live systems shadow: standard Solana logs -> frozen Carbon decoder -> "
            "same canonical observations -> Python indexed Radar + Rust indexed Radar."
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
        "--out",
        type=Path,
        default=Path(
            "artifacts/rust_signal_plane_live_shadow_v0/report.json"
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
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["classification"] == PASS_CLASSIFICATION else 1


if __name__ == "__main__":
    raise SystemExit(main())
