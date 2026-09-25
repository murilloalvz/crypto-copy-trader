from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from benchmarks.launch_burst_prospective_route_live_v4 import funded_taker_preflight as shared
from benchmarks.post_transition_reacceleration_v0.economic_collector import (
    DEFAULT_CONTRACT,
    load_and_validate_contract,
)
from src.assets import USDC_MINT, WRAPPED_SOL_MINT


PASS = "PASS_POST_TRANSITION_FUNDED_TAKER_PREFLIGHT_V0"
FAIL = "FAIL_POST_TRANSITION_FUNDED_TAKER_PREFLIGHT_V0"
FIXTURE_SCHEMA_VERSION = "post_transition_funded_taker_fixture_v0"
DEFAULT_FIXTURE = Path(__file__).with_name("funded_taker_fixture_v0.frozen.json")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_payload(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _validate_fixture(fixture: dict[str, Any], contract: dict[str, Any]) -> dict[str, bool]:
    expected_fixture_hash = str(fixture.get("fixture_hash_sha256") or "")
    unhashed = {k: v for k, v in fixture.items() if k != "fixture_hash_sha256"}
    calculated_fixture_hash = _sha256_payload(unhashed)

    decimals = int(fixture.get("input_decimals", -1))
    notional_raw = int(
        round(float(contract["position"]["notional_usd"]) * (10**decimals))
    ) if decimals >= 0 else -1

    return {
        "fixture_schema_valid": fixture.get("schema_version") == FIXTURE_SCHEMA_VERSION,
        "fixture_status_frozen": fixture.get("status") == "FROZEN",
        "fixture_hash_unchanged": (
            bool(expected_fixture_hash)
            and expected_fixture_hash == calculated_fixture_hash
        ),
        "collector_contract_hash_matches_fixture": (
            fixture.get("economic_collector_contract_hash_sha256")
            == contract.get("contract_hash_sha256")
        ),
        "input_mint_is_usdc": fixture.get("input_mint") == USDC_MINT,
        "input_decimals_are_usdc": decimals == 6,
        "minimum_input_matches_frozen_notional": (
            int(fixture.get("minimum_input_amount_raw", -1)) == notional_raw
        ),
        "minimum_sol_matches_reused_operational_floor": (
            int(fixture.get("minimum_sol_lamports", -1)) == 10_000_000
        ),
        "control_is_wrapped_sol": (
            fixture.get("control_output_mint") == WRAPPED_SOL_MINT
        ),
        "slippage_matches_frozen_contract": (
            int(fixture.get("slippage_bps", -1))
            == int(contract["costs"]["entry_adverse_slippage_bps"])
        ),
        "no_adaptive_top_up": (
            fixture.get("no_adaptive_top_up_after_acquisition_starts") is True
        ),
        "read_only_assembly_only": fixture.get("read_only_assembly_only") is True,
        "no_cohort_token_probe_before_fresh_run": (
            fixture.get("cohort_token_probe_before_fresh_run") is False
        ),
        "taker_identity_frozen": bool(
            str(fixture.get("taker_public_key_sha256") or "")
        ),
    }


def run_preflight(
    *,
    fixture_path: Path = DEFAULT_FIXTURE,
    rpc_url: str,
    jupiter_api_key: str,
    taker_public_key: str,
    balance_reader: Callable[..., dict[str, int]] = shared._read_balances,
    assembly_probe: Callable[..., dict[str, Any]] = shared._probe_assembly,
) -> dict[str, Any]:
    fixture = _read_json(fixture_path)
    contract = load_and_validate_contract(DEFAULT_CONTRACT)
    fixture_gates = _validate_fixture(fixture, contract)

    taker = taker_public_key.strip()
    env_gates = {
        "rpc_url_present": bool(rpc_url.strip()),
        "jupiter_api_key_present": bool(jupiter_api_key.strip()),
        "taker_public_key_present": bool(taker),
        "taker_identity_matches_frozen_fixture": (
            bool(taker)
            and _sha256_text(taker)
            == fixture.get("taker_public_key_sha256")
        ),
    }

    report: dict[str, Any] = {
        "type": "post_transition_funded_taker_preflight_report_v0",
        "version": "post_transition_funded_taker_preflight_v0",
        "classification": FAIL,
        "fixture_hash_sha256": fixture.get("fixture_hash_sha256"),
        "contract_hash_sha256": contract.get("contract_hash_sha256"),
        "taker_public_key_sha256": _sha256_text(taker) if taker else None,
        "minimums": {
            "input_mint": fixture.get("input_mint"),
            "input_amount_raw": int(fixture.get("minimum_input_amount_raw", 0)),
            "sol_lamports": int(fixture.get("minimum_sol_lamports", 0)),
        },
        "balances": None,
        "probe": {"status": "NOT_RUN_CONFIG_GATE"},
        "gates": {**fixture_gates, **env_gates},
        "cohort_tokens_queried": 0,
        "fresh_economic_outcomes_opened": False,
        "provider_execute_called": False,
        "transaction_submitted": False,
        "live_money": False,
        "interpretation": (
            "Operational funded-taker readiness only. The probe is USDC->WSOL "
            "with the frozen US$25 notional and frozen slippage. It may request "
            "an assembled Jupiter transaction but never signs or submits it and "
            "never queries a Post-Transition cohort token."
        ),
    }

    if not all(report["gates"].values()):
        return report

    try:
        balances = balance_reader(
            rpc_url=rpc_url.strip(),
            taker_public_key=taker,
            input_mint=str(fixture["input_mint"]),
        )
    except Exception as exc:
        report["gates"]["balance_read_ok"] = False
        report["balance_error"] = shared._redact_error(
            exc, rpc_url, jupiter_api_key
        )
        report["probe"] = {"status": "NOT_RUN_BALANCE_READ_FAILED"}
        return report

    balances = {
        "input_amount_raw": int(balances.get("input_amount_raw", 0)),
        "sol_lamports": int(balances.get("sol_lamports", 0)),
    }
    report["balances"] = balances
    balance_gates = {
        "balance_read_ok": True,
        "minimum_input_balance_met": (
            balances["input_amount_raw"]
            >= int(fixture["minimum_input_amount_raw"])
        ),
        "minimum_sol_balance_met": (
            balances["sol_lamports"]
            >= int(fixture["minimum_sol_lamports"])
        ),
    }
    report["gates"].update(balance_gates)
    if not all(balance_gates.values()):
        report["probe"] = {"status": "NOT_RUN_BALANCE_GATE"}
        return report

    try:
        probe = assembly_probe(
            api_key=jupiter_api_key.strip(),
            taker_public_key=taker,
            input_mint=str(fixture["input_mint"]),
            output_mint=str(fixture["control_output_mint"]),
            amount_raw=int(fixture["minimum_input_amount_raw"]),
            slippage_bps=int(fixture["slippage_bps"]),
        )
        report["probe"] = {"status": "COMPLETED", **probe}
        report["gates"]["control_transaction_assembled"] = (
            probe.get("transaction_present") is True
            and probe.get("error_code") in {None, 0}
        )
    except Exception as exc:
        report["probe"] = {
            "status": "ERROR",
            "error": shared._redact_error(exc, rpc_url, jupiter_api_key),
        }
        report["gates"]["control_transaction_assembled"] = False

    report["classification"] = PASS if all(report["gates"].values()) else FAIL
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Post-Transition funded-taker readiness preflight"
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
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
            rpc_url=os.environ.get("SOLANA_RPC_URL", ""),
            jupiter_api_key=os.environ.get("JUPITER_API_KEY", ""),
            taker_public_key=os.environ.get("JUPITER_TAKER_PUBLIC_KEY", ""),
        )
    except Exception as exc:
        report = {
            "type": "post_transition_funded_taker_preflight_report_v0",
            "version": "post_transition_funded_taker_preflight_v0",
            "classification": FAIL,
            "error": shared._redact_error(
                exc,
                os.environ.get("JUPITER_API_KEY", ""),
                os.environ.get("SOLANA_RPC_URL", ""),
            ),
            "cohort_tokens_queried": 0,
            "fresh_economic_outcomes_opened": False,
            "provider_execute_called": False,
            "transaction_submitted": False,
            "live_money": False,
        }

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("classification") == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
