from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlparse, urlunparse

from dotenv import load_dotenv

from benchmarks.helius_standard_wss_shadow_v0 import collect as standard_collect
from benchmarks.launch_burst_control_taker_sim_v0 import run_v4_sniper_v1 as base_runner
from benchmarks.launch_burst_prospective_route_live_v3 import live as v3


VERSION = "launch_burst_sniper_v1_standard_wss_transport_amendment_v0"
PASS = "PASS_SNIPER_V1_STANDARD_WSS_TRANSPORT_PREFLIGHT"
FAIL = "FAIL_SNIPER_V1_STANDARD_WSS_TRANSPORT_PREFLIGHT"


def _http_to_ws(url: str) -> str | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme == "https":
        scheme = "wss"
    elif parsed.scheme == "http":
        scheme = "ws"
    elif parsed.scheme in {"wss", "ws"}:
        scheme = parsed.scheme
    else:
        return None
    if not parsed.netloc:
        return None
    return urlunparse(
        (
            scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _host(url: str) -> str:
    try:
        return str(urlparse(url).hostname or "unknown")
    except Exception:
        return "unknown"


def _candidate_urls(
    *,
    explicit_wss_url: str,
    rpc_url: str,
    rpc_fallback_urls: tuple[str, ...],
    helius_api_key: str,
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []

    explicit = _http_to_ws(explicit_wss_url)
    if explicit:
        candidates.append(("explicit_logs_wss", explicit))

    primary = _http_to_ws(rpc_url)
    if primary:
        candidates.append(("solana_rpc_primary", primary))

    for index, item in enumerate(rpc_fallback_urls, start=1):
        derived = _http_to_ws(item)
        if derived:
            candidates.append((f"solana_rpc_fallback_{index}", derived))

    key = str(helius_api_key or "").strip()
    if key:
        candidates.append(
            (
                "helius_direct_last_resort",
                standard_collect.helius_wss_url(key),
            )
        )

    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label, url in candidates:
        if url in seen:
            continue
        seen.add(url)
        deduped.append((label, url))
    return deduped


async def _probe(url: str, *, timeout_seconds: float = 8.0) -> dict:
    from websockets.asyncio.client import connect

    request_specs = standard_collect.SUBSCRIPTION_REQUESTS
    request_labels = {
        request_id: label
        for request_id, label, _method, _params in request_specs
    }
    acks: dict[int, str] = {}

    async with connect(
        url,
        open_timeout=timeout_seconds,
        ping_interval=None,
        close_timeout=3,
        max_size=2 * 1024 * 1024,
    ) as ws:
        for payload in standard_collect.subscription_payloads():
            await ws.send(json.dumps(payload, separators=(",", ":")))

        deadline = time.monotonic() + timeout_seconds
        while len(acks) < len(request_specs):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("standard WSS subscription acknowledgement timeout")
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            message = json.loads(raw)
            if not isinstance(message, dict):
                continue
            request_id = message.get("id")
            if not isinstance(request_id, int) or request_id not in request_labels:
                continue
            if "error" in message:
                raise RuntimeError(
                    f"subscription RPC error for {request_labels[request_id]}: "
                    f"{message['error']}"
                )
            subscription_id = message.get("result")
            if not isinstance(subscription_id, int) or isinstance(subscription_id, bool):
                raise RuntimeError(
                    f"invalid subscription id for {request_labels[request_id]}"
                )
            acks[subscription_id] = request_labels[request_id]

    labels = sorted(acks.values())
    return {
        "subscription_acks": len(acks),
        "labels": labels,
        "all_required_acks": (
            set(labels)
            == {label for _id, label, _method, _params in request_specs}
        ),
    }


def _redacted_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}:{exc}"
    if len(text) > 320:
        text = text[:320] + "..."
    return text


async def resolve_transport(
    *,
    explicit_wss_url: str,
    rpc_url: str,
    rpc_fallback_urls: tuple[str, ...],
    helius_api_key: str,
) -> tuple[dict, str | None]:
    attempts: list[dict] = []
    candidates = _candidate_urls(
        explicit_wss_url=explicit_wss_url,
        rpc_url=rpc_url,
        rpc_fallback_urls=rpc_fallback_urls,
        helius_api_key=helius_api_key,
    )

    for label, url in candidates:
        host = _host(url)
        try:
            probe = await _probe(url)
            attempts.append(
                {
                    "candidate": label,
                    "host": host,
                    "status": "PASS",
                    **probe,
                }
            )
            report = {
                "type": "sniper_v1_standard_wss_transport_preflight",
                "version": VERSION,
                "classification": PASS,
                "selected_candidate": label,
                "selected_host": host,
                "candidate_count": len(candidates),
                "attempts": attempts,
                "all_three_standard_subscriptions_acked": True,
                "economic_outcomes_opened": False,
                "selector_changed": False,
                "thresholds_changed": False,
                "benchmark_changed": False,
            }
            return report, url
        except Exception as exc:
            attempts.append(
                {
                    "candidate": label,
                    "host": host,
                    "status": "FAIL",
                    "error": _redacted_error(exc),
                }
            )

    report = {
        "type": "sniper_v1_standard_wss_transport_preflight",
        "version": VERSION,
        "classification": FAIL,
        "selected_candidate": None,
        "selected_host": None,
        "candidate_count": len(candidates),
        "attempts": attempts,
        "all_three_standard_subscriptions_acked": False,
        "economic_outcomes_opened": False,
        "selector_changed": False,
        "thresholds_changed": False,
        "benchmark_changed": False,
    }
    return report, None


async def _collect_selected_wss(
    *,
    handle,
    counters,
    api_key: str,
    duration_seconds: int,
    websocket_url: str,
) -> dict:
    del api_key

    try:
        from websockets.exceptions import (
            ConnectionClosed,
            InvalidStatus,
        )
    except ImportError:
        ConnectionClosed = RuntimeError
        InvalidStatus = RuntimeError

    started = time.monotonic()
    deadline = started + float(duration_seconds)
    stop_reason = "duration_elapsed"
    session = 0

    try:
        while time.monotonic() < deadline:
            session += 1
            try:
                stop_reason = await standard_collect._run_session(
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
            except (
                OSError,
                TimeoutError,
                RuntimeError,
                asyncio.TimeoutError,
                InvalidStatus,
                ConnectionClosed,
            ):
                counters.transport_errors += 1
                if counters.reconnects >= 5 or time.monotonic() >= deadline:
                    stop_reason = "transport_error_reconnect_budget_exhausted"
                    break
                counters.reconnects += 1
                await asyncio.sleep(
                    min(
                        2.0,
                        max(0.0, deadline - time.monotonic()),
                    )
                )
    finally:
        handle.close(stop_reason=stop_reason)

    return {
        "stop_reason": stop_reason,
        "elapsed_seconds": max(
            0.0,
            time.monotonic() - started,
        ),
    }


def _parse_wrapper_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--env-file", type=Path, default=None)
    args, _unknown = parser.parse_known_args(argv)
    return args


def main() -> int:
    wrapper_args = _parse_wrapper_args(sys.argv[1:])
    env_file = wrapper_args.env_file or (Path.cwd() / ".env")
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

    helius_key = os.environ.get("HELIUS_API_KEY", "").strip()
    rpc_url = os.environ.get("SOLANA_RPC_URL", "").strip()
    fallback_urls = tuple(
        item.strip()
        for item in os.environ.get(
            "SOLANA_RPC_FALLBACK_URLS", ""
        ).split(",")
        if item.strip()
    )
    explicit_wss = os.environ.get(
        "SOLANA_LOGS_WSS_URL", ""
    ).strip()

    report, selected_url = asyncio.run(
        resolve_transport(
            explicit_wss_url=explicit_wss,
            rpc_url=rpc_url,
            rpc_fallback_urls=fallback_urls,
            helius_api_key=helius_key,
        )
    )
    print(
        json.dumps(
            {
                **report,
                "selected_url_redacted": selected_url is not None,
            },
            indent=2,
            sort_keys=True,
        )
    )
    if report.get("classification") != PASS or not selected_url:
        return 2

    source_label = (
        "standard_solana_wss:"
        + str(report.get("selected_host") or "unknown")
    )

    original_collect = v3._collect
    original_source_provider = standard_collect.SOURCE_PROVIDER

    async def selected_collect(
        *,
        handle,
        counters,
        api_key: str,
        duration_seconds: int,
    ):
        return await _collect_selected_wss(
            handle=handle,
            counters=counters,
            api_key=api_key,
            duration_seconds=duration_seconds,
            websocket_url=selected_url,
        )

    v3._collect = selected_collect
    standard_collect.SOURCE_PROVIDER = source_label
    try:
        return base_runner.main()
    finally:
        v3._collect = original_collect
        standard_collect.SOURCE_PROVIDER = original_source_provider


if __name__ == "__main__":
    raise SystemExit(main())
