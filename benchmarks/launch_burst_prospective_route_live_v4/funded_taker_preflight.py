from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from src.assets import USDC_MINT, WRAPPED_SOL_MINT
from src.jupiter_swap_v2 import JupiterSwapV2Client
from src.launch_burst_route_paper_v2 import validate_contract

PASS = "PASS_LAUNCH_BURST_V4_FUNDED_TAKER_PREFLIGHT"
FAIL = "FAIL_LAUNCH_BURST_V4_FUNDED_TAKER_PREFLIGHT"
FIXTURE_SCHEMA_VERSION = "launch_burst_funded_taker_fixture_v0"
DEFAULT_FIXTURE = Path(__file__).with_name("funded_taker_fixture_v0.frozen.json")
DEFAULT_CONTRACT = (
    Path("benchmarks")
    / "launch_burst_prospective_economic_v1"
    / "pump_route_paper_contract_v2.frozen.json"
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_payload(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _validate_fixture(fixture: dict[str, Any], contract: dict[str, Any]) -> dict[str, bool]:
    validate_contract(contract)
    expected_hash = str(fixture.get("fixture_hash_sha256") or "")
    unhashed = {key: value for key, value in fixture.items() if key != "fixture_hash_sha256"}
    calculated_hash = _sha256_payload(unhashed)

    decimals = int(fixture.get("input_decimals", -1))
    contract_notional_raw = int(round(float(contract["position"]["notional_usd"]) * (10**decimals))) if decimals >= 0 else -1
    contract_slippage = int(contract["costs"]["entry_adverse_slippage_bps"])

    return {
        "fixture_schema_valid": fixture.get("schema_version") == FIXTURE_SCHEMA_VERSION,
        "fixture_status_frozen": fixture.get("status") == "FROZEN",
        "fixture_hash_unchanged": bool(expected_hash) and expected_hash == calculated_hash,
        "route_contract_hash_matches_fixture": (
            fixture.get("route_contract_hash_sha256") == contract.get("contract_hash_sha256")
        ),
        "input_mint_is_usdc": fixture.get("input_mint") == USDC_MINT,
        "input_decimals_are_usdc": decimals == 6,
        "minimum_input_matches_frozen_notional": (
            int(fixture.get("minimum_input_amount_raw", -1)) == contract_notional_raw
        ),
        "slippage_matches_frozen_contract": int(fixture.get("slippage_bps", -1)) == contract_slippage,
        "control_is_wrapped_sol": fixture.get("control_output_mint") == WRAPPED_SOL_MINT,
        "no_adaptive_top_up": fixture.get("no_adaptive_top_up_after_acquisition_starts") is True,
        "read_only_assembly_only": fixture.get("read_only_assembly_only") is True,
        "minimum_sol_positive": int(fixture.get("minimum_sol_lamports", 0)) > 0,
        "taker_identity_frozen": bool(str(fixture.get("taker_public_key_sha256") or "")),
    }


def _rpc_call(rpc_url: str, method: str, params: list[Any]) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    request = Request(
        rpc_url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "crypto-copy-trader/0.3"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Solana RPC returned a non-object payload")
    if payload.get("error") is not None:
        raise RuntimeError(f"Solana RPC {method} error: {payload['error']}")
    return payload.get("result")


def _read_balances(*, rpc_url: str, taker_public_key: str, input_mint: str) -> dict[str, int]:
    balance = _rpc_call(rpc_url, "getBalance", [taker_public_key, {"commitment": "confirmed"}])
    if not isinstance(balance, dict) or balance.get("value") is None:
        raise RuntimeError("getBalance returned an invalid payload")
    sol_lamports = int(balance["value"])

    token_accounts = _rpc_call(
        rpc_url,
        "getTokenAccountsByOwner",
        [
            taker_public_key,
            {"mint": input_mint},
            {"encoding": "jsonParsed", "commitment": "confirmed"},
        ],
    )
    rows = token_accounts.get("value") if isinstance(token_accounts, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("getTokenAccountsByOwner returned an invalid payload")

    input_amount_raw = 0
    for row in rows:
        try:
            info = row["account"]["data"]["parsed"]["info"]
            input_amount_raw += int(info["tokenAmount"]["amount"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("token account payload is malformed") from exc

    return {"sol_lamports": sol_lamports, "input_amount_raw": input_amount_raw}


def _probe_assembly(
    *,
    api_key: str,
    taker_public_key: str,
    input_mint: str,
    output_mint: str,
    amount_raw: int,
    slippage_bps: int,
) -> dict[str, Any]:
    order = JupiterSwapV2Client(api_key=api_key, timeout=10).order(
        input_mint=input_mint,
        output_mint=output_mint,
        amount_raw=amount_raw,
        taker=taker_public_key,
        slippage_bps=slippage_bps,
    )
    return {
        "router": order.router,
        "mode": order.mode,
        "transaction_present": bool(order.transaction),
        "error_code": order.error_code,
        "error_message": order.error_message,
        "in_amount_raw": order.in_amount_raw,
        "out_amount_raw": order.out_amount_raw,
        "in_usd_value": order.in_usd_value,
        "out_usd_value": order.out_usd_value,
        "swap_usd_value": order.swap_usd_value,
        "price_impact_pct_points": order.price_impact_pct_points,
        "observed_at": order.observed_at,
    }


def _probe_passed(probe: dict[str, Any]) -> bool:
    return probe.get("transaction_present") is True and probe.get("error_code") in {None, 0}


def _redact_error(exc: Exception, *secrets: str) -> str:
    text = f"{type(exc).__name__}:{exc}"
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text[:1000]


def run_preflight(
    *,
    fixture_path: Path,
    contract_path: Path,
    rpc_url: str,
    jupiter_api_key: str,
    taker_public_key: str,
    balance_reader: Callable[..., dict[str, int]] = _read_balances,
    assembly_probe: Callable[..., dict[str, Any]] = _probe_assembly,
) -> dict[str, Any]:
    fixture = _read_json(fixture_path)
    contract = _read_json(contract_path)
    fixture_gates = _validate_fixture(fixture, contract)

    env_gates = {
        "rpc_url_present": bool(rpc_url.strip()),
        "jupiter_api_key_present": bool(jupiter_api_key.strip()),
        "taker_public_key_present": bool(taker_public_key.strip()),
        "taker_identity_matches_frozen_fixture": (
            bool(taker_public_key.strip())
            and _sha256_text(taker_public_key.strip()) == fixture.get("taker_public_key_sha256")
        ),
    }
    base_gates = {**fixture_gates, **env_gates}

    report: dict[str, Any] = {
        "type": "launch_burst_v4_funded_taker_preflight_report",
        "classification": FAIL,
        "fixture_hash_sha256": fixture.get("fixture_hash_sha256"),
        "route_contract_hash_sha256": contract.get("contract_hash_sha256"),
        "taker_public_key_sha256": _sha256_text(taker_public_key.strip()) if taker_public_key.strip() else None,
        "minimums": {
            "input_mint": fixture.get("input_mint"),
            "input_amount_raw": int(fixture.get("minimum_input_amount_raw", 0)),
            "sol_lamports": int(fixture.get("minimum_sol_lamports", 0)),
        },
        "balances": None,
        "probes": {
            "known_liquid_control": {"status": "NOT_RUN_CONFIG_GATE"},
            "representative_burst": {"status": "NOT_RUN_CONFIG_GATE"},
        },
        "gates": dict(base_gates),
        "economic_outcomes_opened": False,
        "provider_execute_called": False,
        "interpretation": (
            "This fail-closed preflight validates a frozen funded-taker execution fixture before a prospective "
            "economic acquisition. It may request read-only Jupiter candidate transactions but never signs or "
            "submits them. PASS is operational fixture evidence only, not economic or landed-fill evidence."
        ),
    }

    if not all(base_gates.values()):
        return report

    try:
        balances = balance_reader(
            rpc_url=rpc_url.strip(),
            taker_public_key=taker_public_key.strip(),
            input_mint=str(fixture["input_mint"]),
        )
    except Exception as exc:
        report["balance_error"] = _redact_error(exc, rpc_url, jupiter_api_key)
        report["gates"]["balance_read_ok"] = False
        report["probes"] = {
            "known_liquid_control": {"status": "NOT_RUN_BALANCE_READ_FAILED"},
            "representative_burst": {"status": "NOT_RUN_BALANCE_READ_FAILED"},
        }
        return report

    balances = {
        "input_amount_raw": int(balances.get("input_amount_raw", 0)),
        "sol_lamports": int(balances.get("sol_lamports", 0)),
    }
    report["balances"] = balances
    balance_gates = {
        "balance_read_ok": True,
        "minimum_input_balance_met": balances["input_amount_raw"] >= int(fixture["minimum_input_amount_raw"]),
        "minimum_sol_balance_met": balances["sol_lamports"] >= int(fixture["minimum_sol_lamports"]),
    }
    report["gates"].update(balance_gates)
    if not all(balance_gates.values()):
        report["probes"] = {
            "known_liquid_control": {"status": "NOT_RUN_BALANCE_GATE"},
            "representative_burst": {"status": "NOT_RUN_BALANCE_GATE"},
        }
        return report

    probe_specs = (
        ("known_liquid_control", str(fixture["control_output_mint"])),
        ("representative_burst", str(fixture["representative_burst_output_mint"])),
    )
    for name, output_mint in probe_specs:
        try:
            probe = assembly_probe(
                api_key=jupiter_api_key.strip(),
                taker_public_key=taker_public_key.strip(),
                input_mint=str(fixture["input_mint"]),
                output_mint=output_mint,
                amount_raw=int(fixture["minimum_input_amount_raw"]),
                slippage_bps=int(fixture["slippage_bps"]),
            )
            report["probes"][name] = {"status": "COMPLETED", **probe}
            report["gates"][f"{name}_transaction_assembled"] = _probe_passed(probe)
        except Exception as exc:
            report["probes"][name] = {
                "status": "ERROR",
                "error": _redact_error(exc, jupiter_api_key, rpc_url),
            }
            report["gates"][f"{name}_transaction_assembled"] = False

    report["classification"] = PASS if all(report["gates"].values()) else FAIL
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed funded-taker preflight for Launch Burst V4")
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
        report = run_preflight(
            fixture_path=args.fixture,
            contract_path=args.contract,
            rpc_url=os.environ.get("SOLANA_RPC_URL", ""),
            jupiter_api_key=os.environ.get("JUPITER_API_KEY", ""),
            taker_public_key=os.environ.get("JUPITER_TAKER_PUBLIC_KEY", ""),
        )
    except Exception as exc:
        report = {
            "type": "launch_burst_v4_funded_taker_preflight_report",
            "classification": FAIL,
            "error": _redact_error(
                exc,
                os.environ.get("JUPITER_API_KEY", ""),
                os.environ.get("SOLANA_RPC_URL", ""),
            ),
            "economic_outcomes_opened": False,
            "provider_execute_called": False,
        }

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("classification") == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
