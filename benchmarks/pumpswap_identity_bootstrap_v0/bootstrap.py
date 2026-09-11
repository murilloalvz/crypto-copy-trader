from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Iterable, Sequence
from urllib.parse import quote
from urllib.request import Request, urlopen
import uuid

from benchmarks.helius_standard_wss_shadow_v0.collect import (
    COVERAGE_CLASSIFICATION,
    SOURCE_PROVIDER,
    collect_shadow,
    redact_secret,
)
from benchmarks.helius_standard_wss_shadow_v0.reduce import reduce_shadow
from benchmarks.market_first_live_smoke_v0.run import _run_carbon_decoder
from benchmarks.pumpswap_identity_bootstrap_v0 import BOOTSTRAP_VERSION
from src.pumpswap_pool_identity import PumpSwapPoolIdentityObservation


PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WARMUP_SECONDS = 60
RPC_BATCH_SIZE = 100
DEFAULT_ARTIFACTS_ROOT = Path("artifacts") / BOOTSTRAP_VERSION
ACCOUNT_DECODER_MANIFEST = (
    Path("benchmarks")
    / "pumpswap_identity_bootstrap_v0"
    / "rust_runner"
    / "Cargo.toml"
)
PASS_CLASSIFICATION = "PASS_PUMPSWAP_IDENTITY_BOOTSTRAP_V0"
FAIL_CLASSIFICATION = "FAIL_PUMPSWAP_IDENTITY_BOOTSTRAP_V0"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def helius_http_url(api_key: str) -> str:
    key = api_key.strip()
    if not key:
        raise ValueError("HELIUS_API_KEY cannot be blank")
    return "https://mainnet.helius-rpc.com/?api-key=" + quote(key, safe="")


def _unique_pools_from_carbon(path: Path) -> tuple[str, ...]:
    pools: set[str] = set()
    for row in _jsonl(path):
        if row.get("type") != "carbon_canonical_event" or row.get("status") != "decoded":
            continue
        if row.get("event_type") not in {"pumpswap_buy", "pumpswap_sell", "pumpswap_create_pool"}:
            continue
        pool = row.get("pool")
        if isinstance(pool, str) and pool.strip():
            pools.add(pool.strip())
    return tuple(sorted(pools))


def _chunks(values: Sequence[str], size: int = RPC_BATCH_SIZE) -> Iterable[tuple[str, ...]]:
    if size <= 0 or size > RPC_BATCH_SIZE:
        raise ValueError(f"batch size must be in 1..{RPC_BATCH_SIZE}")
    for offset in range(0, len(values), size):
        yield tuple(values[offset : offset + size])


def _account_inputs_from_rpc_result(
    *,
    pools: Sequence[str],
    payload: dict[str, Any],
    observed_wall_ns: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if not isinstance(observed_wall_ns, int) or isinstance(observed_wall_ns, bool) or observed_wall_ns <= 0:
        raise ValueError("observed_wall_ns must be a positive integer")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("getMultipleAccounts result must be an object")
    context = result.get("context")
    values = result.get("value")
    if not isinstance(context, dict) or not isinstance(values, list):
        raise ValueError("getMultipleAccounts response missing context/value")
    slot = context.get("slot")
    if not isinstance(slot, int) or isinstance(slot, bool) or slot < 0:
        raise ValueError("getMultipleAccounts context slot is invalid")
    if len(values) != len(pools):
        raise ValueError("getMultipleAccounts response cardinality mismatch")

    rows: list[dict[str, Any]] = []
    counters = {
        "requested": len(pools),
        "account_missing": 0,
        "account_present": 0,
        "invalid_account_shape": 0,
    }
    for pool, account in zip(pools, values):
        if account is None:
            counters["account_missing"] += 1
            continue
        if not isinstance(account, dict):
            counters["invalid_account_shape"] += 1
            continue
        owner = account.get("owner")
        data = account.get("data")
        if (
            not isinstance(owner, str)
            or not owner.strip()
            or not isinstance(data, list)
            or len(data) < 2
            or not isinstance(data[0], str)
            or data[1] != "base64"
        ):
            counters["invalid_account_shape"] += 1
            continue
        counters["account_present"] += 1
        rows.append(
            {
                "type": "pumpswap_pool_account_input",
                "pool": pool,
                "owner": owner,
                "observed_slot": slot,
                "observed_wall_ns": observed_wall_ns,
                "evidence_key": f"getMultipleAccounts:{slot}:{observed_wall_ns}:{pool}",
                "data_base64": data[0],
            }
        )
    return rows, counters


def _fetch_account_batch(
    *,
    api_key: str,
    pools: Sequence[str],
    timeout_seconds: float = 30.0,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getMultipleAccounts",
            "params": [list(pools), {"encoding": "base64", "commitment": "processed"}],
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        helius_http_url(api_key),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read()
    observed_wall_ns = time.time_ns()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("getMultipleAccounts response must be a JSON object")
    if payload.get("error") is not None:
        raise RuntimeError(f"getMultipleAccounts RPC error: {payload['error']}")
    return _account_inputs_from_rpc_result(
        pools=pools,
        payload=payload,
        observed_wall_ns=observed_wall_ns,
    )


def fetch_pool_account_inputs(
    *,
    api_key: str,
    pools: Sequence[str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    unique = tuple(dict.fromkeys(str(pool).strip() for pool in pools if str(pool).strip()))
    rows: list[dict[str, Any]] = []
    totals = {
        "requested": 0,
        "account_missing": 0,
        "account_present": 0,
        "invalid_account_shape": 0,
        "rpc_batches": 0,
    }
    for batch in _chunks(unique):
        batch_rows, counters = _fetch_account_batch(api_key=api_key, pools=batch)
        rows.extend(batch_rows)
        totals["rpc_batches"] += 1
        for key in ("requested", "account_missing", "account_present", "invalid_account_shape"):
            totals[key] += int(counters[key])
    return rows, totals


def _run_account_decoder(
    *,
    cargo: str,
    input_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    command = [
        cargo,
        "run",
        "--release",
        "--quiet",
        "--manifest-path",
        str(ACCOUNT_DECODER_MANIFEST),
        "--",
        str(input_path),
        str(output_path),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    rows = _jsonl(output_path)
    footer = next(
        (row for row in reversed(rows) if row.get("type") == "pumpswap_pool_identity_decoder_footer"),
        {},
    )
    expected = sum(1 for row in _jsonl(input_path) if row.get("type") == "pumpswap_pool_account_input")
    accounting_valid = bool(
        completed.returncode == 0
        and footer.get("input_accounts") == expected
        and sum(
            int(footer.get(name) or 0)
            for name in ("adapted", "decode_failed", "owner_mismatch", "invalid_input")
        )
        == expected
    )
    return {
        "command": command,
        "process_return_code": completed.returncode,
        "stderr_tail": completed.stderr[-4000:],
        "stdout_tail": completed.stdout[-4000:],
        "footer": footer,
        "footer_accounting_valid": accounting_valid,
    }


def _load_identity_observations(path: Path) -> tuple[PumpSwapPoolIdentityObservation, ...]:
    identities: list[PumpSwapPoolIdentityObservation] = []
    for row in _jsonl(path):
        if row.get("type") != "pumpswap_pool_identity_decode" or row.get("status") != "ADAPTED":
            continue
        identities.append(
            PumpSwapPoolIdentityObservation(
                pool=str(row["pool"]),
                base_mint=str(row["base_mint"]),
                quote_mint=str(row["quote_mint"]),
                observed_wall_ns=int(row["observed_wall_ns"]),
                observed_slot=int(row["observed_slot"]),
                evidence_key=str(row["evidence_key"]),
                source=str(row["source"]),
            )
        )
    identities.sort(key=lambda item: (item.observed_wall_ns, item.pool, item.evidence_key))
    return tuple(identities)


def _identity_rows(identities: Sequence[PumpSwapPoolIdentityObservation]) -> list[dict[str, Any]]:
    return [
        {
            "type": "pumpswap_pool_identity_observation",
            "bootstrap_version": BOOTSTRAP_VERSION,
            "pool": item.pool,
            "base_mint": item.base_mint,
            "quote_mint": item.quote_mint,
            "observed_wall_ns": item.observed_wall_ns,
            "observed_slot": item.observed_slot,
            "evidence_key": item.evidence_key,
            "source": item.source,
        }
        for item in identities
    ]


def classify_bootstrap(report: dict[str, Any]) -> str:
    gates = report.get("gates") or {}
    return PASS_CLASSIFICATION if gates and all(bool(value) for value in gates.values()) else FAIL_CLASSIFICATION


async def run_bootstrap(*, api_key: str, cargo: str = "cargo", artifacts_root: Path = DEFAULT_ARTIFACTS_ROOT) -> dict[str, Any]:
    started_at = int(time.time())
    run_id = f"{BOOTSTRAP_VERSION}-{started_at}-{uuid.uuid4().hex[:12]}"
    run_dir = artifacts_root / run_id
    trace_path = run_dir / "warmup-wss-trace.jsonl"
    carbon_input_path = run_dir / "warmup-carbon-input.jsonl"
    manifest_path = run_dir / "warmup-target-manifest.jsonl"
    carbon_output_path = run_dir / "warmup-carbon-canonical.jsonl"
    account_input_path = run_dir / "pool-account-input.jsonl"
    account_output_path = run_dir / "pool-account-output.jsonl"
    identities_path = run_dir / "pool-identities.jsonl"
    report_path = run_dir / "report.json"
    run_dir.mkdir(parents=True, exist_ok=False)

    report: dict[str, Any] = {
        "type": "pumpswap_identity_bootstrap",
        "bootstrap_version": BOOTSTRAP_VERSION,
        "run_id": run_id,
        "warmup_seconds": WARMUP_SECONDS,
        "source_provider": SOURCE_PROVIDER,
        "coverage_classification": COVERAGE_CLASSIFICATION,
        "chain_complete_coverage_claimed": False,
        "artifacts": {
            "run_dir": str(run_dir),
            "trace": str(trace_path),
            "carbon_input": str(carbon_input_path),
            "target_manifest": str(manifest_path),
            "carbon_output": str(carbon_output_path),
            "account_input": str(account_input_path),
            "account_output": str(account_output_path),
            "identities": str(identities_path),
            "report": str(report_path),
        },
    }
    try:
        acquisition = await collect_shadow(
            api_key=api_key,
            out_path=trace_path,
            duration_seconds=float(WARMUP_SECONDS),
            max_log_notifications=0,
            max_reconnects=5,
            ack_timeout_seconds=20.0,
            reconnect_delay_seconds=2.0,
        )
        report["acquisition"] = acquisition
        reducer = reduce_shadow(
            trace_path=trace_path,
            carbon_input_path=carbon_input_path,
            manifest_path=manifest_path,
        )
        report["reducer"] = reducer
        decoder = await asyncio.to_thread(
            _run_carbon_decoder,
            cargo=cargo,
            carbon_input_path=carbon_input_path,
            carbon_output_path=carbon_output_path,
        )
        report["event_decoder"] = decoder

        pools = _unique_pools_from_carbon(carbon_output_path)
        account_inputs, rpc = await asyncio.to_thread(
            fetch_pool_account_inputs,
            api_key=api_key,
            pools=pools,
        )
        _write_jsonl(account_input_path, account_inputs)
        report["rpc"] = {**rpc, "unique_pools_observed": len(pools)}

        account_decoder = await asyncio.to_thread(
            _run_account_decoder,
            cargo=cargo,
            input_path=account_input_path,
            output_path=account_output_path,
        )
        report["account_decoder"] = account_decoder
        identities = _load_identity_observations(account_output_path)
        _write_jsonl(identities_path, _identity_rows(identities))

        identity_pools = {item.pool for item in identities}
        unresolved = tuple(sorted(set(pools) - identity_pools))
        report["identity"] = {
            "observed_pool_count": len(pools),
            "decoded_identity_count": len(identities),
            "unresolved_pool_count": len(unresolved),
            "unresolved_pool_examples": list(unresolved[:20]),
            "causal_policy": (
                "identity is usable only for market events whose first_received_wall_ns is "
                ">= identity.observed_wall_ns; no later lookup may backfill an earlier trade"
            ),
        }
        report["gates"] = {
            "fixed_operational_warmup": report["warmup_seconds"] == WARMUP_SECONDS,
            "wss_operational_shadow_active": acquisition.get("valid_operational_shadow") is True,
            "wss_warmup_duration_elapsed": acquisition.get("stop_reason") == "duration_elapsed",
            "reducer_valid_for_carbon_decode": reducer.get("valid_for_carbon_decode") is True,
            "event_decoder_accounting_valid": decoder.get("footer_accounting_valid") is True,
            "pumpswap_pool_observed": len(pools) > 0,
            "rpc_accounting_valid": (
                int(rpc["requested"]) == len(pools)
                and int(rpc["account_present"])
                + int(rpc["account_missing"])
                + int(rpc["invalid_account_shape"])
                == len(pools)
            ),
            "account_decoder_accounting_valid": account_decoder.get("footer_accounting_valid") is True,
            "at_least_one_causal_identity": len(identities) > 0,
            "coverage_claim_is_operational_only": (
                report["coverage_classification"] == COVERAGE_CLASSIFICATION
                and report["chain_complete_coverage_claimed"] is False
            ),
        }
    except Exception as exc:
        report["fatal_error"] = {
            "type": type(exc).__name__,
            "message": redact_secret(str(exc), api_key),
        }
        report.setdefault("gates", {})["no_fatal_stage_error"] = False

    if "fatal_error" not in report:
        report.setdefault("gates", {})["no_fatal_stage_error"] = True
    report["classification"] = classify_bootstrap(report)
    report["valid_bootstrap"] = report["classification"] == PASS_CLASSIFICATION
    report["ended_at"] = int(time.time())
    _write_json(report_path, report)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Causal PumpSwap pool-identity bootstrap before Market-First discovery."
    )
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    api_key = os.environ.get("HELIUS_API_KEY", "")
    if not api_key.strip():
        print("HELIUS_API_KEY is required in the environment", flush=True)
        return 2
    report = asyncio.run(
        run_bootstrap(
            api_key=api_key,
            cargo=args.cargo,
            artifacts_root=args.artifacts_root,
        )
    )
    print(json.dumps(report, sort_keys=True, indent=2), flush=True)
    return 0 if report.get("valid_bootstrap") else 1


if __name__ == "__main__":
    raise SystemExit(main())
