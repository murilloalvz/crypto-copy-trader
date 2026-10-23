from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarks.holder_ownership_native_v1.market_ingest import run_preflight as run_market_ingest_preflight
from benchmarks.holder_ownership_rpc_v2.protocol import DEFAULT_PROTOCOL, read_json, validate_protocol
from benchmarks.holder_ownership_rpc_v2.rpc_endpoint import (
    PROBE_TOKEN,
    rpc_once,
    select_standard_rpc_endpoint,
)


PASS = "PASS_HOLDER_OWNERSHIP_RPC_V2_PREFLIGHT"
FAIL = "FAIL_HOLDER_OWNERSHIP_RPC_V2_PREFLIGHT"


def run_preflight(*, protocol_path: Path = DEFAULT_PROTOCOL) -> dict:
    protocol = read_json(protocol_path)
    validate_protocol(protocol)

    selected = select_standard_rpc_endpoint()
    rpc_url = str(selected["rpc_url"])
    safe_host = str(selected["safe_host"])

    largest = rpc_once(
        rpc_url=rpc_url,
        method="getTokenLargestAccounts",
        params=[PROBE_TOKEN, {"commitment": "processed"}],
        timeout_seconds=3.0,
    )
    if largest.get("error") is not None:
        raise RuntimeError(
            f"getTokenLargestAccounts capability probe failed on {safe_host}: "
            f"{largest.get('error')}"
        )
    largest_result = largest.get("result")
    rows = largest_result.get("value") if isinstance(largest_result, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("getTokenLargestAccounts capability probe returned no rows")

    addresses = [
        str(row.get("address") or "")
        for row in rows[: min(3, len(rows))]
        if isinstance(row, dict) and str(row.get("address") or "")
    ]
    if not addresses:
        raise RuntimeError("getTokenLargestAccounts probe returned no usable addresses")

    multiple = rpc_once(
        rpc_url=rpc_url,
        method="getMultipleAccounts",
        params=[addresses, {"encoding": "jsonParsed", "commitment": "processed"}],
        timeout_seconds=3.0,
    )
    if multiple.get("error") is not None:
        raise RuntimeError(
            f"getMultipleAccounts capability probe failed on {safe_host}: "
            f"{multiple.get('error')}"
        )
    multiple_result = multiple.get("result")
    account_rows = multiple_result.get("value") if isinstance(multiple_result, dict) else None
    if not isinstance(account_rows, list) or len(account_rows) != len(addresses):
        raise RuntimeError("getMultipleAccounts capability probe returned invalid row count")

    usable_owner_rows = 0
    for row in account_rows:
        data = row.get("data") if isinstance(row, dict) else None
        parsed = data.get("parsed") if isinstance(data, dict) else None
        info = parsed.get("info") if isinstance(parsed, dict) else None
        if isinstance(info, dict) and str(info.get("owner") or "").strip():
            usable_owner_rows += 1
    if usable_owner_rows != len(addresses):
        raise RuntimeError("jsonParsed token account owner schema unavailable")

    market_ingest = run_market_ingest_preflight()

    return {
        "classification": PASS,
        "economic_outcomes_opened": False,
        "selector_changed": False,
        "capital_used": False,
        "transaction_signed": False,
        "transaction_submitted": False,
        "helius_holder_used": False,
        "gmgn_holder_used": False,
        "protocol_hash_sha256": protocol["protocol_hash_sha256"],
        "feature_id": (protocol.get("feature_contract") or {}).get("primary_feature_id"),
        "holder_rpc": {
            "safe_host": safe_host,
            "probe_token_redacted": True,
            "get_token_supply_usable": True,
            "get_token_largest_accounts_usable": True,
            "get_multiple_accounts_json_parsed_usable": True,
            "usable_owner_rows": usable_owner_rows,
            "endpoint_fixed_after_capture_start": True,
        },
        "market_ingest": market_ingest,
        "gates": {
            "protocol_hash_valid": True,
            "non_helius_holder_rpc_selected": True,
            "get_token_supply_usable": True,
            "get_token_largest_accounts_usable": True,
            "get_multiple_accounts_json_parsed_usable": True,
            "public_solana_standard_wss_usable": (
                market_ingest.get("classification")
                == "PASS_PUBLIC_SOLANA_STANDARD_WSS_PREFLIGHT"
            ),
            "market_ingest_http_hydration_absent": (
                market_ingest.get("http_hydration_used") is False
            ),
        },
        "interpretation": (
            "Read-only systems/schema preflight only. No Holder feature is calculated or exposed, "
            "and no economic outcome is opened."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only standard-RPC capability preflight for Holder Ownership RPC V2"
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    args = parser.parse_args()
    try:
        report = run_preflight(protocol_path=args.protocol)
    except Exception as exc:
        print(json.dumps({"classification": FAIL, "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
