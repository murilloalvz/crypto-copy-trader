from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from benchmarks.launch_burst_control_taker_sim_v0 import run as sim
from benchmarks.launch_burst_control_taker_sim_v0.run_helius_holders import (
    _discover_control_via_helius_holders,
)
from benchmarks.launch_burst_control_taker_sim_v0.run_v4_smart_ladder_25 import (
    DEFAULT_CONTRACT,
    DEFAULT_FIXTURE,
    DEFAULT_POLICY as DEFAULT_SMART_POLICY,
)
from benchmarks.launch_burst_control_taker_sim_v0.smart_ladder_25 import _validate_policy as validate_smart_policy
from benchmarks.launch_burst_control_taker_sim_v0.run_v4_sniper_v1 import (
    DEFAULT_SNIPER_POLICY,
    _screening_preflight,
)
from benchmarks.launch_burst_prospective_route_live_v4 import funded_taker_preflight as ft


VERSION = "launch_burst_sniper_v1_read_only_preflight"
PASS = "PASS_LAUNCH_BURST_SNIPER_V1_PREFLIGHT"
FAIL = "FAIL_LAUNCH_BURST_SNIPER_V1_PREFLIGHT"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _probe_ok(probe: dict[str, Any]) -> bool:
    return probe.get("transaction_present") is True and probe.get("error_code") in {None, 0}


def run_preflight(
    *,
    contract_path: Path,
    fixture_path: Path,
    smart_policy_path: Path,
    sniper_policy_path: Path,
    duration_seconds: int,
    helius_api_key: str,
    jupiter_api_key: str,
    rpc_url: str,
    discover_control: Callable[..., tuple[str, dict[str, Any]]] = _discover_control_via_helius_holders,
    assembly_probe: Callable[..., dict[str, Any]] = ft._probe_assembly,
) -> dict[str, Any]:
    sniper = _screening_preflight(
        sniper_policy_path=sniper_policy_path,
        duration_seconds=duration_seconds,
    )
    contract = _read_json(contract_path)
    fixture = _read_json(fixture_path)
    smart_policy = _read_json(smart_policy_path)

    fixture_gates = ft._validate_fixture(fixture, contract)
    route_hash = str(contract.get("contract_hash_sha256") or "")
    validate_smart_policy(smart_policy, route_contract_hash=route_hash)

    env_gates = {
        "helius_api_key_present": bool(helius_api_key.strip()),
        "jupiter_api_key_present": bool(jupiter_api_key.strip()),
        "solana_rpc_url_present": bool(rpc_url.strip()),
    }
    report: dict[str, Any] = {
        "type": "launch_burst_sniper_v1_preflight_report",
        "version": VERSION,
        "classification": FAIL,
        "sniper_policy": sniper,
        "route_contract_hash_sha256": route_hash,
        "smart_exit_policy_hash_sha256": smart_policy.get("policy_hash_sha256"),
        "fixture_hash_sha256": fixture.get("fixture_hash_sha256"),
        "fixture_gates": fixture_gates,
        "environment_gates": env_gates,
        "public_control": None,
        "assembly_probes": {
            "known_liquid_control": {"status": "NOT_RUN"},
            "representative_burst": {"status": "NOT_RUN"},
        },
        "gates": {},
        "economic_outcomes_opened": False,
        "transaction_signed": False,
        "transaction_submitted": False,
        "provider_execute_called": False,
        "interpretation": (
            "Read-only support preflight for the preregistered Sniper V1 screening. It validates the frozen "
            "policies and fixture, discovers a public funded control address, and asks Jupiter only to assemble "
            "candidate transactions. Nothing is signed or submitted, and no economic outcome is opened."
        ),
    }

    config_ok = all(fixture_gates.values()) and all(env_gates.values())
    report["gates"]["frozen_configuration_valid"] = config_ok
    if not config_ok:
        return report

    control_taker, control_meta = discover_control(fixture=fixture, rpc_url=rpc_url.strip())
    report["public_control"] = {**control_meta, "address_redacted": True}
    report["gates"]["public_control_discovered"] = True

    common = {
        "api_key": jupiter_api_key.strip(),
        "taker_public_key": control_taker,
        "input_mint": str(fixture["input_mint"]),
        "amount_raw": int(fixture["minimum_input_amount_raw"]),
        "slippage_bps": int(fixture["slippage_bps"]),
    }
    known = assembly_probe(
        output_mint=str(fixture["control_output_mint"]),
        **common,
    )
    representative = assembly_probe(
        output_mint=str(fixture["representative_burst_output_mint"]),
        **common,
    )
    report["assembly_probes"] = {
        "known_liquid_control": known,
        "representative_burst": representative,
    }
    report["gates"]["known_liquid_control_assembly"] = _probe_ok(known)
    report["gates"]["representative_burst_assembly"] = _probe_ok(representative)
    report["gates"]["all_read_only_support_checks_pass"] = all(report["gates"].values())
    if report["gates"]["all_read_only_support_checks_pass"]:
        report["classification"] = PASS
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only preregistered Sniper V1 support preflight")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--smart-policy", type=Path, default=DEFAULT_SMART_POLICY)
    parser.add_argument("--sniper-policy", type=Path, default=DEFAULT_SNIPER_POLICY)
    parser.add_argument("--duration-seconds", type=int, default=900)
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()

    env_file = args.env_file or (Path.cwd() / ".env")
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

    helius_key = os.environ.get("HELIUS_API_KEY", "").strip()
    jupiter_key = os.environ.get("JUPITER_API_KEY", "").strip()
    rpc_url = os.environ.get("SOLANA_RPC_URL", "").strip()
    try:
        report = run_preflight(
            contract_path=args.contract,
            fixture_path=args.fixture,
            smart_policy_path=args.smart_policy,
            sniper_policy_path=args.sniper_policy,
            duration_seconds=args.duration_seconds,
            helius_api_key=helius_key,
            jupiter_api_key=jupiter_key,
            rpc_url=rpc_url,
        )
    except Exception as exc:
        report = {
            "type": "launch_burst_sniper_v1_preflight_report",
            "version": VERSION,
            "classification": FAIL,
            "economic_outcomes_opened": False,
            "transaction_signed": False,
            "transaction_submitted": False,
            "provider_execute_called": False,
            "error": sim._redacted_error(exc, helius_key, jupiter_key, rpc_url),
        }

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("classification") == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
