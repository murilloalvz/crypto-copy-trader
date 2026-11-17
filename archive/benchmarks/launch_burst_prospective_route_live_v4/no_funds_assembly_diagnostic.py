from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from benchmarks.launch_burst_prospective_route_live_v4 import funded_taker_preflight as ft


PROVIDER_CONFIRMED = "DIAGNOSTIC_LAUNCH_BURST_V4_PROVIDER_ASSEMBLY_CONFIRMED"
CONTROL_ONLY = "DIAGNOSTIC_LAUNCH_BURST_V4_CONTROL_ASSEMBLY_ONLY"
NOT_CONFIRMED = "DIAGNOSTIC_LAUNCH_BURST_V4_PROVIDER_ASSEMBLY_NOT_CONFIRMED"
DEFAULT_FIXTURE = Path(__file__).with_name("funded_taker_fixture_v0.frozen.json")
DEFAULT_CONTRACT = ft.DEFAULT_CONTRACT


def _redacted_probe(call: Callable[..., dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    try:
        probe = call(**kwargs)
        return {"status": "COMPLETED", **probe}
    except Exception as exc:
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:500]}"}


def _tx_present(probe: dict[str, Any]) -> bool:
    return probe.get("status") == "COMPLETED" and probe.get("transaction_present") is True


def _discover_public_funded_control(
    *,
    rpc_url: str,
    input_mint: str,
    minimum_input_amount_raw: int,
    minimum_sol_lamports: int,
    rpc_call: Callable[[str, str, list[Any]], Any] = ft._rpc_call,
) -> dict[str, Any]:
    largest = rpc_call(
        rpc_url,
        "getTokenLargestAccounts",
        [input_mint, {"commitment": "confirmed"}],
    )
    rows = largest.get("value") if isinstance(largest, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("getTokenLargestAccounts returned an invalid payload")

    checked = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            token_account = str(row["address"])
            amount_raw = int(row["amount"])
        except (KeyError, TypeError, ValueError):
            continue
        if amount_raw < minimum_input_amount_raw:
            continue

        checked += 1
        account_info = rpc_call(
            rpc_url,
            "getAccountInfo",
            [token_account, {"encoding": "jsonParsed", "commitment": "confirmed"}],
        )
        try:
            owner = str(account_info["value"]["data"]["parsed"]["info"]["owner"])
        except (KeyError, TypeError):
            continue
        if not owner:
            continue

        balance = rpc_call(
            rpc_url,
            "getBalance",
            [owner, {"commitment": "confirmed"}],
        )
        try:
            sol_lamports = int(balance["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if sol_lamports < minimum_sol_lamports:
            continue

        return {
            "owner_public_key": owner,
            "owner_public_key_sha256": hashlib.sha256(owner.encode("utf-8")).hexdigest(),
            "token_account_amount_raw": amount_raw,
            "sol_lamports": sol_lamports,
            "candidates_checked": checked,
        }

    raise RuntimeError("No public USDC control owner met the predeclared USDC and SOL floors")


def run_diagnostic(
    *,
    fixture_path: Path,
    contract_path: Path,
    rpc_url: str,
    jupiter_api_key: str,
    frozen_taker_public_key: str,
    rpc_call: Callable[[str, str, list[Any]], Any] = ft._rpc_call,
    balance_reader: Callable[..., dict[str, int]] = ft._read_balances,
    assembly_probe: Callable[..., dict[str, Any]] = ft._probe_assembly,
) -> dict[str, Any]:
    fixture = ft._read_json(fixture_path)
    contract = ft._read_json(contract_path)
    fixture_gates = ft._validate_fixture(fixture, contract)
    taker = frozen_taker_public_key.strip()

    report: dict[str, Any] = {
        "type": "launch_burst_v4_no_funds_assembly_diagnostic",
        "classification": NOT_CONFIRMED,
        "diagnostic_only": True,
        "official_funded_taker_gate_passed": False,
        "economic_outcomes_opened": False,
        "provider_execute_called": False,
        "fixture_hash_sha256": fixture.get("fixture_hash_sha256"),
        "route_contract_hash_sha256": contract.get("contract_hash_sha256"),
        "fixture_gates": fixture_gates,
        "frozen_taker_identity_matches": (
            bool(taker)
            and hashlib.sha256(taker.encode("utf-8")).hexdigest()
            == fixture.get("taker_public_key_sha256")
        ),
        "frozen_taker": {},
        "public_funded_control": {},
        "interpretation": (
            "Diagnostic only. It may request read-only Jupiter candidate transactions for the frozen zero-balance "
            "taker and for a public on-chain funded control address. It never signs or submits anything. A positive "
            "public control proves provider assembly capability only; it does not satisfy the frozen funded-taker gate."
        ),
    }

    if not all(fixture_gates.values()) or not report["frozen_taker_identity_matches"]:
        report["configuration_error"] = "Frozen fixture or taker identity validation failed"
        return report
    if not rpc_url.strip() or not jupiter_api_key.strip():
        report["configuration_error"] = "SOLANA_RPC_URL and JUPITER_API_KEY are required"
        return report

    try:
        balances = balance_reader(
            rpc_url=rpc_url.strip(),
            taker_public_key=taker,
            input_mint=str(fixture["input_mint"]),
        )
        report["frozen_taker"]["balances"] = {
            "input_amount_raw": int(balances.get("input_amount_raw", 0)),
            "sol_lamports": int(balances.get("sol_lamports", 0)),
        }
    except Exception as exc:
        report["frozen_taker"]["balance_error"] = ft._redact_error(exc, rpc_url, jupiter_api_key)

    common = {
        "api_key": jupiter_api_key.strip(),
        "input_mint": str(fixture["input_mint"]),
        "amount_raw": int(fixture["minimum_input_amount_raw"]),
        "slippage_bps": int(fixture["slippage_bps"]),
    }
    report["frozen_taker"]["known_liquid_control"] = _redacted_probe(
        assembly_probe,
        taker_public_key=taker,
        output_mint=str(fixture["control_output_mint"]),
        **common,
    )
    report["frozen_taker"]["representative_burst"] = _redacted_probe(
        assembly_probe,
        taker_public_key=taker,
        output_mint=str(fixture["representative_burst_output_mint"]),
        **common,
    )

    try:
        control = _discover_public_funded_control(
            rpc_url=rpc_url.strip(),
            input_mint=str(fixture["input_mint"]),
            minimum_input_amount_raw=int(fixture["minimum_input_amount_raw"]),
            minimum_sol_lamports=int(fixture["minimum_sol_lamports"]),
            rpc_call=rpc_call,
        )
    except Exception as exc:
        report["public_funded_control"] = {
            "status": "DISCOVERY_ERROR",
            "error": ft._redact_error(exc, rpc_url, jupiter_api_key),
        }
        return report

    control_taker = str(control.pop("owner_public_key"))
    report["public_funded_control"] = {"status": "DISCOVERED", **control}
    report["public_funded_control"]["known_liquid_control"] = _redacted_probe(
        assembly_probe,
        taker_public_key=control_taker,
        output_mint=str(fixture["control_output_mint"]),
        **common,
    )
    report["public_funded_control"]["representative_burst"] = _redacted_probe(
        assembly_probe,
        taker_public_key=control_taker,
        output_mint=str(fixture["representative_burst_output_mint"]),
        **common,
    )

    control_ok = _tx_present(report["public_funded_control"]["known_liquid_control"])
    burst_ok = _tx_present(report["public_funded_control"]["representative_burst"])
    if control_ok and burst_ok:
        report["classification"] = PROVIDER_CONFIRMED
    elif control_ok:
        report["classification"] = CONTROL_ONLY
    else:
        report["classification"] = NOT_CONFIRMED
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="No-funds read-only Jupiter assembly diagnostic for Launch Burst V4")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()

    env_file = args.env_file
    if env_file is None:
        candidate = Path.cwd() / ".env"
        env_file = candidate if candidate.exists() else None
    if env_file is not None and env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

    try:
        report = run_diagnostic(
            fixture_path=args.fixture,
            contract_path=args.contract,
            rpc_url=os.environ.get("SOLANA_RPC_URL", ""),
            jupiter_api_key=os.environ.get("JUPITER_API_KEY", ""),
            frozen_taker_public_key=os.environ.get("JUPITER_TAKER_PUBLIC_KEY", ""),
        )
    except Exception as exc:
        report = {
            "type": "launch_burst_v4_no_funds_assembly_diagnostic",
            "classification": NOT_CONFIRMED,
            "diagnostic_only": True,
            "official_funded_taker_gate_passed": False,
            "economic_outcomes_opened": False,
            "provider_execute_called": False,
            "error": ft._redact_error(
                exc,
                os.environ.get("JUPITER_API_KEY", ""),
                os.environ.get("SOLANA_RPC_URL", ""),
            ),
        }

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
