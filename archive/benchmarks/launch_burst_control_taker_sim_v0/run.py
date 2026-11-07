from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import time
from typing import Any

from dotenv import load_dotenv

from benchmarks.helius_standard_wss_shadow_v0.collect import redact_secret
from benchmarks.launch_burst_prospective_route_live_v4 import funded_taker_preflight as ft
from benchmarks.launch_burst_prospective_route_live_v4.no_funds_assembly_diagnostic import _discover_public_funded_control
from benchmarks.launch_burst_prospective_route_paper_v2 import live as live_v2
from benchmarks.launch_burst_control_taker_sim_v0.smart_exit import run_smart_exit
from src.assets import USDC_MINT
from src.jupiter_swap_v2 import JupiterOrderError, JupiterSwapV2Client, jupiter_order_to_causal_quote
from src.launch_burst_route_paper_v2 import selection_decision, validate_contract
from src.solana import SolanaRPCError

VERSION = "launch_burst_control_taker_sim_v0"
DEFAULT_DURATION_SECONDS = 600
DEFAULT_ARTIFACTS_ROOT = Path("artifacts") / VERSION
DEFAULT_CONTRACT = Path("benchmarks") / "launch_burst_prospective_economic_v1" / "pump_route_paper_contract_v2.frozen.json"
DEFAULT_FIXTURE = Path("benchmarks") / "launch_burst_prospective_route_live_v4" / "funded_taker_fixture_v0.frozen.json"
DEFAULT_POLICY = Path(__file__).with_name("smart_exit_policy_v0.frozen.json")
USDC_DECIMALS = 6
_SIM_CONTEXT: dict[str, Any] = {}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _redacted_error(exc: Exception, *secrets: str) -> str:
    text = f"{type(exc).__name__}:{exc}"
    for secret in secrets:
        if secret:
            text = redact_secret(text, secret)
    return text[:700]


def _discover_control(*, fixture: dict[str, Any], rpc_url: str) -> tuple[str, dict[str, Any]]:
    control = _discover_public_funded_control(
        rpc_url=rpc_url,
        input_mint=str(fixture["input_mint"]),
        minimum_input_amount_raw=int(fixture["minimum_input_amount_raw"]),
        minimum_sol_lamports=int(fixture["minimum_sol_lamports"]),
        rpc_call=ft._rpc_call,
    )
    address = str(control.pop("owner_public_key"))
    return address, {
        "owner_public_key_sha256": control.get("owner_public_key_sha256"),
        "token_account_amount_raw": int(control.get("token_account_amount_raw") or 0),
        "sol_lamports": int(control.get("sol_lamports") or 0),
        "candidates_checked": int(control.get("candidates_checked") or 0),
    }


async def _capture_selected_episode_sim(
    *, episode_key: str, token_mint: str, snapshot: dict[str, Any],
    contract: dict[str, Any], jupiter_api_key: str, taker_public_key: str,
    rpc_url: str, rpc_fallback_urls: tuple[str, ...],
) -> dict[str, Any]:
    policy = _SIM_CONTEXT["policy"]
    quotes: list[dict[str, Any]] = []
    path_marks: list[dict[str, Any]] = []
    collection: dict[str, Any] = {
        "snapshot_frozen_wall_ns": time.time_ns(),
        "provider_calls_started": False,
        "entry_status": None,
        "simulation_scope": "PUBLIC_CONTROL_ASSEMBLY_ROUTE_SHADOW_NO_SIGN_NO_SUBMIT",
    }
    admitted, reason = selection_decision(snapshot, contract)
    if not admitted:
        collection["entry_status"] = reason
        return live_v2._episode(episode_key=episode_key, token_mint=token_mint, snapshot=snapshot, quotes=quotes, collection=collection)

    entry_ready_at = live_v2._entry_ready_second(snapshot, contract)
    collection["entry_ready_at"] = entry_ready_at
    if time.time() < entry_ready_at:
        await asyncio.sleep(max(0.0, entry_ready_at - time.time()))
    deadline_at = entry_ready_at + int(contract["entry"]["max_quote_wait_seconds"])
    if time.time() > deadline_at:
        collection["entry_status"] = "ENTRY_WINDOW_MISSED_BY_PROCESSING"
        episode = live_v2._episode(episode_key=episode_key, token_mint=token_mint, snapshot=snapshot, quotes=quotes, collection=collection)
        _SIM_CONTEXT["paths"].append({"episode_key": episode_key, "token_mint": token_mint, "entry_quote": None, "path": [], "collection": collection})
        return episode

    collection["provider_calls_started"] = True
    try:
        decimals = await asyncio.to_thread(live_v2._resolve_decimals, token_mint, rpc_url=rpc_url, fallback_urls=rpc_fallback_urls)
        amount_raw = int(round(float(contract["position"]["notional_usd"]) * 10**USDC_DECIMALS))
        order = await asyncio.to_thread(
            JupiterSwapV2Client(api_key=jupiter_api_key, timeout=7).order,
            input_mint=USDC_MINT, output_mint=token_mint, amount_raw=amount_raw,
            taker=taker_public_key, slippage_bps=int(contract["costs"]["entry_adverse_slippage_bps"]),
        )
        buy = jupiter_order_to_causal_quote(order, token_mint=token_mint, side="buy", token_decimals=decimals)
        quotes.append(asdict(buy))
        collection["entry_status"] = "AVAILABLE_ASSEMBLED_PUBLIC_CONTROL" if buy.executable else "ROUTE_ONLY_UNEXPECTED"
    except (JupiterOrderError, SolanaRPCError, ValueError, TypeError) as exc:
        collection["entry_status"] = "ERROR:" + _redacted_error(exc, jupiter_api_key, rpc_url)
        episode = live_v2._episode(episode_key=episode_key, token_mint=token_mint, snapshot=snapshot, quotes=quotes, collection=collection)
        _SIM_CONTEXT["paths"].append({"episode_key": episode_key, "token_mint": token_mint, "entry_quote": None, "path": [], "collection": collection})
        return episode

    if not buy.executable or not buy.output_amount_raw:
        episode = live_v2._episode(episode_key=episode_key, token_mint=token_mint, snapshot=snapshot, quotes=quotes, collection=collection)
        _SIM_CONTEXT["paths"].append({"episode_key": episode_key, "token_mint": token_mint, "entry_quote": asdict(buy), "path": [], "collection": collection})
        return episode

    entry_at = int(buy.observed_at)
    for offset in policy["sample_offsets_seconds_from_entry"]:
        offset = int(offset)
        target = entry_at + offset
        if time.time() < target:
            await asyncio.sleep(max(0.0, target - time.time()))
        mark: dict[str, Any] = {"offset_seconds": offset, "target_at": target, "status": "STARTED", "quote": None}
        try:
            order = await asyncio.to_thread(
                JupiterSwapV2Client(api_key=jupiter_api_key, timeout=7).order,
                input_mint=token_mint, output_mint=USDC_MINT, amount_raw=int(buy.output_amount_raw),
                taker=None, slippage_bps=int(contract["costs"]["exit_adverse_slippage_bps"]),
            )
            sell = jupiter_order_to_causal_quote(order, token_mint=token_mint, side="sell", token_decimals=decimals)
            if sell.executable:
                raise ValueError("route-only SELL unexpectedly executable")
            payload = asdict(sell)
            quotes.append(payload)
            mark["status"] = "AVAILABLE_ROUTE_ONLY"
            mark["quote"] = payload
        except (JupiterOrderError, ValueError, TypeError) as exc:
            mark["status"] = "ERROR:" + _redacted_error(exc, jupiter_api_key)
        path_marks.append(mark)

    collection["path_mark_count"] = len(path_marks)
    collection["path_available_count"] = sum(mark["status"] == "AVAILABLE_ROUTE_ONLY" for mark in path_marks)
    episode = live_v2._episode(episode_key=episode_key, token_mint=token_mint, snapshot=snapshot, quotes=quotes, collection=collection)
    _SIM_CONTEXT["paths"].append({"episode_key": episode_key, "token_mint": token_mint, "entry_quote": asdict(buy), "path": path_marks, "collection": collection})
    return episode


async def run_sim(
    *, contract_path: Path, fixture_path: Path, policy_path: Path,
    artifacts_root: Path, duration_seconds: int, rotation_seconds: float,
    chunk_max_bytes: int, cargo: str, helius_api_key: str, jupiter_api_key: str,
    rpc_url: str, rpc_fallback_urls: tuple[str, ...],
) -> dict[str, Any]:
    contract, fixture, policy = _read_json(contract_path), _read_json(fixture_path), _read_json(policy_path)
    validate_contract(contract)
    route_hash = str(contract["contract_hash_sha256"])
    if fixture.get("route_contract_hash_sha256") != route_hash:
        raise ValueError("fixture/route contract hash mismatch")
    if policy.get("route_contract_hash_sha256") != route_hash:
        raise ValueError("smart policy/route contract hash mismatch")
    if int(contract["exit"]["horizon_seconds"]) not in policy["sample_offsets_seconds_from_entry"]:
        raise ValueError("smart observation grid must contain frozen +60s exit")
    if not helius_api_key or not jupiter_api_key or not rpc_url:
        raise ValueError("HELIUS_API_KEY, JUPITER_API_KEY and SOLANA_RPC_URL are required")

    control_taker, control_meta = await asyncio.to_thread(_discover_control, fixture=fixture, rpc_url=rpc_url)
    _SIM_CONTEXT.clear()
    _SIM_CONTEXT.update({"policy": policy, "paths": []})
    original_capture = live_v2._capture_selected_episode
    live_v2._capture_selected_episode = _capture_selected_episode_sim
    try:
        base_report = await live_v2.run_live(
            contract_path=contract_path, artifacts_root=artifacts_root,
            duration_seconds=duration_seconds, rotation_seconds=rotation_seconds,
            chunk_max_bytes=chunk_max_bytes, cargo=cargo,
            helius_api_key=helius_api_key, jupiter_api_key=jupiter_api_key,
            taker_public_key=control_taker, rpc_url=rpc_url,
            rpc_fallback_urls=rpc_fallback_urls,
        )
    finally:
        live_v2._capture_selected_episode = original_capture

    run_dir = Path(base_report["artifacts"]["report"]).resolve().parent
    route_result_path = Path(base_report["artifacts"]["result"]).resolve()
    paths_path = run_dir / "market-paths-v0.json"
    smart_result_path = run_dir / "smart-exit-result-v0.json"
    wrapper_report_path = run_dir / "simulation-report-v0.json"
    paths = {
        "type": "launch_burst_control_taker_market_paths_v0",
        "version": VERSION,
        "route_contract_hash_sha256": route_hash,
        "smart_exit_policy_hash_sha256": policy["policy_hash_sha256"],
        "sample_offsets_seconds_from_entry": policy["sample_offsets_seconds_from_entry"],
        "simulation_control_taker": {**control_meta, "address_redacted": True, "signing_or_submission_performed": False},
        "episodes": sorted(_SIM_CONTEXT["paths"], key=lambda x: (int((x.get("entry_quote") or {}).get("observed_at") or 0), x["token_mint"])),
    }
    _write_json(paths_path, paths)
    smart = run_smart_exit(
        contract_path=contract_path, policy_path=policy_path,
        route_result_path=route_result_path, market_paths_path=paths_path,
        output_path=smart_result_path,
    )
    paired = int(smart.get("paired_trade_count") or 0)
    report = {
        "type": "launch_burst_control_taker_sim_report_v0",
        "version": VERSION,
        "classification": "PASS_LAUNCH_BURST_CONTROL_TAKER_SIM_V0" if base_report.get("classification") == "PASS_LAUNCH_BURST_PROSPECTIVE_ROUTE_LIVE_V2" and smart.get("classification") == "PASS_LAUNCH_BURST_CONTROL_TAKER_SMART_EXIT_SIM_V0" else "FAIL_LAUNCH_BURST_CONTROL_TAKER_SIM_V0",
        "economic_interpretation": "SIMULATION_RESULT_AVAILABLE" if paired > 0 else "INCONCLUSIVE_NO_PAIRED_TRADES",
        "route_contract_hash_sha256": route_hash,
        "smart_exit_policy_hash_sha256": policy["policy_hash_sha256"],
        "paired_trade_count": paired,
        "base_systems_report": base_report,
        "artifacts": {
            "fixed_60s_route_result": str(route_result_path),
            "market_paths": str(paths_path),
            "smart_exit_result": str(smart_result_path),
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
            "smart_exit_is_exploratory": True,
        },
        "interpretation": "No-capital route-shadow simulation. Public funded control is used only so Jupiter can assemble a candidate BUY; nothing is signed or submitted. Fixed +60s is primary. Smart exit is preregistered exploratory evidence. This does not replace or unblock the official V4 funded-taker gate.",
    }
    _write_json(wrapper_report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Solana Launch Burst no-capital economic simulation v0")
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--duration-seconds", type=int, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--rotation-seconds", type=float, default=live_v2.DEFAULT_ROTATION_SECONDS)
    parser.add_argument("--chunk-max-mib", type=int, default=live_v2.DEFAULT_CHUNK_MAX_BYTES // (1024 * 1024))
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()
    env_file = args.env_file or (Path.cwd() / ".env")
    if env_file.exists():
        load_dotenv(dotenv_path=env_file, override=False)
    fallback_urls = tuple(x.strip() for x in os.environ.get("SOLANA_RPC_FALLBACK_URLS", "").split(",") if x.strip())
    try:
        result = asyncio.run(run_sim(
            contract_path=args.contract, fixture_path=args.fixture, policy_path=args.policy,
            artifacts_root=args.artifacts_root, duration_seconds=args.duration_seconds,
            rotation_seconds=args.rotation_seconds, chunk_max_bytes=args.chunk_max_mib * 1024 * 1024,
            cargo=args.cargo, helius_api_key=os.environ.get("HELIUS_API_KEY", "").strip(),
            jupiter_api_key=os.environ.get("JUPITER_API_KEY", "").strip(),
            rpc_url=os.environ.get("SOLANA_RPC_URL", "").strip(), rpc_fallback_urls=fallback_urls,
        ))
    except Exception as exc:
        print(json.dumps({
            "classification": "FAIL_LAUNCH_BURST_CONTROL_TAKER_SIM_V0",
            "error": _redacted_error(exc, os.environ.get("HELIUS_API_KEY", ""), os.environ.get("JUPITER_API_KEY", ""), os.environ.get("SOLANA_RPC_URL", "")),
        }, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["classification"] == "PASS_LAUNCH_BURST_CONTROL_TAKER_SIM_V0" else 2


if __name__ == "__main__":
    raise SystemExit(main())
