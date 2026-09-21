from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

from benchmarks.early_buyer_churn_prospective_v1.parity import (
    validate_parity_report,
)
from benchmarks.early_buyer_churn_prospective_v1.protocol import (
    DEFAULT_PROTOCOL,
    read_json,
    validate_protocol,
)
from benchmarks.holder_ownership_native_v1.market_ingest import (
    run_preflight as run_market_ingest_preflight,
)
from benchmarks.launch_burst_prospective_route_live_v4 import (
    funded_taker_preflight as funded,
)
from benchmarks.launch_burst_prospective_route_live_v4.no_funds_assembly_diagnostic import (
    _discover_public_funded_control,
)


PASS = "PASS_EARLY_BUYER_CHURN_PROSPECTIVE_V1_PROVIDER_PREFLIGHT"
FAIL = "FAIL_EARLY_BUYER_CHURN_PROSPECTIVE_V1_PROVIDER_PREFLIGHT"
PUBLIC_DRPC_SOLANA_RPC = "https://solana.drpc.org/"
PUBLIC_SOLANA_RPC = "https://api.mainnet-beta.solana.com"
DEFAULT_OUTPUT = (
    Path("artifacts")
    / "early_buyer_churn_prospective_v1"
    / "provider-health-preflight.json"
)


def _safe_host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _is_helius(url: str) -> bool:
    return "helius" in _safe_host(url)


def _rpc_candidates(
    *,
    primary: str,
    fallbacks: tuple[str, ...],
) -> tuple[str, ...]:
    values = [str(primary or "").strip(), *[str(x).strip() for x in fallbacks]]
    values.append(PUBLIC_DRPC_SOLANA_RPC)
    values.append(PUBLIC_SOLANA_RPC)

    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or _is_helius(value) or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return tuple(output)


def _probe_assembly_read_only(
    *,
    jupiter_api_key: str,
    taker_public_key: str,
    input_mint: str,
    output_mint: str,
    amount_raw: int,
    slippage_bps: int,
) -> dict[str, Any]:
    try:
        probe = funded._probe_assembly(
            api_key=jupiter_api_key,
            taker_public_key=taker_public_key,
            input_mint=input_mint,
            output_mint=output_mint,
            amount_raw=amount_raw,
            slippage_bps=slippage_bps,
        )
        return {"status": "COMPLETED", **probe}
    except Exception as exc:
        return {
            "status": "ERROR",
            "transaction_present": False,
            "error": funded._redact_error(exc, jupiter_api_key),
        }


def _probe_ok(probe: dict[str, Any]) -> bool:
    return (
        probe.get("status") == "COMPLETED"
        and probe.get("transaction_present") is True
        and probe.get("error_code") in {None, 0}
    )


def _candidate_public_control_probe(
    *,
    candidate: str,
    fixture: dict[str, Any],
    jupiter_api_key: str,
) -> tuple[dict[str, Any], str | None, dict[str, Any] | None]:
    safe_host = _safe_host(candidate)
    try:
        control = _discover_public_funded_control(
            rpc_url=candidate,
            input_mint=str(fixture["input_mint"]),
            minimum_input_amount_raw=int(fixture["minimum_input_amount_raw"]),
            minimum_sol_lamports=int(fixture["minimum_sol_lamports"]),
            rpc_call=funded._rpc_call,
        )
    except Exception as exc:
        return (
            {
                "classification": "FAIL_PUBLIC_CONTROL_DISCOVERY",
                "safe_host": safe_host,
                "discovery_error": funded._redact_error(
                    exc,
                    candidate,
                    jupiter_api_key,
                ),
                "public_control": None,
                "known_liquid_control": {"status": "NOT_RUN"},
                "representative_burst": {"status": "NOT_RUN"},
                "economic_outcomes_opened": False,
                "provider_execute_called": False,
            },
            None,
            None,
        )

    control_taker = str(control.pop("owner_public_key"))
    common = {
        "jupiter_api_key": jupiter_api_key,
        "taker_public_key": control_taker,
        "input_mint": str(fixture["input_mint"]),
        "amount_raw": int(fixture["minimum_input_amount_raw"]),
        "slippage_bps": int(fixture["slippage_bps"]),
    }
    known = _probe_assembly_read_only(
        output_mint=str(fixture["control_output_mint"]),
        **common,
    )
    representative = _probe_assembly_read_only(
        output_mint=str(fixture["representative_burst_output_mint"]),
        **common,
    )
    assembly_pass = _probe_ok(known) and _probe_ok(representative)

    control_meta = {
        "owner_public_key_sha256": str(control["owner_public_key_sha256"]),
        "token_account_amount_raw": int(control["token_account_amount_raw"]),
        "sol_lamports": int(control["sol_lamports"]),
        "provider_preflight": PASS,
        "rpc_safe_host": safe_host,
        "candidates_checked": int(control.get("candidates_checked") or 0),
    }

    report = {
        "classification": (
            "PASS_PUBLIC_CONTROL_AND_JUPITER_ASSEMBLY"
            if assembly_pass
            else "FAIL_PUBLIC_CONTROL_JUPITER_ASSEMBLY"
        ),
        "safe_host": safe_host,
        "public_control": {
            "owner_public_key_sha256": control_meta["owner_public_key_sha256"],
            "token_account_amount_raw": control_meta["token_account_amount_raw"],
            "sol_lamports": control_meta["sol_lamports"],
            "candidates_checked": control_meta["candidates_checked"],
            "address_redacted": True,
        },
        "known_liquid_control": {
            "status": known.get("status"),
            "transaction_present": known.get("transaction_present"),
            "error_code": known.get("error_code"),
            "error_message": known.get("error_message"),
            "router": known.get("router"),
        },
        "representative_burst": {
            "status": representative.get("status"),
            "transaction_present": representative.get("transaction_present"),
            "error_code": representative.get("error_code"),
            "error_message": representative.get("error_message"),
            "router": representative.get("router"),
        },
        "economic_outcomes_opened": False,
        "provider_execute_called": False,
    }
    return (
        report,
        control_taker if assembly_pass else None,
        control_meta if assembly_pass else None,
    )


def run_provider_preflight(
    *,
    parity_report_path: Path,
    protocol_path: Path = DEFAULT_PROTOCOL,
    contract_path: Path = funded.DEFAULT_CONTRACT,
    fixture_path: Path = funded.DEFAULT_FIXTURE,
    jupiter_api_key: str,
    rpc_url: str,
    rpc_fallback_urls: tuple[str, ...],
    market_ingest_timeout_seconds: float = 12.0,
) -> tuple[
    dict[str, Any],
    str | None,
    str | None,
    dict[str, Any] | None,
]:
    protocol = read_json(protocol_path)
    validate_protocol(protocol)
    parity = validate_parity_report(
        parity_report_path=parity_report_path,
        protocol=protocol,
    )

    fixture = funded._read_json(fixture_path)
    contract = funded._read_json(contract_path)
    fixture_gates = funded._validate_fixture(fixture, contract)
    if not all(fixture_gates.values()):
        raise ValueError("frozen funded-control fixture validation failed")
    if not jupiter_api_key.strip():
        raise ValueError("JUPITER_API_KEY is required")

    try:
        market_ingest = run_market_ingest_preflight(
            timeout_seconds=market_ingest_timeout_seconds
        )
    except Exception as exc:
        market_ingest = {
            "classification": "FAIL_PUBLIC_SOLANA_STANDARD_WSS_PREFLIGHT",
            "error": f"{type(exc).__name__}:{exc}",
            "economic_outcomes_opened": False,
        }

    candidates = _rpc_candidates(
        primary=rpc_url,
        fallbacks=rpc_fallback_urls,
    )
    attempts: list[dict[str, Any]] = []
    selected_url: str | None = None
    selected_control_taker: str | None = None
    selected_control_meta: dict[str, Any] | None = None
    selected_index: int | None = None

    for index, candidate in enumerate(candidates):
        candidate_report, control_taker, control_meta = (
            _candidate_public_control_probe(
                candidate=candidate,
                fixture=fixture,
                jupiter_api_key=jupiter_api_key,
            )
        )
        attempts.append(
            {
                "candidate_index": index,
                **candidate_report,
            }
        )
        if control_taker and control_meta:
            selected_url = candidate
            selected_control_taker = control_taker
            selected_control_meta = {
                **control_meta,
                "rpc_candidate_index": index,
            }
            selected_index = index
            break

    wss_pass = (
        market_ingest.get("classification")
        == "PASS_PUBLIC_SOLANA_STANDARD_WSS_PREFLIGHT"
    )
    selected_pass = (
        selected_url is not None
        and selected_control_taker is not None
        and selected_control_meta is not None
    )
    gates = {
        "protocol_valid": True,
        "fixture_valid": all(fixture_gates.values()),
        "exact_parity_attested": parity.get("exact_parity") is True,
        "parity_mismatch_count_zero": int(parity.get("mismatch_count") or 0) == 0,
        "public_standard_wss_usable": wss_pass,
        "market_ingest_http_hydration_absent": (
            market_ingest.get("http_hydration_used") is False
            if wss_pass
            else False
        ),
        "non_helius_rpc_candidate_available": bool(candidates),
        "public_funded_control_discovered": selected_pass,
        "non_helius_rpc_and_jupiter_assembly_pass": selected_pass,
        "economic_outcomes_closed": True,
        "transaction_signing_absent": True,
        "transaction_submission_absent": True,
    }
    classification = PASS if all(gates.values()) else FAIL

    report = {
        "type": "early_buyer_churn_prospective_v1_provider_preflight",
        "classification": classification,
        "protocol_hash_sha256": protocol.get("protocol_hash_sha256"),
        "fixture_hash_sha256": fixture.get("fixture_hash_sha256"),
        "parity_attestation": parity,
        "market_ingest": market_ingest,
        "rpc_candidates_checked": attempts,
        "selected_rpc": (
            {
                "candidate_index": selected_index,
                "safe_host": _safe_host(selected_url or ""),
                "fallback_used": bool(selected_index and selected_index > 0),
                "helius": False,
            }
            if selected_url is not None
            else None
        ),
        "control": (
            {
                "owner_public_key_sha256": selected_control_meta.get(
                    "owner_public_key_sha256"
                ),
                "input_amount_raw": int(
                    selected_control_meta.get("token_account_amount_raw") or 0
                ),
                "sol_lamports": int(
                    selected_control_meta.get("sol_lamports") or 0
                ),
                "candidates_checked": int(
                    selected_control_meta.get("candidates_checked") or 0
                ),
                "address_redacted": True,
                "known_liquid_control_assembled": True,
                "representative_burst_assembled": True,
            }
            if selected_control_meta is not None
            else None
        ),
        "gates": gates,
        "economic_outcomes_opened": False,
        "fresh_confirmation_consumed": False,
        "provider_execute_called": False,
        "private_key_used": False,
        "transaction_signed": False,
        "transaction_submitted": False,
        "helius_dependency_active": False,
        "interpretation": (
            "Read-only health gate for the single preregistered Early Buyer Churn "
            "fresh confirmation. It validates exact feature parity, public Standard WSS, "
            "discovers a sufficiently funded public USDC control over a non-Helius RPC, "
            "and requires Jupiter to assemble both frozen candidate transactions. "
            "No public control address is persisted, no economic outcome is opened, "
            "and the fresh confirmation is not consumed."
        ),
    }
    return (
        report,
        selected_url,
        selected_control_taker,
        selected_control_meta,
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Outcome-blind provider health gate for Early Buyer Churn Prospective V1"
    )
    parser.add_argument("--parity-report", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--contract", type=Path, default=funded.DEFAULT_CONTRACT)
    parser.add_argument("--fixture", type=Path, default=funded.DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--wss-timeout-seconds", type=float, default=12.0)
    args = parser.parse_args()

    env_file = args.env_file or (Path.cwd() / ".env")
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

    jupiter_key = os.environ.get("JUPITER_API_KEY", "").strip()
    rpc_url = os.environ.get("SOLANA_RPC_URL", "").strip()
    fallbacks = tuple(
        item.strip()
        for item in os.environ.get("SOLANA_RPC_FALLBACK_URLS", "").split(",")
        if item.strip()
    )

    try:
        report, _selected, _control_taker, _control_meta = (
            run_provider_preflight(
                parity_report_path=args.parity_report,
                protocol_path=args.protocol,
                contract_path=args.contract,
                fixture_path=args.fixture,
                jupiter_api_key=jupiter_key,
                rpc_url=rpc_url,
                rpc_fallback_urls=fallbacks,
                market_ingest_timeout_seconds=args.wss_timeout_seconds,
            )
        )
        _write_json(args.output, report)
        report["artifact"] = str(args.output.resolve())
    except Exception as exc:
        report = {
            "classification": FAIL,
            "error": funded._redact_error(
                exc,
                jupiter_key,
                rpc_url,
            ),
            "economic_outcomes_opened": False,
            "fresh_confirmation_consumed": False,
            "provider_execute_called": False,
            "transaction_signed": False,
            "transaction_submitted": False,
        }

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("classification") == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
