from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import time
from typing import Any, Iterator

from benchmarks.helius_standard_wss_shadow_v0 import collect as helius_collect
from benchmarks.market_first_live_discovery_v0 import rotating_trace
from benchmarks.launch_burst_prospective_route_paper_v2 import live as paper_v2


PUBLIC_SOLANA_WSS_URL = "wss://api.mainnet.solana.com/"
SOURCE_PROVIDER = "solana_public_standard_wss"
ENDPOINT_HOST = "api.mainnet.solana.com"


def _public_trace_header(
    *,
    duration_seconds: float,
    max_log_notifications: int,
    started_wall_ns: int,
) -> dict[str, Any]:
    row = helius_collect.trace_header(
        duration_seconds=duration_seconds,
        max_log_notifications=max_log_notifications,
        started_wall_ns=started_wall_ns,
    )
    row["source_provider"] = SOURCE_PROVIDER
    row["endpoint_host"] = ENDPOINT_HOST
    notes = list(row.get("notes") or [])
    notes.extend(
        [
            "public Solana Standard WSS market-ingest fallback",
            "no per-transaction HTTP hydration",
            "research-only endpoint with no SLA",
        ]
    )
    row["notes"] = notes
    return row


@contextmanager
def patched_public_solana_standard_wss_v1() -> Iterator[None]:
    original_url = paper_v2.helius_wss_url
    original_collect_source = helius_collect.SOURCE_PROVIDER
    original_rotating_source = rotating_trace.SOURCE_PROVIDER
    original_rotating_header = rotating_trace.trace_header

    paper_v2.helius_wss_url = lambda _api_key: PUBLIC_SOLANA_WSS_URL
    helius_collect.SOURCE_PROVIDER = SOURCE_PROVIDER
    rotating_trace.SOURCE_PROVIDER = SOURCE_PROVIDER
    rotating_trace.trace_header = _public_trace_header
    try:
        yield
    finally:
        paper_v2.helius_wss_url = original_url
        helius_collect.SOURCE_PROVIDER = original_collect_source
        rotating_trace.SOURCE_PROVIDER = original_rotating_source
        rotating_trace.trace_header = original_rotating_header


async def _preflight_async(*, timeout_seconds: float = 12.0) -> dict[str, Any]:
    try:
        from websockets.asyncio.client import connect
    except ImportError as exc:
        raise RuntimeError("websockets package is required for market ingest preflight") from exc

    request_labels = {
        request_id: label
        for request_id, label, _method, _params in helius_collect.SUBSCRIPTION_REQUESTS
    }
    subscription_labels: dict[int, str] = {}
    slot_notification_seen = False
    started = time.monotonic()

    async with connect(
        PUBLIC_SOLANA_WSS_URL,
        ping_interval=30,
        ping_timeout=30,
        close_timeout=5,
        max_size=16 * 1024 * 1024,
    ) as ws:
        for payload in helius_collect.subscription_payloads():
            await ws.send(json.dumps(payload, separators=(",", ":")))

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            remaining = max(0.001, deadline - time.monotonic())
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            message = json.loads(raw)
            if not isinstance(message, dict):
                continue

            request_id = message.get("id")
            if isinstance(request_id, int) and request_id in request_labels:
                if message.get("error") is not None:
                    raise RuntimeError(
                        f"subscription RPC error for {request_labels[request_id]}: "
                        f"{message.get('error')}"
                    )
                subscription_id = message.get("result")
                if not isinstance(subscription_id, int) or isinstance(subscription_id, bool):
                    raise RuntimeError("subscription acknowledgement returned invalid id")
                subscription_labels[subscription_id] = request_labels[request_id]
                continue

            label, normalized = helius_collect.classify_notification(
                message,
                subscription_labels,
            )
            if label == "slot" and normalized is not None:
                slot_notification_seen = True

            if len(subscription_labels) == len(request_labels) and slot_notification_seen:
                break

    if len(subscription_labels) != len(request_labels):
        raise RuntimeError(
            f"only {len(subscription_labels)}/{len(request_labels)} subscription acks observed"
        )
    if not slot_notification_seen:
        raise RuntimeError("no slot notification observed during public WSS preflight")

    return {
        "classification": "PASS_PUBLIC_SOLANA_STANDARD_WSS_PREFLIGHT",
        "source_provider": SOURCE_PROVIDER,
        "endpoint_host": ENDPOINT_HOST,
        "subscription_ack_count": len(subscription_labels),
        "slot_notification_seen": True,
        "http_hydration_used": False,
        "economic_outcomes_opened": False,
        "elapsed_seconds": max(0.0, time.monotonic() - started),
    }


def run_preflight(*, timeout_seconds: float = 12.0) -> dict[str, Any]:
    return asyncio.run(_preflight_async(timeout_seconds=timeout_seconds))
