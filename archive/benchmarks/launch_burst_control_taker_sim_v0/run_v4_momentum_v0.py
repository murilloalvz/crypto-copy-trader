from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from benchmarks.launch_burst_control_taker_sim_v0 import run as sim
from benchmarks.launch_burst_control_taker_sim_v0.price_impact_semantics_fix_v0 import patched_price_impact_semantics
from benchmarks.launch_burst_control_taker_sim_v0.run_v4_smart_ladder_25 import (
    DEFAULT_CONTRACT,
    DEFAULT_FIXTURE,
    DEFAULT_POLICY as DEFAULT_SMART_POLICY,
    run_sim_v4,
)
from benchmarks.launch_burst_momentum_v0.compare import PASS as PASS_COMPARISON, run_momentum_comparison_v0
from benchmarks.launch_burst_momentum_v0.horizon_300 import HORIZON_VERSION, patched_300s_route_collection_v0
from benchmarks.launch_burst_momentum_v0.runtime_enrichment import ENRICHMENT_VERSION, patched_momentum_feature_enrichment_v0
from benchmarks.launch_burst_prospective_route_live_v3 import live as v3
from benchmarks.launch_burst_prospective_route_live_v4 import live as v4
from benchmarks.launch_burst_sniper_v1.preflight import PASS as SUPPORT_PASS, prepare_preflight_control
from src.launch_burst_momentum_v0 import load_momentum_policy_v0


VERSION = "launch_burst_control_taker_sim_v4_momentum_v0"
PASS = "PASS_LAUNCH_BURST_CONTROL_TAKER_SIM_V4_MOMENTUM_V0"
FAIL = "FAIL_LAUNCH_BURST_CONTROL_TAKER_SIM_V4_MOMENTUM_V0"
DEFAULT_ARTIFACTS_ROOT = Path("artifacts") / VERSION
DEFAULT_MOMENTUM_POLICY = Path("benchmarks") / "launch_burst_momentum_v0" / "momentum_policy_v0.frozen.json"
DEFAULT_SNIPER_V1_POLICY = Path("benchmarks") / "launch_burst_sniper_v1" / "sniper_policy_v1.frozen.json"


def _screening_preflight(policy_path: Path, duration_seconds: int) -> dict:
    policy = load_momentum_policy_v0(policy_path)
    gates = policy.get("evaluation_gates") or {}
    frozen_duration = int(gates.get("screening_run_duration_seconds") or 0)
    if int(duration_seconds) != frozen_duration:
        raise ValueError(
            f"Burst Momentum V0 screening is frozen at {frozen_duration}s; got {duration_seconds}s"
        )
    return {
        "policy_name": policy["policy_name"],
        "policy_hash_sha256": policy["policy_hash_sha256"],
        "screening_run_duration_seconds": frozen_duration,
        "validated_before_acquisition": True,
        "historical_source_strategy": (policy.get("historical_evidence_provenance") or {}).get("source_strategy"),
        "historical_metric_exact_parity_claim": False,
    }


def _compact(report: dict) -> dict:
    comparison = report.get("momentum_comparison") or {}
    fixed = comparison.get("fixed_60s_primary_benchmark") or {}
    h300 = comparison.get("historical_alignment_300s_exploratory") or {}
    return {
        "classification": report.get("classification"),
        "economic_interpretation": report.get("economic_interpretation"),
        "preflight": report.get("momentum_screening_preflight"),
        "support_preflight": report.get("support_preflight"),
        "selection": comparison.get("selection"),
        "fixed_60s": {
            "baseline": fixed.get("baseline"),
            "momentum_primary": fixed.get("momentum_primary"),
            "sniper_v1_diagnostic": fixed.get("sniper_v1_diagnostic"),
            "momentum_and_sniper_v1_convergence_diagnostic": fixed.get("momentum_and_sniper_v1_convergence_diagnostic"),
            "counterfactual_skip": fixed.get("counterfactual_skip"),
        },
        "historical_alignment_300s_exploratory": h300,
        "screening": comparison.get("screening"),
        "primary_rejection_reasons": ((comparison.get("primary_selector_diagnostics") or {}).get("reason_counts")),
        "source_integrity": comparison.get("source_integrity"),
        "artifacts": report.get("artifacts"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fresh no-capital Burst + causal momentum convergence screening"
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--smart-policy", type=Path, default=DEFAULT_SMART_POLICY)
    parser.add_argument("--momentum-policy", type=Path, default=DEFAULT_MOMENTUM_POLICY)
    parser.add_argument("--sniper-v1-policy", type=Path, default=DEFAULT_SNIPER_V1_POLICY)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--duration-seconds", type=int, default=900)
    parser.add_argument("--rotation-seconds", type=float, default=v3.DEFAULT_ROTATION_SECONDS)
    parser.add_argument("--chunk-max-mib", type=int, default=v3.DEFAULT_CHUNK_MAX_BYTES // (1024 * 1024))
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--decoder-target-dir", type=Path, default=None)
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()

    helius_key = ""
    jupiter_key = ""
    rpc_url = ""
    try:
        momentum_preflight = _screening_preflight(args.momentum_policy, args.duration_seconds)
        env_file = args.env_file or (Path.cwd() / ".env")
        if env_file.exists():
            load_dotenv(dotenv_path=env_file, override=False)
        helius_key = os.environ.get("HELIUS_API_KEY", "").strip()
        jupiter_key = os.environ.get("JUPITER_API_KEY", "").strip()
        rpc_url = os.environ.get("SOLANA_RPC_URL", "").strip()
        fallback_urls = tuple(
            item.strip()
            for item in os.environ.get("SOLANA_RPC_FALLBACK_URLS", "").split(",")
            if item.strip()
        )

        support_preflight, control_taker = prepare_preflight_control(
            contract_path=args.contract,
            fixture_path=args.fixture,
            smart_policy_path=args.smart_policy,
            sniper_policy_path=args.sniper_v1_policy,
            duration_seconds=args.duration_seconds,
            helius_api_key=helius_key,
            jupiter_api_key=jupiter_key,
            rpc_url=rpc_url,
        )
        if support_preflight.get("classification") != SUPPORT_PASS or not control_taker:
            raise RuntimeError("read-only support preflight did not PASS; acquisition was not started")
        control_meta = support_preflight.get("public_control")
        if not isinstance(control_meta, dict):
            raise RuntimeError("support preflight did not return control metadata")

        with (
            patched_price_impact_semantics(),
            patched_momentum_feature_enrichment_v0(),
            patched_300s_route_collection_v0(),
        ):
            base = asyncio.run(
                run_sim_v4(
                    contract_path=args.contract,
                    fixture_path=args.fixture,
                    policy_path=args.smart_policy,
                    artifacts_root=args.artifacts_root,
                    duration_seconds=args.duration_seconds,
                    rotation_seconds=args.rotation_seconds,
                    chunk_max_bytes=args.chunk_max_mib * 1024 * 1024,
                    cargo=args.cargo,
                    decoder_target_dir=args.decoder_target_dir or v4._default_decoder_target(),
                    helius_api_key=helius_key,
                    jupiter_api_key=jupiter_key,
                    rpc_url=rpc_url,
                    rpc_fallback_urls=fallback_urls,
                    control_taker_override=control_taker,
                    control_meta_override=control_meta,
                )
            )

        base_v4 = base.get("base_v4_report") or {}
        route_input_path = Path(str((base_v4.get("artifacts") or {}).get("input") or ""))
        route_result_path = Path(str((base.get("artifacts") or {}).get("fixed_60s_route_result") or ""))
        smart_result_path = Path(str((base.get("artifacts") or {}).get("smart_ladder_25_result") or ""))
        market_paths_path = Path(str((base.get("artifacts") or {}).get("market_paths") or ""))
        required = (route_input_path, route_result_path, smart_result_path, market_paths_path)
        if not all(path.is_file() for path in required):
            raise RuntimeError("base V4 simulation did not produce required artifacts")

        market_paths = sim._read_json(market_paths_path)
        market_paths["momentum_feature_enrichment_version"] = ENRICHMENT_VERSION
        market_paths["exploratory_additional_offsets_seconds_from_entry"] = [300]
        market_paths["momentum_horizon_version"] = HORIZON_VERSION
        sim._write_json(market_paths_path, market_paths)

        run_dir = Path(str((base.get("artifacts") or {}).get("simulation_report") or "")).resolve().parent
        comparison_path = run_dir / "momentum-comparison-v0.json"
        wrapper_report_path = run_dir / "simulation-report-v4-momentum-v0.json"
        comparison = run_momentum_comparison_v0(
            contract_path=args.contract,
            momentum_policy_path=args.momentum_policy,
            sniper_v1_policy_path=args.sniper_v1_policy,
            route_input_path=route_input_path,
            route_result_path=route_result_path,
            market_paths_path=market_paths_path,
            smart_result_path=smart_result_path,
            output_path=comparison_path,
        )
        if comparison.get("classification") != PASS_COMPARISON:
            raise RuntimeError("momentum comparison did not PASS")
        if comparison.get("momentum_policy_hash_sha256") != momentum_preflight["policy_hash_sha256"]:
            raise RuntimeError("momentum policy changed between preflight and comparison")

        base_pass = str(base.get("classification") or "").startswith("PASS_")
        report = dict(base)
        report.update({
            "type": "launch_burst_control_taker_sim_report_v4_momentum_v0",
            "version": VERSION,
            "classification": PASS if base_pass else FAIL,
            "economic_interpretation": (
                "BURST_MOMENTUM_ROUTE_SHADOW_COMPARISON_AVAILABLE"
                if int((comparison.get("selection") or {}).get("baseline_selected_count") or 0) > 0
                else "INCONCLUSIVE_NO_BASELINE_SELECTED_EPISODES"
            ),
            "momentum_policy_hash_sha256": momentum_preflight["policy_hash_sha256"],
            "momentum_screening_preflight": momentum_preflight,
            "support_preflight": {
                "classification": support_preflight.get("classification"),
                "gates": support_preflight.get("gates"),
                "public_control": support_preflight.get("public_control"),
            },
            "momentum_comparison": comparison,
            "momentum_runtime": {
                "feature_enrichment_version": ENRICHMENT_VERSION,
                "horizon_300_version": HORIZON_VERSION,
                "old_provider_volume_windows_reused": False,
                "local_causal_5s_stream_only": True,
            },
        })
        artifacts = dict(report.get("artifacts") or {})
        artifacts.update({
            "route_input": str(route_input_path.resolve()),
            "momentum_comparison": str(comparison_path.resolve()),
            "simulation_report": str(wrapper_report_path.resolve()),
        })
        report["artifacts"] = artifacts
        guardrails = dict(report.get("guardrails") or {})
        guardrails.update({
            "momentum_policy_preregistered_before_run": True,
            "momentum_duration_frozen_before_run": True,
            "frozen_burst_baseline_changed": False,
            "sniper_v1_promoted_to_primary": False,
            "300s_changes_primary_60s_benchmark": False,
            "exact_preflight_control_reused": True,
            "automatic_profitability_claim": False,
            "official_v4_economic_verdict_changed": False,
        })
        report["guardrails"] = guardrails
        sim._write_json(wrapper_report_path, report)
    except Exception as exc:
        print(json.dumps({
            "classification": FAIL,
            "error": sim._redacted_error(exc, helius_key, jupiter_key, rpc_url),
        }, indent=2))
        return 2

    print(json.dumps(_compact(report), indent=2, sort_keys=True))
    return 0 if report.get("classification") == PASS else 2


if __name__ == "__main__":
    raise SystemExit(main())
