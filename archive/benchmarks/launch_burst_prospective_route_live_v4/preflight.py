from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from benchmarks.launch_burst_prospective_route_live_v3.live import (
    EXPECTED_ROUTE_CONTRACT_HASH,
    _build_decoder,
    _read_json,
)
from benchmarks.launch_burst_prospective_route_live_v4.live import _default_decoder_target
from src.launch_burst_route_paper_v2 import validate_contract

PASS = "PASS_LAUNCH_BURST_V4_PREFLIGHT"
FAIL = "FAIL_LAUNCH_BURST_V4_PREFLIGHT"


def run_preflight(
    *,
    contract_path: Path,
    cargo: str,
    decoder_target_dir: Path,
    systems_only: bool,
    build_decoder: bool,
) -> dict:
    contract = _read_json(contract_path)
    validate_contract(contract)
    contract_hash_ok = contract.get("contract_hash_sha256") == EXPECTED_ROUTE_CONTRACT_HASH

    env = {
        "HELIUS_API_KEY": bool(os.environ.get("HELIUS_API_KEY", "").strip()),
        "JUPITER_API_KEY": bool(os.environ.get("JUPITER_API_KEY", "").strip()),
        "JUPITER_TAKER_PUBLIC_KEY": bool(os.environ.get("JUPITER_TAKER_PUBLIC_KEY", "").strip()),
        "SOLANA_RPC_URL": bool(os.environ.get("SOLANA_RPC_URL", "").strip()),
    }
    required_env_ok = env["HELIUS_API_KEY"] if systems_only else all(env.values())

    target = decoder_target_dir.resolve()
    decoder_build = None
    decoder_ok = True
    if build_decoder:
        decoder_build = _build_decoder(cargo=cargo, target_dir=target)
        decoder_ok = (
            decoder_build.get("process_return_code") == 0
            and decoder_build.get("binary_exists") is True
        )

    gates = {
        "contract_hash_unchanged": contract_hash_ok,
        "required_env_present": required_env_ok,
        "decoder_target_absolute": target.is_absolute(),
        "decoder_build_ok": decoder_ok,
    }
    return {
        "type": "launch_burst_v4_preflight_report",
        "classification": PASS if all(gates.values()) else FAIL,
        "mode": "systems_only" if systems_only else "route_paper_economic",
        "contract_hash_sha256": contract.get("contract_hash_sha256"),
        "expected_contract_hash_sha256": EXPECTED_ROUTE_CONTRACT_HASH,
        "decoder_target_dir": str(target),
        "env_present": env,
        "decoder_build": decoder_build,
        "gates": gates,
        "provider_calls_enabled": False,
        "economic_outcomes_opened": False,
        "interpretation": (
            "Preflight validates local configuration only. It does not connect to Helius, Jupiter, "
            "or Solana RPC and opens no economic outcomes."
        ),
    }


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Offline preflight for Launch Burst V4")
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("benchmarks")
        / "launch_burst_prospective_economic_v1"
        / "pump_route_paper_contract_v2.frozen.json",
    )
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--decoder-target-dir", type=Path, default=None)
    parser.add_argument("--systems-only", action="store_true")
    parser.add_argument("--skip-decoder-build", action="store_true")
    args = parser.parse_args()

    try:
        report = run_preflight(
            contract_path=args.contract,
            cargo=args.cargo,
            decoder_target_dir=args.decoder_target_dir or _default_decoder_target(),
            systems_only=bool(args.systems_only),
            build_decoder=not bool(args.skip_decoder_build),
        )
    except Exception as exc:
        print(json.dumps({"classification": FAIL, "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["classification"] == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
