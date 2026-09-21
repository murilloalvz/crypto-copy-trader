from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from benchmarks.holder_ownership_native_v1.run import DEFAULT_PROTOCOL, _read_json, _validate_protocol
from benchmarks.holder_ownership_native_v1.runtime_enrichment import _rpc_once


PASS = "PASS_HOLDER_OWNERSHIP_NATIVE_V1_PREFLIGHT"
FAIL = "FAIL_HOLDER_OWNERSHIP_NATIVE_V1_PREFLIGHT"
DEFAULT_SCHEMA_PROBE_TOKEN = "5JGyhGrdY7hERN4Wkvnqu6wAv6EjW2QUFfkr4CU8pump"


def run_preflight(*, protocol_path: Path, token_mint: str, helius_api_key: str) -> dict:
    protocol = _read_json(protocol_path)
    _validate_protocol(protocol)
    if not helius_api_key.strip():
        raise ValueError("HELIUS_API_KEY is required")

    supply = _rpc_once(
        api_key=helius_api_key,
        method="getTokenSupply",
        params=[token_mint, {"commitment": "confirmed"}],
        timeout_seconds=2.0,
    )
    if supply.get("error") is not None:
        raise RuntimeError(f"getTokenSupply capability probe failed: {supply.get('error')}")
    supply_result = supply.get("result")
    supply_value = supply_result.get("value") if isinstance(supply_result, dict) else None
    if not isinstance(supply_value, dict) or not str(supply_value.get("amount") or "").isdigit():
        raise RuntimeError("getTokenSupply schema probe returned invalid raw amount")

    accounts = _rpc_once(
        api_key=helius_api_key,
        method="getTokenAccounts",
        params={"page": 1, "limit": 10, "displayOptions": {}, "mint": token_mint},
        timeout_seconds=2.0,
    )
    if accounts.get("error") is not None:
        raise RuntimeError(f"getTokenAccounts capability probe failed: {accounts.get('error')}")
    result = accounts.get("result")
    rows = result.get("token_accounts") if isinstance(result, dict) else None
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("getTokenAccounts schema probe returned no token accounts")

    valid_rows = 0
    for row in rows:
        if isinstance(row, dict) and str(row.get("owner") or "").strip() and str(row.get("amount") or "").isdigit():
            valid_rows += 1
    if valid_rows == 0:
        raise RuntimeError("getTokenAccounts schema probe returned no usable owner/amount rows")

    return {
        "classification": PASS,
        "economic_outcomes_opened": False,
        "selector_changed": False,
        "capital_used": False,
        "transaction_signed": False,
        "transaction_submitted": False,
        "gmgn_used": False,
        "protocol_hash_sha256": protocol["protocol_hash_sha256"],
        "feature_id": (protocol.get("feature_contract") or {}).get("primary_feature_id"),
        "schema_probe": {
            "token_address_redacted": True,
            "token_supply_raw_redacted": True,
            "token_account_rows_returned": len(rows),
            "usable_owner_amount_rows": valid_rows,
            "methods": ["getTokenSupply", "getTokenAccounts"],
        },
        "gates": {
            "protocol_hash_valid": True,
            "helius_get_token_supply_usable": True,
            "helius_get_token_accounts_usable": True,
            "owner_field_usable": True,
            "raw_amount_field_usable": True,
            "gmgn_dependency_absent": True,
        },
        "interpretation": (
            "Read-only Helius schema/capability preflight only. It opens no economic outcome and "
            "does not calculate or expose the preregistered holder feature."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Helius capability preflight for Holder Ownership Native V1"
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--schema-probe-token", default=DEFAULT_SCHEMA_PROBE_TOKEN)
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()

    env_file = args.env_file or (Path.cwd() / ".env")
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)
    key = os.environ.get("HELIUS_API_KEY", "").strip()
    try:
        report = run_preflight(
            protocol_path=args.protocol,
            token_mint=str(args.schema_probe_token).strip(),
            helius_api_key=key,
        )
    except Exception as exc:
        text = f"{type(exc).__name__}:{exc}"
        if key:
            text = text.replace(key, "<redacted>")
        print(json.dumps({"classification": FAIL, "error": text[:700]}, indent=2))
        return 2

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
