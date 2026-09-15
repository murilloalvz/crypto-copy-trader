from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from benchmarks.launch_burst_prospective_route_live_v4 import no_funds_assembly_diagnostic as diag


HELIUS_MAINNET_RPC_PREFIX = "https://mainnet.helius-rpc.com/?api-key="


def _helius_rpc_url(api_key: str) -> str:
    key = api_key.strip()
    if not key:
        raise ValueError("HELIUS_API_KEY is required")
    return HELIUS_MAINNET_RPC_PREFIX + key


def main() -> int:
    parser = argparse.ArgumentParser(
        description="No-funds Launch Burst V4 assembly diagnostic using Helius RPC for public-control discovery"
    )
    parser.add_argument("--fixture", type=Path, default=diag.DEFAULT_FIXTURE)
    parser.add_argument("--contract", type=Path, default=diag.DEFAULT_CONTRACT)
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()

    env_file = args.env_file
    if env_file is None:
        candidate = Path.cwd() / ".env"
        env_file = candidate if candidate.exists() else None
    if env_file is not None and env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

    helius_api_key = os.environ.get("HELIUS_API_KEY", "")
    jupiter_api_key = os.environ.get("JUPITER_API_KEY", "")
    frozen_taker = os.environ.get("JUPITER_TAKER_PUBLIC_KEY", "")

    try:
        rpc_url = _helius_rpc_url(helius_api_key)
        report = diag.run_diagnostic(
            fixture_path=args.fixture,
            contract_path=args.contract,
            rpc_url=rpc_url,
            jupiter_api_key=jupiter_api_key,
            frozen_taker_public_key=frozen_taker,
        )
        report["diagnostic_rpc_source"] = "helius_mainnet"
    except Exception as exc:
        report = {
            "type": "launch_burst_v4_no_funds_assembly_diagnostic",
            "classification": diag.NOT_CONFIRMED,
            "diagnostic_only": True,
            "official_funded_taker_gate_passed": False,
            "economic_outcomes_opened": False,
            "provider_execute_called": False,
            "diagnostic_rpc_source": "helius_mainnet",
            "error": diag.ft._redact_error(
                exc,
                helius_api_key,
                jupiter_api_key,
            ),
        }

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
