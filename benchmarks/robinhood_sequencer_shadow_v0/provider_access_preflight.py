"""Fast no-capital access preflight for Robinhood Chain RPC + Nitro feed.

Runs a same-session A/B access check:
- baseline request/handshake matching the existing transport headers;
- identified request/handshake adding an explicit User-Agent.

No block/event acquisition, reconciliation, latency claim, selector, or economic
outcomes are opened. Full provider URLs are never serialized.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import urlsplit

from src.robinhood_nitro_ws_v0 import (
    FEED_CLIENT_VERSION,
    ROBINHOOD_CHAIN_ID,
    validate_handshake_response_v0,
)


PREFLIGHT_VERSION = "robinhood_provider_access_preflight_v0"
DEFAULT_RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
DEFAULT_FEED_URL = "wss://feed.mainnet.chain.robinhood.com"
USER_AGENT = "crypto-copy-trader-robinhood-shadow-v0/0"


def _endpoint_identity(url: str) -> dict[str, Any]:
    parsed = urlsplit(url)
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "path_redacted": bool(parsed.path and parsed.path != "/"),
        "query_redacted": bool(parsed.query),
    }


def _rpc_probe_v0(
    url: str,
    *,
    timeout_seconds: float = 10.0,
    user_agent: str | None = None,
) -> dict[str, Any]:
    request_id = 1
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": "eth_chainId", "params": []},
        separators=(",", ":"),
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if user_agent:
        headers["User-Agent"] = user_agent
    request = urllib.request.Request(
        url,
        data=payload,
        headers=headers,
        method="POST",
    )
    started_ns = time.time_ns()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            http_status = int(getattr(response, "status", 200))
            row = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "stage": "http",
            "http_status": int(exc.code),
            "error": f"HTTPError:{exc.code}:{exc.reason}",
            "service_ms": (time.time_ns() - started_ns) / 1_000_000.0,
        }
    except Exception as exc:
        return {
            "ok": False,
            "stage": "transport_or_response",
            "http_status": None,
            "error": f"{type(exc).__name__}:{exc}",
            "service_ms": (time.time_ns() - started_ns) / 1_000_000.0,
        }

    if not isinstance(row, dict):
        return {"ok": False, "stage": "json_rpc_shape", "http_status": http_status, "error": "response_not_object"}
    if row.get("id") != request_id:
        return {"ok": False, "stage": "json_rpc_identity", "http_status": http_status, "error": f"response_id_mismatch:{row.get('id')!r}"}
    if row.get("error") is not None:
        return {"ok": False, "stage": "json_rpc_error", "http_status": http_status, "error": f"rpc_error:{row['error']}"}
    if "result" not in row:
        return {"ok": False, "stage": "json_rpc_result", "http_status": http_status, "error": "missing_result"}
    try:
        chain_id = int(str(row["result"]), 16)
    except (TypeError, ValueError):
        return {"ok": False, "stage": "chain_id_decode", "http_status": http_status, "error": f"invalid_chain_id:{row['result']!r}"}
    return {
        "ok": chain_id == ROBINHOOD_CHAIN_ID,
        "stage": "complete",
        "http_status": http_status,
        "chain_id": chain_id,
        "error": None if chain_id == ROBINHOOD_CHAIN_ID else f"wrong_chain_id:{chain_id}",
        "service_ms": (time.time_ns() - started_ns) / 1_000_000.0,
    }


def build_feed_handshake_request_v0(
    feed_url: str,
    *,
    requested_sequence_number: int = 0,
    websocket_key: str,
    user_agent: str | None = None,
) -> bytes:
    parsed = urlsplit(feed_url)
    if parsed.scheme != "wss" or not parsed.hostname:
        raise ValueError("feed_url must be a valid wss:// URL")
    port = parsed.port or 443
    host_header = parsed.hostname if port == 443 else f"{parsed.hostname}:{port}"
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {host_header}",
    ]
    if user_agent:
        lines.append(f"User-Agent: {user_agent}")
    lines.extend(
        [
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {websocket_key}",
            "Sec-WebSocket-Version: 13",
            f"Arbitrum-Feed-Client-Version: {FEED_CLIENT_VERSION}",
            f"Arbitrum-Requested-Sequence-Number: {requested_sequence_number}",
            "",
            "",
        ]
    )
    return "\r\n".join(lines).encode("ascii")


def _read_http_upgrade_headers(sock: ssl.SSLSocket) -> bytes:
    response = bytearray()
    while b"\r\n\r\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            raise EOFError("EOF during WebSocket upgrade")
        response.extend(chunk)
        if len(response) > 64 * 1024:
            raise RuntimeError("oversized WebSocket upgrade response")
    split = response.index(b"\r\n\r\n") + 4
    return bytes(response[:split])


def _http_status_from_headers(raw_headers: bytes) -> int | None:
    try:
        line = raw_headers.decode("iso-8859-1").split("\r\n", 1)[0]
        parts = line.split(" ", 2)
        return int(parts[1]) if len(parts) >= 2 else None
    except Exception:
        return None


def _feed_probe_v0(
    url: str,
    *,
    timeout_seconds: float = 10.0,
    user_agent: str | None = None,
) -> dict[str, Any]:
    parsed = urlsplit(url)
    if parsed.scheme != "wss" or not parsed.hostname:
        return {"ok": False, "stage": "url", "http_status": None, "error": "invalid_wss_url"}
    host = parsed.hostname
    port = parsed.port or 443
    websocket_key = base64.b64encode(os.urandom(16)).decode("ascii")
    started_ns = time.time_ns()
    wrapped: ssl.SSLSocket | None = None
    try:
        raw_sock = socket.create_connection((host, port), timeout=timeout_seconds)
        context = ssl.create_default_context()
        wrapped = context.wrap_socket(raw_sock, server_hostname=host)
        wrapped.settimeout(timeout_seconds)
        wrapped.sendall(
            build_feed_handshake_request_v0(
                url,
                requested_sequence_number=0,
                websocket_key=websocket_key,
                user_agent=user_agent,
            )
        )
        raw_headers = _read_http_upgrade_headers(wrapped)
        http_status = _http_status_from_headers(raw_headers)
        if http_status != 101:
            return {
                "ok": False,
                "stage": "http_upgrade",
                "http_status": http_status,
                "error": f"websocket_upgrade_http_{http_status}",
                "service_ms": (time.time_ns() - started_ns) / 1_000_000.0,
            }
        handshake = validate_handshake_response_v0(
            raw_headers,
            websocket_key=websocket_key,
            feed_url=url,
            requested_sequence_number=0,
            expected_chain_id=ROBINHOOD_CHAIN_ID,
        )
        return {
            "ok": True,
            "stage": "complete",
            "http_status": 101,
            "chain_id": handshake.chain_id,
            "feed_server_version": handshake.feed_server_version,
            "error": None,
            "service_ms": (time.time_ns() - started_ns) / 1_000_000.0,
        }
    except Exception as exc:
        return {
            "ok": False,
            "stage": "transport_or_handshake",
            "http_status": None,
            "error": f"{type(exc).__name__}:{exc}",
            "service_ms": (time.time_ns() - started_ns) / 1_000_000.0,
        }
    finally:
        if wrapped is not None:
            try:
                wrapped.close()
            except OSError:
                pass


def classify_provider_access_v0(
    baseline_rpc: dict[str, Any],
    baseline_feed: dict[str, Any],
    identified_rpc: dict[str, Any],
    identified_feed: dict[str, Any],
) -> str:
    if baseline_rpc.get("ok") is True and baseline_feed.get("ok") is True:
        return "PASS_ROBINHOOD_PROVIDER_ACCESS_BASELINE_V0"
    if identified_rpc.get("ok") is True and identified_feed.get("ok") is True:
        return "PASS_ROBINHOOD_PROVIDER_ACCESS_IDENTIFIED_CLIENT_V0"
    rows = (identified_rpc, identified_feed)
    if any(row.get("http_status") in {401, 403} for row in rows):
        return "FAIL_ROBINHOOD_PROVIDER_ACCESS_DENIED_V0"
    if any(row.get("http_status") == 429 for row in rows):
        return "INCONCLUSIVE_ROBINHOOD_PROVIDER_RATE_LIMITED_V0"
    return "FAIL_ROBINHOOD_PROVIDER_ACCESS_PREFLIGHT_V0"


def run_provider_access_preflight_v0(
    *,
    rpc_url: str,
    feed_url: str,
    timeout_seconds: float = 10.0,
    rpc_probe: Callable[..., dict[str, Any]] = _rpc_probe_v0,
    feed_probe: Callable[..., dict[str, Any]] = _feed_probe_v0,
) -> dict[str, Any]:
    baseline_rpc = rpc_probe(rpc_url, timeout_seconds=timeout_seconds, user_agent=None)
    baseline_feed = feed_probe(feed_url, timeout_seconds=timeout_seconds, user_agent=None)
    identified_rpc = rpc_probe(rpc_url, timeout_seconds=timeout_seconds, user_agent=USER_AGENT)
    identified_feed = feed_probe(feed_url, timeout_seconds=timeout_seconds, user_agent=USER_AGENT)
    classification = classify_provider_access_v0(
        baseline_rpc,
        baseline_feed,
        identified_rpc,
        identified_feed,
    )
    return {
        "type": PREFLIGHT_VERSION,
        "classification": classification,
        "rpc_endpoint": _endpoint_identity(rpc_url),
        "feed_endpoint": _endpoint_identity(feed_url),
        "baseline": {"rpc": baseline_rpc, "feed": baseline_feed},
        "identified_client": {
            "user_agent": USER_AGENT,
            "rpc": identified_rpc,
            "feed": identified_feed,
        },
        "acquisition_opened": False,
        "execution_reconciliation_opened": False,
        "latency_claim_opened": False,
        "economic_outcomes_opened": False,
        "selector_frozen": False,
        "notes": [
            "same_session_ab_access_probe_only",
            "baseline_matches_existing_transport_header_shape",
            "identified_client_adds_only_an_explicit_user_agent",
            "rpc_probe_is_read_only_eth_chainId",
            "feed_probe_closes_immediately_after_valid_upgrade",
            "full_provider_urls_are_not_serialized_to_avoid_api_key_leakage",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc-url")
    parser.add_argument("--feed-url", default=DEFAULT_FEED_URL)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    args = parser.parse_args()
    rpc_url = args.rpc_url or os.environ.get("ROBINHOOD_RPC_URL") or DEFAULT_RPC_URL
    result = run_provider_access_preflight_v0(
        rpc_url=rpc_url,
        feed_url=args.feed_url,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
