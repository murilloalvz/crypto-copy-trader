from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from typing import Any


PUBLIC_MAINNET_RPC = "https://api.mainnet.solana.com"
PROBE_TOKEN = "So11111111111111111111111111111111111111112"


def _safe_host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _is_helius(url: str) -> bool:
    return "helius" in _safe_host(url)


def rpc_candidates() -> tuple[str, ...]:
    values: list[str] = []
    primary = os.environ.get("SOLANA_RPC_URL", "").strip()
    if primary:
        values.append(primary)
    values.extend(
        item.strip()
        for item in os.environ.get("SOLANA_RPC_FALLBACK_URLS", "").split(",")
        if item.strip()
    )
    values.append(PUBLIC_MAINNET_RPC)

    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or _is_helius(value) or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return tuple(out)


def rpc_once(
    *,
    rpc_url: str,
    method: str,
    params: Any,
    timeout_seconds: float,
) -> dict[str, Any]:
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        rpc_url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "crypto-copy-trader/0.3"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=max(0.05, timeout_seconds)) as response:
            status_code = int(getattr(response, "status", 200))
            payload = json.loads(response.read().decode("utf-8"))
        error = None
        retry_after = None
    except HTTPError as exc:
        status_code = int(exc.code)
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        except Exception:
            payload = None
        error = f"HTTP_{status_code}"
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        status_code = None
        payload = None
        retry_after = None
        error = f"{type(exc).__name__}:{exc}"[:300]

    rpc_error = payload.get("error") if isinstance(payload, dict) else None
    if error is None and rpc_error is not None:
        error = f"RPC_ERROR:{rpc_error}"[:300]

    return {
        "method": method,
        "status_code": status_code,
        "error": error,
        "rate_limited": status_code == 429,
        "retry_after": retry_after,
        "result": payload.get("result") if isinstance(payload, dict) else None,
    }


def select_standard_rpc_endpoint() -> dict[str, Any]:
    errors: list[str] = []
    for url in rpc_candidates():
        host = _safe_host(url)
        call = rpc_once(
            rpc_url=url,
            method="getTokenSupply",
            params=[PROBE_TOKEN, {"commitment": "processed"}],
            timeout_seconds=3.0,
        )
        result = call.get("result")
        value = result.get("value") if isinstance(result, dict) else None
        amount = value.get("amount") if isinstance(value, dict) else None
        if call.get("error") is None and isinstance(amount, str) and amount.isdigit():
            return {
                "rpc_url": url,
                "safe_host": host,
                "probe_method": "getTokenSupply",
                "probe_ok": True,
                "helius_endpoint": False,
            }
        errors.append(f"{host or 'unknown'}:{call.get('error') or 'INVALID_SCHEMA'}")
    raise RuntimeError("no usable non-Helius standard RPC endpoint: " + " | ".join(errors))
