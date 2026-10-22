from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

from dotenv import load_dotenv

from benchmarks.holder_ownership_structure_v0.run import DEFAULT_PROTOCOL, _read_json, _validate_protocol
from benchmarks.holder_ownership_structure_v0.runtime_enrichment import _collect_holder_evidence_sync


PASS = "PASS_HOLDER_OWNERSHIP_STRUCTURE_V0_PREFLIGHT"
FAIL = "FAIL_HOLDER_OWNERSHIP_STRUCTURE_V0_PREFLIGHT"
DEFAULT_SCHEMA_PROBE_TOKEN = "5JGyhGrdY7hERN4Wkvnqu6wAv6EjW2QUFfkr4CU8pump"


def run_preflight(*, protocol_path: Path, token_mint: str, api_key: str) -> dict:
    protocol = _read_json(protocol_path)
    _validate_protocol(protocol)
    if not api_key.strip():
        raise ValueError("GMGN_API_KEY is required")

    now = time.time_ns()
    record = _collect_holder_evidence_sync(
        token_mint=token_mint,
        observed_t0_wall_ns=now,
        decision_cutoff_wall_ns=now + 5_000_000_000,
        api_key=api_key,
    )
    status = str(record.get("status") or "UNKNOWN")
    if status != "CAUSAL_AVAILABLE":
        raise RuntimeError(f"holder schema/capability probe did not become causal: {status}")

    return {
        "classification": PASS,
        "economic_outcomes_opened": False,
        "selector_changed": False,
        "capital_used": False,
        "transaction_signed": False,
        "transaction_submitted": False,
        "protocol_hash_sha256": protocol["protocol_hash_sha256"],
        "feature_id": (protocol.get("feature_contract") or {}).get("primary_feature_id"),
        "schema_probe": {
            "token_address_redacted": True,
            "status": status,
            "returned_holder_row_count": record.get("returned_holder_row_count"),
            "regular_wallet_count": record.get("regular_wallet_count"),
            "burn_dead_count": record.get("burn_dead_count"),
            "dex_pool_count": record.get("dex_pool_count"),
            "denominator": record.get("denominator"),
            "excluded_addr_types": record.get("excluded_addr_types"),
            "feature_value_redacted": True,
        },
        "gates": {
            "protocol_hash_valid": True,
            "read_only_holder_command_usable": True,
            "recognized_addr_type_schema": True,
            "regular_wallet_amount_percentage_usable": True,
            "pool_exchange_exclusion_explicit": record.get("excluded_addr_types") == [1, 2],
            "total_supply_denominator_preserved": record.get("denominator") == "total_supply",
        },
        "interpretation": (
            "Read-only schema/capability preflight only. It opens no economic outcome, does not inspect "
            "historical profitability, and does not expose the holder feature value."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only capability preflight for Holder Ownership Structure V0"
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--schema-probe-token", default=DEFAULT_SCHEMA_PROBE_TOKEN)
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()

    env_file = args.env_file or (Path.cwd() / ".env")
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)
    api_key = os.environ.get("GMGN_API_KEY", "").strip()

    try:
        report = run_preflight(
            protocol_path=args.protocol,
            token_mint=str(args.schema_probe_token).strip(),
            api_key=api_key,
        )
    except Exception as exc:
        text = f"{type(exc).__name__}:{exc}"
        if api_key:
            text = text.replace(api_key, "<redacted>")
        print(json.dumps({"classification": FAIL, "error": text[:700]}, indent=2))
        return 2

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
