from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from benchmarks.launch_burst_control_taker_sim_v0 import run as sim
from benchmarks.launch_burst_control_taker_sim_v0.run_helius_holders import (
    _discover_control_via_helius_holders,
)
from benchmarks.launch_burst_control_taker_sim_v0.smart_ladder_25 import (
    run_smart_ladder_25,
)
from benchmarks.launch_burst_prospective_route_live_v3 import live as v3
from benchmarks.launch_burst_prospective_route_live_v4 import live as v4

VERSION = "launch_burst_control_taker_sim_v4_smart_ladder_25_v0"
DEFAULT_ARTIFACTS_ROOT = Path("artifacts") / VERSION
DEFAULT_POLICY = Path(__file__).with_name("smart_ladder_25_policy_v0.frozen.json")
DEFAULT_CONTRACT = sim.DEFAULT_CONTRACT
DEFAULT_FIXTURE = sim.DEFAULT_FIXTURE


def _resolve_sim_control(
    *,
    fixture: dict[str, Any],
    rpc_url: str,
    helius_api_key: str,
    control_taker_override: str | None,
    control_meta_override: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    taker = str(control_taker_override or "").strip()
    if taker:
        if not isinstance(control_meta_override, dict):
            raise ValueError("control_taker_override requires control_meta_override")
        expected_sha = hashlib.sha256(taker.encode("utf-8")).hexdigest()
        if str(control_meta_override.get("owner_public_key_sha256") or "") != expected_sha:
            raise ValueError("preflight control metadata does not match control taker public key")
        if int(control_meta_override.get("token_account_amount_raw") or 0) < int(fixture["minimum_input_amount_raw"]):
            raise ValueError("preflight control metadata is below frozen USDC floor")
        if int(control_meta_override.get("sol_lamports") or 0) < int(fixture["minimum_sol_lamports"]):
            raise ValueError("preflight control metadata is below frozen SOL floor")
        return taker, {
            **control_meta_override,
            "control_resolution_mode": "EXACT_PREFLIGHT_REUSE",
        }

    discovered, metadata = _discover_control_via_helius_holders(
        fixture=fixture,
        rpc_url=rpc_url,
        helius_api_key=helius_api_key,
    )
    return discovered, {
        **metadata,
        "control_resolution_mode": "DISCOVERED_AT_RUN_START",
    }


async def run_sim_v4(
    *,
    contract_path: Path,
    fixture_path: Path,
    policy_path: Path,
    artifacts_root: Path,
    duration_seconds: int,
    rotation_seconds: float,
    chunk_max_bytes: int,
    cargo: str,
    decoder_target_dir: Path,
    helius_api_key: str,
    jupiter_api_key: str,
    rpc_url: str,
    rpc_fallback_urls: tuple[str, ...],
    control_taker_override: str | None = None,
    control_meta_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = sim._read_json(contract_path)
    fixture = sim._read_json(fixture_path)
    policy = sim._read_json(policy_path)
    route_hash = str(contract["contract_hash_sha256"])
    if fixture.get("route_contract_hash_sha256") != route_hash:
        raise ValueError("fixture/route contract hash mismatch")
    if policy.get("route_contract_hash_sha256") != route_hash:
        raise ValueError("SMART-LADDER-25/route contract hash mismatch")
    if policy.get("sample_offsets_seconds_from_entry") != [5, 10, 20, 30, 45, 60]:
        raise ValueError("SMART-LADDER-25 observation grid changed")
    if int((policy.get("runner") or {}).get("horizon_seconds_from_entry") or 0) != 60:
        raise ValueError("SMART-LADDER-25 final runner exit must be +60s")
    if not helius_api_key or not jupiter_api_key or not rpc_url:
        raise ValueError("HELIUS_API_KEY, JUPITER_API_KEY and SOLANA_RPC_URL are required")

    control_taker, control_meta = await asyncio.to_thread(
        _resolve_sim_control,
        fixture=fixture,
        rpc_url=rpc_url,
        helius_api_key=helius_api_key,
        control_taker_override=control_taker_override,
        control_meta_override=control_meta_override,
    )
    sim._SIM_CONTEXT.clear()
    sim._SIM_CONTEXT.update({"policy": policy, "paths": []})

    original_dispatch = v3._dispatch_snapshot

    async def dispatch_with_sim_provider(
        *,
        episode_key: str,
        token_mint: str,
        snapshot: dict[str, Any],
        contract: dict[str, Any],
        systems_only: bool,
        provider_factory=None,
        provider_kwargs: dict[str, Any] | None = None,
    ):
        del provider_factory
        return await original_dispatch(
            episode_key=episode_key,
            token_mint=token_mint,
            snapshot=snapshot,
            contract=contract,
            systems_only=systems_only,
            provider_factory=sim._capture_selected_episode_sim,
            provider_kwargs=provider_kwargs,
        )

    v3._dispatch_snapshot = dispatch_with_sim_provider
    try:
        base_report = await v4.run_live(
            contract_path=contract_path,
            artifacts_root=artifacts_root,
            duration_seconds=duration_seconds,
            rotation_seconds=rotation_seconds,
            chunk_max_bytes=chunk_max_bytes,
            cargo=cargo,
            decoder_target_dir=decoder_target_dir,
            helius_api_key=helius_api_key,
            jupiter_api_key=jupiter_api_key,
            taker_public_key=control_taker,
            rpc_url=rpc_url,
            rpc_fallback_urls=rpc_fallback_urls,
            systems_only=False,
        )
    finally:
        v3._dispatch_snapshot = original_dispatch

    run_dir = Path(base_report["artifacts"]["report"]).resolve().parent
    route_result_path = Path(base_report["artifacts"]["result"]).resolve()
    paths_path = run_dir / "market-paths-smart-ladder-25-v0.json"
    smart_result_path = run_dir / "smart-ladder-25-result-v0.json"
    wrapper_report_path = run_dir / "simulation-report-v4-smart-ladder-25-v0.json"

    paths = {
        "type": "launch_burst_control_taker_market_paths_smart_ladder_25_v0",
        "version": VERSION,
        "route_contract_hash_sha256": route_hash,
        "smart_exit_policy_hash_sha256": policy["policy_hash_sha256"],
        "sample_offsets_seconds_from_entry": policy["sample_offsets_seconds_from_entry"],
        "simulation_control_taker": {
            **control_meta,
            "address_redacted": True,
            "signing_or_submission_performed": False,
        },
        "episodes": sorted(
            sim._SIM_CONTEXT["paths"],
            key=lambda x: (
                int((x.get("entry_quote") or {}).get("observed_at") or 0),
                x["token_mint"],
            ),
        ),
    }
    sim._write_json(paths_path, paths)

    smart = run_smart_ladder_25(
        contract_path=contract_path,
        policy_path=policy_path,
        route_result_path=route_result_path,
        market_paths_path=paths_path,
        output_path=smart_result_path,
    )
    paired = int(smart.get("paired_trade_count") or 0)
    base_pass = base_report.get("classification") == v4.PASS_LIVE
    smart_pass = smart.get("classification") == "PASS_LAUNCH_BURST_CONTROL_TAKER_SMART_LADDER_25_SIM_V0"

    report = {
        "type": "launch_burst_control_taker_sim_report_v4_smart_ladder_25_v0",
        "version": VERSION,
        "classification": (
            "PASS_LAUNCH_BURST_CONTROL_TAKER_SIM_V4_SMART_LADDER_25_V0"
            if base_pass and smart_pass
            else "FAIL_LAUNCH_BURST_CONTROL_TAKER_SIM_V4_SMART_LADDER_25_V0"
        ),
        "economic_interpretation": "SIMULATION_RESULT_AVAILABLE" if paired > 0 else "INCONCLUSIVE_NO_PAIRED_TRADES",
        "route_contract_hash_sha256": route_hash,
        "smart_exit_policy_hash_sha256": policy["policy_hash_sha256"],
        "paired_trade_count": paired,
        "base_v4_report": base_report,
        "simulation_control_taker": {
            **control_meta,
            "address_redacted": True,
            "signing_or_submission_performed": False,
        },
        "artifacts": {
            "fixed_60s_route_result": str(route_result_path),
            "market_paths": str(paths_path),
            "smart_ladder_25_result": str(smart_result_path),
            "simulation_report": str(wrapper_report_path),
        },
        "guardrails": {
            "official_v4_funded_taker_gate_opened": False,
            "official_v4_economic_verdict_changed": False,
            "public_control_address_only_for_read_only_assembly": True,
            "private_key_required": False,
            "transaction_signed": False,
            "transaction_submitted": False,
            "fixed_60s_is_primary_benchmark": True,
            "smart_ladder_25_is_exploratory": True,
            "smart_ladder_trailing_stop": False,
            "smart_ladder_final_runner_exit_seconds": 60,
            "v4_direct_decoder_path_used": True,
        },
        "interpretation": (
            "No-capital V4 route-shadow simulation. A public funded control address is used only so Jupiter can assemble "
            "candidate BUY transactions; nothing is signed or submitted. Fixed +60s is primary. SMART-LADDER-25 V0 is "
            "preregistered exploratory evidence with +20/+50/+100 25% scale-outs and the final 25% closed at +60s."
        ),
    }
    sim._write_json(wrapper_report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="V4 no-capital Launch Burst economic simulation with corrected SMART-LADDER-25 V0")
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
                    "classification": "FAIL_LAUNCH_BURST_CONTROL_TAKER_SIM_V4_SMART_LADDER_25_V0",
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
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if str(report.get("classification", "")).startswith("PASS_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
