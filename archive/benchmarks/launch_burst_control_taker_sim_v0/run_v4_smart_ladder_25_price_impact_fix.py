from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from benchmarks.launch_burst_control_taker_sim_v0 import run as sim
from benchmarks.launch_burst_control_taker_sim_v0.price_impact_semantics_fix_v0 import (
    FIX_VERSION,
    JUPITER_SWAP_V2_DOC,
    patched_price_impact_semantics,
)
from benchmarks.launch_burst_control_taker_sim_v0.run_v4_smart_ladder_25 import (
    DEFAULT_CONTRACT,
    DEFAULT_FIXTURE,
    DEFAULT_POLICY,
    run_sim_v4,
)
from benchmarks.launch_burst_prospective_route_live_v3 import live as v3
from benchmarks.launch_burst_prospective_route_live_v4 import live as v4

VERSION = "launch_burst_control_taker_sim_v4_smart_ladder_25_price_impact_fix_v0"
PASS = "PASS_LAUNCH_BURST_CONTROL_TAKER_SIM_V4_SMART_LADDER_25_PRICE_IMPACT_FIX_V0"
DEFAULT_ARTIFACTS_ROOT = Path("artifacts") / VERSION


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "V4 no-capital Launch Burst economic simulation with corrected Jupiter "
            "negative priceImpact semantics and frozen SMART-LADDER-25 V0"
        )
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--duration-seconds", type=int, default=300)
    parser.add_argument("--rotation-seconds", type=float, default=v3.DEFAULT_ROTATION_SECONDS)
    parser.add_argument("--chunk-max-mib", type=int, default=v3.DEFAULT_CHUNK_MAX_BYTES // (1024 * 1024))
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--decoder-target-dir", type=Path, default=None)
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()

    env_file = args.env_file or (Path.cwd() / ".env")
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)

    fallback_urls = tuple(
        item.strip()
        for item in os.environ.get("SOLANA_RPC_FALLBACK_URLS", "").split(",")
        if item.strip()
    )

    try:
        with patched_price_impact_semantics():
            report = asyncio.run(
                run_sim_v4(
                    contract_path=args.contract,
                    fixture_path=args.fixture,
                    policy_path=args.policy,
                    artifacts_root=args.artifacts_root,
                    duration_seconds=args.duration_seconds,
                    rotation_seconds=args.rotation_seconds,
                    chunk_max_bytes=args.chunk_max_mib * 1024 * 1024,
                    cargo=args.cargo,
                    decoder_target_dir=args.decoder_target_dir or v4._default_decoder_target(),
                    helius_api_key=os.environ.get("HELIUS_API_KEY", "").strip(),
                    jupiter_api_key=os.environ.get("JUPITER_API_KEY", "").strip(),
                    rpc_url=os.environ.get("SOLANA_RPC_URL", "").strip(),
                    rpc_fallback_urls=fallback_urls,
                )
            )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": "FAIL_LAUNCH_BURST_CONTROL_TAKER_SIM_V4_SMART_LADDER_25_PRICE_IMPACT_FIX_V0",
                    "error": sim._redacted_error(
                        exc,
                        os.environ.get("HELIUS_API_KEY", ""),
                        os.environ.get("JUPITER_API_KEY", ""),
                        os.environ.get("SOLANA_RPC_URL", ""),
                    ),
                },
                indent=2,
            )
        )
        return 2

    upstream_classification = str(report.get("classification") or "")
    report["version"] = VERSION
    report["upstream_v4_classification"] = upstream_classification
    if upstream_classification.startswith("PASS_"):
        report["classification"] = PASS
    report["price_impact_semantics_fix"] = {
        "version": FIX_VERSION,
        "jupiter_swap_v2_documentation": JUPITER_SWAP_V2_DOC,
        "negative_finite_price_impact_allowed": True,
        "upper_bound_still_frozen_at_pct_points": 2.0,
        "frozen_contract_changed": False,
    }
    report.setdefault("guardrails", {})["price_impact_semantics_fix_applied"] = True
    report["guardrails"]["historical_v4_runner_unchanged"] = True
    report["guardrails"]["upstream_failure_never_promoted_to_pass"] = True

    report_path = Path(str(report["artifacts"]["simulation_report"]))
    sim._write_json(report_path, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if str(report.get("classification", "")).startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
