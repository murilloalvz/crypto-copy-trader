from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from typing import Any, Iterable
from urllib import error, parse, request

PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
VERSION = "helius_pumpswap_pool_bootstrap_probe_v0"
BATCH_SIZE = 100


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


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


def _chunks(values: tuple[str, ...], size: int = BATCH_SIZE) -> Iterable[tuple[str, ...]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _rpc_url(api_key: str) -> str:
    return "https://mainnet.helius-rpc.com/?api-key=" + parse.quote(api_key, safe="")


def _post_json(url: str, payload: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        raw = response.read()
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise RuntimeError("Helius RPC returned non-object JSON")
    return parsed


def fetch_observed_pool_accounts(
    *,
    carbon_output_path: Path,
    output_path: Path,
    api_key: str,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    pools = observed_pumpswap_pools(carbon_output_path)
    started = time.monotonic()
    rows: list[dict[str, Any]] = []
    rpc_batches = 0
    rpc_errors: list[dict[str, Any]] = []
    accounts_missing = 0

    for batch_number, batch in enumerate(_chunks(pools), start=1):
        rpc_batches += 1
        requested_wall_ns = time.time_ns()
        payload = {
            "jsonrpc": "2.0",
            "id": f"pumpswap-pool-bootstrap-{batch_number}",
            "method": "getMultipleAccounts",
            "params": [
                list(batch),
                {"encoding": "base64", "commitment": "processed"},
            ],
        }
        try:
            response = _post_json(
                _rpc_url(api_key), payload, timeout_seconds=timeout_seconds
            )
        except (error.URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            rpc_errors.append(
                {
                    "batch_number": batch_number,
                    "pool_count": len(batch),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        received_wall_ns = time.time_ns()

        if response.get("error") is not None:
            rpc_errors.append(
                {
                    "batch_number": batch_number,
                    "pool_count": len(batch),
                    "error": response.get("error"),
                }
            )
            continue

        result = response.get("result")
        if not isinstance(result, dict):
            rpc_errors.append(
                {
                    "batch_number": batch_number,
                    "pool_count": len(batch),
                    "error": "missing_result_object",
                }
            )
            continue
        context = result.get("context") or {}
        rpc_context_slot = context.get("slot")
        values = result.get("value")
        if not isinstance(rpc_context_slot, int) or isinstance(rpc_context_slot, bool):
            rpc_errors.append(
                {
                    "batch_number": batch_number,
                    "pool_count": len(batch),
                    "error": "invalid_context_slot",
                }
            )
            continue
        if not isinstance(values, list) or len(values) != len(batch):
            rpc_errors.append(
                {
                    "batch_number": batch_number,
                    "pool_count": len(batch),
                    "error": "result_value_length_mismatch",
                }
            )
            continue

        for pool, account in zip(batch, values):
            if account is None:
                accounts_missing += 1
                continue
            if not isinstance(account, dict):
                accounts_missing += 1
                continue
            data = account.get("data")
            data_base64 = data[0] if isinstance(data, list) and len(data) >= 2 else None
            encoding = data[1] if isinstance(data, list) and len(data) >= 2 else None
            if not isinstance(data_base64, str) or encoding != "base64":
                accounts_missing += 1
                continue
            rows.append(
                {
                    "type": "pumpswap_pool_account_probe",
                    "version": VERSION,
                    "pool": pool,
                    "owner": account.get("owner"),
                    "lamports": account.get("lamports"),
                    "executable": account.get("executable"),
                    "rent_epoch": account.get("rentEpoch"),
                    "space": account.get("space"),
                    "data_base64": data_base64,
                    "rpc_context_slot": rpc_context_slot,
                    "requested_wall_ns": requested_wall_ns,
                    "received_wall_ns": received_wall_ns,
                    "causal_for_source_shadow": False,
                }
            )

    _write_jsonl(output_path, rows)
    elapsed_seconds = time.monotonic() - started
    return {
        "type": "helius_pumpswap_pool_bootstrap_probe",
        "version": VERSION,
        "source_provider": "helius_free_rpc",
        "rpc_method": "getMultipleAccounts",
        "commitment": "processed",
        "unique_observed_pools": len(pools),
        "rpc_batches": rpc_batches,
        "accounts_found": len(rows),
        "accounts_missing": accounts_missing,
        "rpc_errors": len(rpc_errors),
        "rpc_error_examples": rpc_errors[:5],
        "elapsed_seconds": elapsed_seconds,
        "causal_for_source_shadow": False,
        "chain_complete_coverage_claimed": False,
        "valid_bootstrap_feasibility_probe": (
            len(pools) > 0
            and len(rows) > 0
            and not rpc_errors
            and len(rows) + accounts_missing == len(pools)
        ),
        "notes": [
            "This probe is fetched after the source shadow and MUST NOT be backfilled into that historical T0.",
            "Its purpose is to test whether active PumpSwap pool identity can be fetched cheaply before a future live run.",
            "Pool account bytes must be decoded by the pinned Carbon account decoder before use.",
        ],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe causal PumpSwap pool bootstrap feasibility")
    parser.add_argument("--carbon-output", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    api_key = os.environ.get("HELIUS_API_KEY")
    if not api_key:
        raise SystemExit("HELIUS_API_KEY is required")
    report = fetch_observed_pool_accounts(
        carbon_output_path=args.carbon_output,
        output_path=args.out,
        api_key=api_key,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid_bootstrap_feasibility_probe"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
