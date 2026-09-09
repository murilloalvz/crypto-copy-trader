from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib.parse import quote

from benchmarks.helius_standard_wss_shadow_v0 import TRACE_VERSION

PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
SOURCE_PROVIDER = "helius_free_standard_wss"
COVERAGE_CLASSIFICATION = "operational_only_not_chain_complete"

SUBSCRIPTION_REQUESTS = (
    (
        1,
        "pump_logs",
        "logsSubscribe",
        [{"mentions": [PUMP_PROGRAM_ID]}, {"commitment": "processed"}],
    ),
    (
        2,
        "pumpswap_logs",
        "logsSubscribe",
        [{"mentions": [PUMPSWAP_PROGRAM_ID]}, {"commitment": "processed"}],
    ),
    (3, "slot", "slotSubscribe", []),
)


@dataclass
class Counters:
    sessions_started: int = 0
    sessions_activated: int = 0
    reconnects: int = 0
    subscription_acks: int = 0
    pump_log_notifications: int = 0
    pumpswap_log_notifications: int = 0
    slot_notifications: int = 0
    rpc_errors: int = 0
    transport_errors: int = 0
    malformed_messages: int = 0
    write_errors: int = 0

    @property
    def log_notifications(self) -> int:
        return self.pump_log_notifications + self.pumpswap_log_notifications


def helius_wss_url(api_key: str) -> str:
    key = api_key.strip()
    if not key:
        raise ValueError("HELIUS_API_KEY cannot be blank")
    return "wss://mainnet.helius-rpc.com/?api-key=" + quote(key, safe="")


def subscription_payloads() -> list[dict[str, Any]]:
    return [
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        for request_id, _label, method, params in SUBSCRIPTION_REQUESTS
    ]


def classify_notification(
    message: dict[str, Any], subscription_labels: dict[int, str]
) -> tuple[str | None, dict[str, Any] | None]:
    """Normalize one standard Solana WSS notification without claiming completeness."""

    method = message.get("method")
    params = message.get("params")
    if not isinstance(params, dict):
        return None, None
    subscription = params.get("subscription")
    if not isinstance(subscription, int) or isinstance(subscription, bool):
        return None, None
    label = subscription_labels.get(subscription)
    result = params.get("result")
    if label in {"pump_logs", "pumpswap_logs"} and method == "logsNotification":
        if not isinstance(result, dict):
            return None, None
        context = result.get("context")
        value = result.get("value")
        if not isinstance(context, dict) or not isinstance(value, dict):
            return None, None
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
            return None, None
        return label, {
            "subscription_label": label,
            "slot": slot,
            "signature": signature,
            "err": value.get("err"),
            "logs": logs,
        }
    if label == "slot" and method == "slotNotification":
        if not isinstance(result, dict):
            return None, None
        slot = result.get("slot")
        parent = result.get("parent")
        root = result.get("root")
        if not isinstance(slot, int) or isinstance(slot, bool):
            return None, None
        return label, {"subscription_label": label, "slot": slot, "parent": parent, "root": root}
    return None, None


def _write_jsonl(handle: Any, row: dict[str, Any], counters: Counters) -> None:
    try:
        handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
    except OSError:
        counters.write_errors += 1
        raise


async def _run_session(
    *,
    websocket_url: str,
    handle: Any,
    counters: Counters,
    session_number: int,
    global_deadline: float,
    max_log_notifications: int,
    ack_timeout_seconds: float,
) -> str:
    try:
        from websockets.asyncio.client import connect
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError(
            "websockets is required; install benchmarks/helius_standard_wss_shadow_v0/requirements.txt"
        ) from exc

    session_key = f"session-{session_number:04d}"
    counters.sessions_started += 1
    connected_wall_ns = time.time_ns()
    _write_jsonl(
        handle,
        {
            "type": "transport_session_start",
            "version": TRACE_VERSION,
            "session_key": session_key,
            "connected_wall_ns": connected_wall_ns,
            "source_provider": SOURCE_PROVIDER,
            "coverage_classification": COVERAGE_CLASSIFICATION,
            "chain_complete_coverage_claimed": False,
        },
        counters,
    )

    subscription_labels: dict[int, str] = {}
    request_labels = {request_id: label for request_id, label, _method, _params in SUBSCRIPTION_REQUESTS}

    try:
        async with connect(
            websocket_url,
            ping_interval=30,
            ping_timeout=30,
            close_timeout=10,
            max_size=16 * 1024 * 1024,
        ) as ws:
            for payload in subscription_payloads():
                await ws.send(json.dumps(payload, separators=(",", ":")))

            ack_deadline = min(global_deadline, time.monotonic() + ack_timeout_seconds)
            while len(subscription_labels) < len(SUBSCRIPTION_REQUESTS):
                remaining = ack_deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("subscription acknowledgement timeout")
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                received_wall_ns = time.time_ns()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    counters.malformed_messages += 1
                    continue
                if not isinstance(message, dict):
                    counters.malformed_messages += 1
                    continue
                request_id = message.get("id")
                if isinstance(request_id, int) and request_id in request_labels:
                    if "error" in message:
                        counters.rpc_errors += 1
                        raise RuntimeError(
                            f"subscription RPC error for {request_labels[request_id]}: {message['error']}"
                        )
                    subscription_id = message.get("result")
                    if not isinstance(subscription_id, int) or isinstance(subscription_id, bool):
                        counters.malformed_messages += 1
                        continue
                    label = request_labels[request_id]
                    subscription_labels[subscription_id] = label
                    counters.subscription_acks += 1
                    _write_jsonl(
                        handle,
                        {
                            "type": "subscription_ack",
                            "version": TRACE_VERSION,
                            "session_key": session_key,
                            "request_id": request_id,
                            "subscription_id": subscription_id,
                            "subscription_label": label,
                            "received_wall_ns": received_wall_ns,
                        },
                        counters,
                    )
                    continue

                # A provider may race a notification after an earlier ack while another
                # subscription is still being acknowledged. Preserve it if understood.
                label, normalized = classify_notification(message, subscription_labels)
                if normalized is not None:
                    _record_notification(
                        handle=handle,
                        counters=counters,
                        session_key=session_key,
                        label=label,
                        normalized=normalized,
                        received_wall_ns=received_wall_ns,
                    )

            counters.sessions_activated += 1
            _write_jsonl(
                handle,
                {
                    "type": "transport_session_active",
                    "version": TRACE_VERSION,
                    "session_key": session_key,
                    "activated_wall_ns": time.time_ns(),
                    "subscriptions": dict(sorted(subscription_labels.items())),
                    "coverage_classification": COVERAGE_CLASSIFICATION,
                    "chain_complete_coverage_claimed": False,
                },
                counters,
            )

            while time.monotonic() < global_deadline:
                if max_log_notifications > 0 and counters.log_notifications >= max_log_notifications:
                    return "max_log_notifications"
                remaining = min(5.0, max(0.0, global_deadline - time.monotonic()))
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    continue
                received_wall_ns = time.time_ns()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    counters.malformed_messages += 1
                    continue
                if not isinstance(message, dict):
                    counters.malformed_messages += 1
                    continue
                if "error" in message and "id" in message:
                    counters.rpc_errors += 1
                    _write_jsonl(
                        handle,
                        {
                            "type": "rpc_error",
                            "version": TRACE_VERSION,
                            "session_key": session_key,
                            "received_wall_ns": received_wall_ns,
                            "error": message.get("error"),
                        },
                        counters,
                    )
                    continue
                label, normalized = classify_notification(message, subscription_labels)
                if normalized is None:
                    counters.malformed_messages += 1
                    continue
                _record_notification(
                    handle=handle,
                    counters=counters,
                    session_key=session_key,
                    label=label,
                    normalized=normalized,
                    received_wall_ns=received_wall_ns,
                )
            return "duration_elapsed"
    finally:
        _write_jsonl(
            handle,
            {
                "type": "transport_session_end",
                "version": TRACE_VERSION,
                "session_key": session_key,
                "ended_wall_ns": time.time_ns(),
                "coverage_classification": COVERAGE_CLASSIFICATION,
                "chain_complete_coverage_claimed": False,
            },
            counters,
        )


def _record_notification(
    *,
    handle: Any,
    counters: Counters,
    session_key: str,
    label: str | None,
    normalized: dict[str, Any],
    received_wall_ns: int,
) -> None:
    if label == "pump_logs":
        counters.pump_log_notifications += 1
        row_type = "logs_notification"
    elif label == "pumpswap_logs":
        counters.pumpswap_log_notifications += 1
        row_type = "logs_notification"
    elif label == "slot":
        counters.slot_notifications += 1
        row_type = "slot_notification"
    else:
        counters.malformed_messages += 1
        return
    _write_jsonl(
        handle,
        {
            "type": row_type,
            "version": TRACE_VERSION,
            "session_key": session_key,
            "received_wall_ns": received_wall_ns,
            **normalized,
        },
        counters,
    )


async def collect_shadow(
    *,
    api_key: str,
    out_path: Path,
    duration_seconds: float,
    max_log_notifications: int,
    max_reconnects: int,
    ack_timeout_seconds: float,
    reconnect_delay_seconds: float,
) -> dict[str, Any]:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if max_log_notifications < 0:
        raise ValueError("max_log_notifications cannot be negative")
    if max_reconnects < 0:
        raise ValueError("max_reconnects cannot be negative")
    if ack_timeout_seconds <= 0 or reconnect_delay_seconds < 0:
        raise ValueError("invalid timeout/reconnect delay")

    websocket_url = helius_wss_url(api_key)
    counters = Counters()
    started_wall_ns = time.time_ns()
    started_monotonic = time.monotonic()
    global_deadline = started_monotonic + duration_seconds
    stop_reason = "duration_elapsed"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n", buffering=1024 * 1024) as handle:
        _write_jsonl(
            handle,
            {
                "type": "trace_header",
                "version": TRACE_VERSION,
                "source_provider": SOURCE_PROVIDER,
                "endpoint_host": "mainnet.helius-rpc.com",
                "commitment": "processed",
                "programs": {"pump": PUMP_PROGRAM_ID, "pumpswap": PUMPSWAP_PROGRAM_ID},
                "started_wall_ns": started_wall_ns,
                "duration_seconds": duration_seconds,
                "max_log_notifications": max_log_notifications,
                "coverage_classification": COVERAGE_CLASSIFICATION,
                "chain_complete_coverage_claimed": False,
                "api_key_embedded_in_trace": False,
                "notes": [
                    "standard WebSocket observations only",
                    "no getTransaction hydration",
                    "processed commitment may include forked observations",
                    "active connection is not treated as proof of chain-complete coverage",
                ],
            },
            counters,
        )

        session_number = 0
        while time.monotonic() < global_deadline:
            session_number += 1
            try:
                stop_reason = await _run_session(
                    websocket_url=websocket_url,
                    handle=handle,
                    counters=counters,
                    session_number=session_number,
                    global_deadline=global_deadline,
                    max_log_notifications=max_log_notifications,
                    ack_timeout_seconds=ack_timeout_seconds,
                )
                if stop_reason in {"duration_elapsed", "max_log_notifications"}:
                    break
            except (OSError, TimeoutError, RuntimeError, asyncio.TimeoutError) as exc:
                counters.transport_errors += 1
                _write_jsonl(
                    handle,
                    {
                        "type": "transport_error",
                        "version": TRACE_VERSION,
                        "session_key": f"session-{session_number:04d}",
                        "at_wall_ns": time.time_ns(),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "coverage_classification": COVERAGE_CLASSIFICATION,
                        "chain_complete_coverage_claimed": False,
                    },
                    counters,
                )
                if counters.reconnects >= max_reconnects or time.monotonic() >= global_deadline:
                    stop_reason = "transport_error_reconnect_budget_exhausted"
                    break
                counters.reconnects += 1
                await asyncio.sleep(min(reconnect_delay_seconds, max(0.0, global_deadline - time.monotonic())))

        elapsed_seconds = max(0.0, time.monotonic() - started_monotonic)
        footer = {
            "type": "trace_footer",
            "version": TRACE_VERSION,
            "source_provider": SOURCE_PROVIDER,
            "coverage_classification": COVERAGE_CLASSIFICATION,
            "chain_complete_coverage_claimed": False,
            "stop_reason": stop_reason,
            "elapsed_seconds": elapsed_seconds,
            "counters": asdict(counters),
            "log_notifications": counters.log_notifications,
            "valid_operational_shadow": counters.sessions_activated > 0,
            "valid_chain_complete_coverage": False,
        }
        _write_jsonl(handle, footer, counters)
    return footer


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Helius Free Standard WSS operational shadow")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=float, default=300.0)
    parser.add_argument("--max-log-notifications", type=int, default=5000)
    parser.add_argument("--max-reconnects", type=int, default=5)
    parser.add_argument("--ack-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--reconnect-delay-seconds", type=float, default=2.0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    api_key = os.environ.get("HELIUS_API_KEY", "")
    if not api_key.strip():
        print("HELIUS_API_KEY is required in the environment", flush=True)
        return 2
    try:
        report = asyncio.run(
            collect_shadow(
                api_key=api_key,
                out_path=args.out,
                duration_seconds=args.duration_seconds,
                max_log_notifications=args.max_log_notifications,
                max_reconnects=args.max_reconnects,
                ack_timeout_seconds=args.ack_timeout_seconds,
                reconnect_delay_seconds=args.reconnect_delay_seconds,
            )
        )
    except Exception as exc:
        print(f"helius_standard_wss_shadow_v0 failed: {type(exc).__name__}: {exc}", flush=True)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    return 0 if report.get("valid_operational_shadow") else 1


if __name__ == "__main__":
    raise SystemExit(main())
