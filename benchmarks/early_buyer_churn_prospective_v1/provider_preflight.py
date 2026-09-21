from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

from benchmarks.early_buyer_churn_prospective_v1.protocol import (
    DEFAULT_PROTOCOL,
    read_json,
    validate_protocol,
)
from benchmarks.early_buyer_churn_prospective_v1.run_live import (
    _validate_parity_report,
)
from benchmarks.holder_ownership_native_v1.market_ingest import (
    run_preflight as run_market_ingest_preflight,
)
from benchmarks.launch_burst_prospective_route_live_v4 import (
    funded_taker_preflight as funded,
)


PASS = "PASS_EARLY_BUYER_CHURN_PROSPECTIVE_V1_PROVIDER_PREFLIGHT"
FAIL = "FAIL_EARLY_BUYER_CHURN_PROSPECTIVE_V1_PROVIDER_PREFLIGHT"
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
    host = _safe_host(url)
    return "helius" in host


def _rpc_candidates(
    *,
    primary: str,
    fallbacks: tuple[str, ...],
) -> tuple[str, ...]:
    values = [str(primary or "").strip(), *[str(x).strip() for x in fallbacks]]
    values.append(PUBLIC_SOLANA_RPC)
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or _is_helius(value):
            continue
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return tuple(output)


def _compact_funded(report: dict[str, Any], *, safe_host: str, index: int) -> dict[str, Any]:
    probes = report.get("probes") or {}
    return {
        "candidate_index": index,
        "safe_host": safe_host,
        "classification": report.get("classification"),
        "gates": report.get("gates"),
        "balances": report.get("balances"),
        "balance_error": report.get("balance_error"),
        "known_liquid_control": {
            "status": (probes.get("known_liquid_control") or {}).get("status"),
            "transaction_present": (
                probes.get("known_liquid_control") or {}
            ).get("transaction_present"),
            "error_code": (probes.get("known_liquid_control") or {}).get("error_code"),
        },
        "representative_burst": {
            "status": (probes.get("representative_burst") or {}).get("status"),
            "transaction_present": (
                probes.get("representative_burst") or {}
            ).get("transaction_present"),
            "error_code": (probes.get("representative_burst") or {}).get("error_code"),
        },
        "economic_outcomes_opened": report.get("economic_outcomes_opened"),
        "provider_execute_called": report.get("provider_execute_called"),
        "taker_public_key_sha256": report.get("taker_public_key_sha256"),
    }


def run_provider_preflight(
    *,
    parity_report_path: Path,
    protocol_path: Path = DEFAULT_PROTOCOL,
    contract_path: Path = funded.DEFAULT_CONTRACT,
    fixture_path: Path = funded.DEFAULT_FIXTURE,
    jupiter_api_key: str,
    taker_public_key: str,
    rpc_url: str,
    rpc_fallback_urls: tuple[str, ...],
    market_ingest_timeout_seconds: float = 12.0,
) -> tuple[dict[str, Any], str | None, dict[str, Any] | None]:
    protocol = read_json(protocol_path)
    validate_protocol(protocol)
    parity = _validate_parity_report(
        parity_report_path=parity_report_path,
        protocol=protocol,
    )

    market_ingest: dict[str, Any]
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
    selected_report: dict[str, Any] | None = None
    selected_index: int | None = None

    for index, candidate in enumerate(candidates):
        safe_host = _safe_host(candidate)
        try:
            report = funded.run_preflight(
                fixture_path=fixture_path,
                contract_path=contract_path,
                rpc_url=candidate,
                jupiter_api_key=jupiter_api_key,
                taker_public_key=taker_public_key,
            )
        except Exception as exc:
            report = {
                "classification": funded.FAIL,
                "balance_error": funded._redact_error(
                    exc,
                    candidate,
                    jupiter_api_key,
                ),
                "gates": {},
                "balances": None,
                "probes": {},
                "economic_outcomes_opened": False,
                "provider_execute_called": False,
            }

        attempts.append(
            _compact_funded(
                report,
                safe_host=safe_host,
                index=index,
            )
        )
        if report.get("classification") == funded.PASS:
            selected_url = candidate
            selected_report = report
            selected_index = index
            break

    selected_control_meta = None
    if selected_report is not None:
        balances = selected_report.get("balances") or {}
        selected_control_meta = {
            "owner_public_key_sha256": selected_report.get(
                "taker_public_key_sha256"
            ),
            "token_account_amount_raw": int(
                balances.get("input_amount_raw") or 0
            ),
            "sol_lamports": int(balances.get("sol_lamports") or 0),
            "provider_preflight": PASS,
            "rpc_candidate_index": int(selected_index or 0),
            "rpc_safe_host": _safe_host(selected_url or ""),
        }

    wss_pass = (
        market_ingest.get("classification")
        == "PASS_PUBLIC_SOLANA_STANDARD_WSS_PREFLIGHT"
    )
    selected_pass = selected_report is not None
    gates = {
        "protocol_valid": True,
        "exact_parity_attested": parity.get("exact_parity") is True,
        "parity_mismatch_count_zero": int(parity.get("mismatch_count") or 0) == 0,
        "public_standard_wss_usable": wss_pass,
        "market_ingest_http_hydration_absent": (
            market_ingest.get("http_hydration_used") is False
            if wss_pass
            else False
        ),
        "non_helius_rpc_candidate_available": bool(candidates),
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
                "taker_public_key_sha256": selected_report.get(
                    "taker_public_key_sha256"
                ),
                "input_amount_raw": int(
                    (selected_report.get("balances") or {}).get(
                        "input_amount_raw"
                    )
                    or 0
                ),
                "sol_lamports": int(
                    (selected_report.get("balances") or {}).get("sol_lamports")
                    or 0
                ),
                "known_liquid_control_assembled": bool(
                    (
                        selected_report.get("probes")
                        or {}
                    ).get("known_liquid_control", {}).get(
                        "transaction_present"
                    )
                ),
                "representative_burst_assembled": bool(
                    (
                        selected_report.get("probes")
                        or {}
                    ).get("representative_burst", {}).get(
                        "transaction_present"
                    )
                ),
            }
            if selected_report is not None
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
            "one non-Helius RPC endpoint, frozen control balances and Jupiter candidate "
            "transaction assembly. It opens no economic outcome and does not consume the fresh run."
        ),
    }
    return report, selected_url, selected_control_meta


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
    taker = os.environ.get("JUPITER_TAKER_PUBLIC_KEY", "").strip()
    fallbacks = tuple(
        item.strip()
        for item in os.environ.get("SOLANA_RPC_FALLBACK_URLS", "").split(",")
        if item.strip()
    )
    try:
        report, _selected, _control = run_provider_preflight(
            parity_report_path=args.parity_report,
            protocol_path=args.protocol,
            contract_path=args.contract,
            fixture_path=args.fixture,
            jupiter_api_key=jupiter_key,
            taker_public_key=taker,
            rpc_url=rpc_url,
            rpc_fallback_urls=fallbacks,
            market_ingest_timeout_seconds=args.wss_timeout_seconds,
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
