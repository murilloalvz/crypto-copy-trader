"""Read-only Robinhood RPC method-surface preflight.

This gate validates the exact JSON-RPC surface required by the coordinated
Robinhood/Pons acquisition path before any longer capture is opened.

It deliberately performs only narrow read-only calls:
- eth_chainId
- eth_blockNumber
- web3_sha3(TokenLaunched signature)
- eth_getCode(factory, latest)
- eth_getLogs over a small recent factory window
- eth_getBlockByNumber(latest, false)

No selector, reconciliation, latency claim, economic outcome, or trade is opened.
Provider URLs are redacted from the report so API keys are never serialized.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from src.robinhood_pons_launch_burst_v0 import (
    ROBINHOOD_CHAIN_ID,
    TOKEN_LAUNCHED_SIGNATURE,
)


PREFLIGHT_VERSION = "robinhood_rpc_method_surface_preflight_v0"
DEFAULT_RPC_URL = "https://rpc.mainnet.chain.robinhood.com"
DEFAULT_FACTORY = "0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e"
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


def _validate_rpc_url_v0(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("rpc url must be non-empty")
    value = url.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("rpc url must be an absolute http(s) URL")
    return value


class RpcProbeV0:
    def __init__(self, url: str, *, timeout_seconds: float = 10.0):
        self.url = _validate_rpc_url_v0(url)
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = float(timeout_seconds)
        self._next_id = 1

    def call(self, method: str, params: list[Any]) -> tuple[Any, dict[str, Any]]:
        request_id = self._next_id
        self._next_id += 1
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        started_ns = time.time_ns()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                http_status = int(getattr(response, "status", 200))
                row = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return None, {
                "ok": False,
                "method": method,
                "http_status": int(exc.code),
                "stage": "http",
                "error": f"HTTPError:{exc.code}:{exc.reason}",
                "service_ms": (time.time_ns() - started_ns) / 1_000_000.0,
            }
        except Exception as exc:
            return None, {
                "ok": False,
                "method": method,
                "http_status": None,
                "stage": "transport_or_response",
                "error": f"{type(exc).__name__}:{exc}",
                "service_ms": (time.time_ns() - started_ns) / 1_000_000.0,
            }

        if not isinstance(row, dict):
            return None, {
                "ok": False,
                "method": method,
                "http_status": http_status,
                "stage": "json_rpc_shape",
                "error": "response_not_object",
            }
        if row.get("id") != request_id:
            return None, {
                "ok": False,
                "method": method,
                "http_status": http_status,
                "stage": "json_rpc_identity",
                "error": f"response_id_mismatch:{row.get('id')!r}",
            }
        if row.get("error") is not None:
            return None, {
                "ok": False,
                "method": method,
                "http_status": http_status,
                "stage": "json_rpc_error",
                "error": f"rpc_error:{row['error']}",
            }
        if "result" not in row:
            return None, {
                "ok": False,
                "method": method,
                "http_status": http_status,
                "stage": "json_rpc_result",
                "error": "missing_result",
            }
        return row["result"], {
            "ok": True,
            "method": method,
            "http_status": http_status,
            "stage": "complete",
            "error": None,
            "service_ms": (time.time_ns() - started_ns) / 1_000_000.0,
        }


def _classify(checks: list[dict[str, Any]]) -> str:
    if checks and all(row.get("ok") is True for row in checks):
        return "PASS_ROBINHOOD_RPC_METHOD_SURFACE_V0"
    failed = [row for row in checks if row.get("ok") is not True]
    if any(row.get("http_status") in {401, 403} for row in failed):
        return "FAIL_ROBINHOOD_RPC_METHOD_SURFACE_ACCESS_DENIED_V0"
    if any(row.get("http_status") == 429 for row in failed):
        return "INCONCLUSIVE_ROBINHOOD_RPC_METHOD_SURFACE_RATE_LIMITED_V0"
    return "FAIL_ROBINHOOD_RPC_METHOD_SURFACE_V0"


def run_method_surface_preflight_v0(
    *,
    rpc_url: str,
    factory_address: str,
    timeout_seconds: float = 10.0,
    log_window_blocks: int = 32,
    client: RpcProbeV0 | None = None,
) -> dict[str, Any]:
    rpc_url = _validate_rpc_url_v0(rpc_url)
    if log_window_blocks <= 0:
        raise ValueError("log_window_blocks must be positive")
    rpc = client or RpcProbeV0(rpc_url, timeout_seconds=timeout_seconds)
    checks: list[dict[str, Any]] = []

    chain_raw, check = rpc.call("eth_chainId", [])
    checks.append(check)
    chain_id = None
    if check["ok"]:
        try:
            chain_id = int(str(chain_raw), 16)
        except (TypeError, ValueError):
            check.update(ok=False, stage="decode", error=f"invalid_chain_id:{chain_raw!r}")
        else:
            if chain_id != ROBINHOOD_CHAIN_ID:
                check.update(ok=False, stage="semantic", error=f"wrong_chain_id:{chain_id}")

    block_raw, check = rpc.call("eth_blockNumber", [])
    checks.append(check)
    latest_block = None
    if check["ok"]:
        try:
            latest_block = int(str(block_raw), 16)
        except (TypeError, ValueError):
            check.update(ok=False, stage="decode", error=f"invalid_block_number:{block_raw!r}")

    topic_raw, check = rpc.call(
        "web3_sha3", ["0x" + TOKEN_LAUNCHED_SIGNATURE.encode("utf-8").hex()]
    )
    checks.append(check)
    topic0 = str(topic_raw).lower() if check["ok"] and isinstance(topic_raw, str) else None
    if check["ok"] and (not topic0 or not topic0.startswith("0x")):
        check.update(ok=False, stage="decode", error="invalid_web3_sha3_result")

    code_raw, check = rpc.call("eth_getCode", [factory_address, "latest"])
    checks.append(check)
    code_present = None
    if check["ok"]:
        code_present = isinstance(code_raw, str) and code_raw not in {"0x", "0x0", ""}
        if not code_present:
            check.update(ok=False, stage="semantic", error="factory_code_missing")

    log_count = None
    if latest_block is not None and topic0 is not None:
        from_block = max(0, latest_block - log_window_blocks + 1)
        logs_raw, check = rpc.call(
            "eth_getLogs",
            [{
                "fromBlock": hex(from_block),
                "toBlock": hex(latest_block),
                "address": factory_address,
                "topics": [topic0],
            }],
        )
        checks.append(check)
        if check["ok"]:
            if isinstance(logs_raw, list):
                log_count = len(logs_raw)
            else:
                check.update(ok=False, stage="decode", error="eth_getLogs_result_not_list")
    else:
        checks.append({
            "ok": False,
            "method": "eth_getLogs",
            "http_status": None,
            "stage": "dependency",
            "error": "skipped_due_to_missing_block_or_topic",
        })

    if latest_block is not None:
        block_row, check = rpc.call("eth_getBlockByNumber", [hex(latest_block), False])
        checks.append(check)
        if check["ok"] and (not isinstance(block_row, dict) or block_row.get("hash") is None):
            check.update(ok=False, stage="decode", error="block_result_missing_hash")
    else:
        checks.append({
            "ok": False,
            "method": "eth_getBlockByNumber",
            "http_status": None,
            "stage": "dependency",
            "error": "skipped_due_to_missing_block_number",
        })

    classification = _classify(checks)
    return {
        "type": PREFLIGHT_VERSION,
        "classification": classification,
        "rpc_endpoint": _endpoint_identity(rpc_url),
        "factory_address": factory_address.lower(),
        "chain_id": chain_id,
        "latest_block": latest_block,
        "factory_code_present": code_present,
        "recent_factory_log_count": log_count,
        "log_window_blocks": log_window_blocks,
        "checks": checks,
        "acquisition_opened": False,
        "execution_reconciliation_opened": False,
        "latency_claim_opened": False,
        "economic_outcomes_opened": False,
        "selector_frozen": False,
        "notes": [
            "provider_method_surface_only",
            "eth_getLogs_window_is_small_and_read_only",
            "zero_recent_logs_is_allowed_if_method_succeeds",
            "full_provider_url_is_not_serialized",
        ],
    }


def _config_failure_report_v0(rpc_url: str, exc: Exception) -> dict[str, Any]:
    return {
        "type": PREFLIGHT_VERSION,
        "classification": "FAIL_ROBINHOOD_RPC_METHOD_SURFACE_CONFIG_V0",
        "rpc_endpoint": _endpoint_identity(rpc_url),
        "error": f"{type(exc).__name__}:{exc}",
        "acquisition_opened": False,
        "execution_reconciliation_opened": False,
        "latency_claim_opened": False,
        "economic_outcomes_opened": False,
        "selector_frozen": False,
        "notes": [
            "provider_method_surface_not_opened_due_to_invalid_rpc_configuration",
            "full_provider_url_is_not_serialized",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc-url")
    parser.add_argument("--factory-address", default=DEFAULT_FACTORY)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--log-window-blocks", type=int, default=32)
    args = parser.parse_args()
    rpc_url = args.rpc_url or os.environ.get("ROBINHOOD_RPC_URL") or DEFAULT_RPC_URL
    try:
        result = run_method_surface_preflight_v0(
            rpc_url=rpc_url,
            factory_address=args.factory_address,
            timeout_seconds=args.timeout_seconds,
            log_window_blocks=args.log_window_blocks,
        )
    except ValueError as exc:
        result = _config_failure_report_v0(rpc_url, exc)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
