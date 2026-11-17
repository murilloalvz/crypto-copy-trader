from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Callable, Iterable
from urllib import error, parse, request

PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
VERSION = "helius_pumpswap_pool_lookup_latency_probe_v0"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def observed_pumpswap_pools(carbon_output_path: Path) -> tuple[str, ...]:
    pools = {
        str(row["pool"])
        for row in _jsonl(carbon_output_path)
        if row.get("type") == "carbon_canonical_event"
        and row.get("status") == "decoded"
        and row.get("event_type") in {"pumpswap_buy", "pumpswap_sell"}
        and isinstance(row.get("pool"), str)
        and row["pool"]
    }
    return tuple(sorted(pools))


def _rpc_url(api_key: str) -> str:
    return "https://mainnet.helius-rpc.com/?api-key=" + parse.quote(api_key, safe="")


def _post_json(url: str, payload: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with request.urlopen(req, timeout=timeout_seconds) as response:
        raw = response.read()
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise RuntimeError("Helius RPC returned non-object JSON")
    return parsed


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if not 0.0 <= pct <= 100.0:
        raise ValueError("pct must be between 0 and 100")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


class _Pacer:
    def __init__(self, rps: float) -> None:
        if rps <= 0:
            raise ValueError("rps must be positive")
        self.interval = 1.0 / rps
        self.last_started: float | None = None

    def wait(self) -> None:
        now = time.monotonic()
        if self.last_started is not None:
            remaining = self.interval - (now - self.last_started)
            if remaining > 0:
                time.sleep(remaining)
        self.last_started = time.monotonic()


def run_probe(
    *,
    carbon_output_path: Path,
    output_path: Path,
    api_key: str,
    rps: float = 5.0,
    timeout_seconds: float = 20.0,
    max_pools: int = 0,
    post_json: Callable[..., dict[str, Any]] = _post_json,
) -> dict[str, Any]:
    pools = observed_pumpswap_pools(carbon_output_path)
    if max_pools < 0:
        raise ValueError("max_pools must be non-negative")
    selected = pools if max_pools == 0 else pools[:max_pools]
    pacer = _Pacer(rps)
    url = _rpc_url(api_key)
    rows: list[dict[str, Any]] = []
    latencies_ms: list[float] = []
    errors: list[dict[str, Any]] = []
    accounts_missing = 0
    owner_mismatch = 0

    for index, pool in enumerate(selected, start=1):
        pacer.wait()
        requested_wall_ns = time.time_ns()
        started_ns = time.monotonic_ns()
        payload = {
            "jsonrpc": "2.0",
            "id": f"pumpswap-lazy-lookup-{index}",
            "method": "getAccountInfo",
            "params": [pool, {"encoding": "base64", "commitment": "processed"}],
        }
        try:
            response = post_json(url, payload, timeout_seconds=timeout_seconds)
        except (error.URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            errors.append({"pool": pool, "error": f"{type(exc).__name__}: {exc}"})
            continue
        received_wall_ns = time.time_ns()
        latency_ms = (time.monotonic_ns() - started_ns) / 1_000_000.0

        if response.get("error") is not None:
            errors.append({"pool": pool, "error": response.get("error")})
            continue
        result = response.get("result")
        if not isinstance(result, dict):
            errors.append({"pool": pool, "error": "missing_result_object"})
            continue
        context = result.get("context") or {}
        slot = context.get("slot")
        account = result.get("value")
        if account is None:
            accounts_missing += 1
            latencies_ms.append(latency_ms)
            continue
        if not isinstance(account, dict):
            errors.append({"pool": pool, "error": "invalid_account_object"})
            continue
        data = account.get("data")
        data_base64 = data[0] if isinstance(data, list) and len(data) >= 2 else None
        encoding = data[1] if isinstance(data, list) and len(data) >= 2 else None
        owner = account.get("owner")
        if owner != PUMPSWAP_PROGRAM_ID:
            owner_mismatch += 1
        if (
            not isinstance(slot, int)
            or isinstance(slot, bool)
            or not isinstance(data_base64, str)
            or encoding != "base64"
        ):
            errors.append({"pool": pool, "error": "invalid_account_payload"})
            continue

        latencies_ms.append(latency_ms)
        rows.append({
            "type": "pumpswap_pool_account_probe",
            "version": VERSION,
            "pool": pool,
            "owner": owner,
            "lamports": account.get("lamports"),
            "executable": account.get("executable"),
            "rent_epoch": account.get("rentEpoch"),
            "space": account.get("space"),
            "data_base64": data_base64,
            "rpc_context_slot": slot,
            "requested_wall_ns": requested_wall_ns,
            "received_wall_ns": received_wall_ns,
            "lookup_latency_ms": latency_ms,
            "causal_for_source_shadow": False,
            "benchmark_only": True,
        })

    _write_jsonl(output_path, rows)
    return {
        "type": "helius_pumpswap_pool_lookup_latency_probe",
        "version": VERSION,
        "provider": "helius_free_rpc",
        "rpc_method": "getAccountInfo",
        "commitment": "processed",
        "observed_unique_pools": len(pools),
        "requested_pools": len(selected),
        "accounts_found": len(rows),
        "accounts_missing": accounts_missing,
        "owner_mismatch": owner_mismatch,
        "request_errors": len(errors),
        "request_error_examples": errors[:10],
        "successful_latency_samples": len(latencies_ms),
        "latency_ms": {
            "min": min(latencies_ms) if latencies_ms else None,
            "p50": _percentile(latencies_ms, 50),
            "p95": _percentile(latencies_ms, 95),
            "p99": _percentile(latencies_ms, 99),
            "max": max(latencies_ms) if latencies_ms else None,
        },
        "compatible_with_existing_carbon_pool_account_decoder": True,
        "counterfactual": False,
        "causal_for_source_shadow": False,
        "economic_edge_evaluated": False,
        "valid_latency_probe": len(selected) > 0 and len(latencies_ms) > 0 and not errors,
        "notes": [
            "This measures live RPC lookup latency for observed PumpSwap Pool accounts; it does not measure WSS event latency.",
            "Rows intentionally use the existing pumpswap_pool_account_probe contract so the pinned Carbon account decoder can consume the same payload.",
            "The source shadow is historical; these fresh account lookups MUST NOT be backfilled into its T0.",
            "Account decode latency is measured separately from network lookup latency.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure live Helius PumpSwap pool-account lookup latency")
    parser.add_argument("--carbon-output", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rps", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--max-pools", type=int, default=0)
    args = parser.parse_args()
    api_key = os.environ.get("HELIUS_API_KEY")
    if not api_key:
        raise SystemExit("HELIUS_API_KEY is required")
    report = run_probe(
        carbon_output_path=args.carbon_output,
        output_path=args.out,
        api_key=api_key,
        rps=args.rps,
        timeout_seconds=args.timeout_seconds,
        max_pools=args.max_pools,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid_latency_probe"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
