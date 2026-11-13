from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from benchmarks.launch_burst_control_taker_sim_v0 import run as sim
from benchmarks.deployer_prior_quality_v0.runtime_enrichment import (
    FEATURE_ID as DEPLOYER_FEATURE_ID,
    VERSION as DEPLOYER_RUNTIME_VERSION,
    patched_deployer_prior_quality_v0,
)
from benchmarks.launch_burst_control_taker_sim_v0.price_impact_semantics_fix_v0 import (
    FIX_VERSION,
    JUPITER_SWAP_V2_DOC,
    patched_price_impact_semantics,
)
from benchmarks.launch_burst_control_taker_sim_v0.run_v4_smart_ladder_25 import (
    DEFAULT_CONTRACT,
    DEFAULT_FIXTURE,
    DEFAULT_POLICY as DEFAULT_SMART_POLICY,
    run_sim_v4,
)
from benchmarks.launch_burst_prospective_route_live_v3 import live as v3
from benchmarks.launch_burst_prospective_route_live_v4 import live as v4
from benchmarks.launch_burst_sniper_v1.compare import PASS_CLASSIFICATION as PASS_COMPARISON
from benchmarks.launch_burst_sniper_v1.runtime_enrichment import (
    ENRICHMENT_VERSION,
    patched_sniper_feature_enrichment_v1,
)
from benchmarks.launch_burst_sniper_v1.strict_compare import run_strict_sniper_comparison_v1
from src.launch_burst_sniper_v1 import load_sniper_policy_v1


VERSION = "launch_burst_control_taker_sim_v4_sniper_v1"
PASS_CLASSIFICATION = "PASS_LAUNCH_BURST_CONTROL_TAKER_SIM_V4_SNIPER_V1"
FAIL_CLASSIFICATION = "FAIL_LAUNCH_BURST_CONTROL_TAKER_SIM_V4_SNIPER_V1"
DEFAULT_ARTIFACTS_ROOT = Path("artifacts") / VERSION
DEFAULT_SNIPER_POLICY = Path("benchmarks") / "launch_burst_sniper_v1" / "sniper_policy_v1.frozen.json"


def _screening_preflight(*, sniper_policy_path: Path, duration_seconds: int) -> dict:
    """Validate the frozen Sniper V1 policy before any live/provider work starts."""

    policy = load_sniper_policy_v1(sniper_policy_path)
    gates = policy.get("evaluation_gates") or {}
    frozen_duration = int(gates.get("screening_run_duration_seconds") or 0)
    if frozen_duration <= 0:
        raise ValueError("Sniper V1 screening duration is missing from frozen policy")
    if int(duration_seconds) != frozen_duration:
        raise ValueError(
            "Sniper V1 screening duration is frozen at "
            f"{frozen_duration}s; got {int(duration_seconds)}s. "
            "A different duration requires a separately preregistered run, not an in-place override."
        )
    return {
        "policy_hash_sha256": str(policy["policy_hash_sha256"]),
        "policy_name": str(policy["policy_name"]),
        "active_chain_profile": str(policy["active_chain_profile"]),
        "screening_run_duration_seconds": frozen_duration,
        "validated_before_acquisition": True,
    }


def _compact(report: dict) -> dict:
    sniper = report.get("sniper_comparison") or {}
    fixed = sniper.get("fixed_60s_primary_benchmark") or {}
    smart = sniper.get("smart_ladder_25_exploratory") or {}
    support = report.get("sniper_support_preflight") or {}
    return {
        "classification": report.get("classification"),
        "economic_interpretation": report.get("economic_interpretation"),
        "baseline_selected_count": sniper.get("baseline_selected_count"),
        "primary_selected_count": sniper.get("primary_selected_count"),
        "diagnostic_selected_count": sniper.get("diagnostic_selected_count"),
        "primary_selection_rate_pct_of_baseline": sniper.get("primary_selection_rate_pct_of_baseline"),
        "fixed_60s": {
            "baseline": fixed.get("baseline"),
            "primary_sniper": fixed.get("primary_sniper"),
            "counterfactual_skip": fixed.get("counterfactual_skip"),
            "primary_minus_baseline": fixed.get("primary_minus_baseline"),
        },
        "smart_ladder_25_exploratory": {
            "baseline": smart.get("baseline"),
            "primary_sniper": smart.get("primary_sniper"),
            "counterfactual_skip": smart.get("counterfactual_skip"),
        } if smart else None,
        "screening": sniper.get("screening"),
        "source_integrity": sniper.get("source_integrity"),
        "primary_rejection_reasons": ((sniper.get("primary_selector_diagnostics") or {}).get("reason_counts")),
        "preflight": report.get("sniper_screening_preflight"),
        "support_preflight": {
            "classification": support.get("classification"),
            "gates": support.get("gates"),
            "public_control": support.get("public_control"),
        } if support else None,
        "deployer_prior_quality_v0": report.get("deployer_prior_quality_v0"),
        "artifacts": report.get("artifacts"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "One-command no-capital Launch Burst V4 route-shadow run comparing the frozen baseline "
            "against preregistered SNIPER-HIGH-PRECISION-V1, with corrected Jupiter priceImpact semantics."
        )
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--smart-policy", type=Path, default=DEFAULT_SMART_POLICY)
    parser.add_argument("--sniper-policy", type=Path, default=DEFAULT_SNIPER_POLICY)
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
    gmgn_key = ""
    try:
        preflight = _screening_preflight(
            sniper_policy_path=args.sniper_policy,
            duration_seconds=args.duration_seconds,
        )

        env_file = args.env_file or (Path.cwd() / ".env")
        if env_file.exists():
            load_dotenv(dotenv_path=env_file, override=False)
        fallback_urls = tuple(
            item.strip()
            for item in os.environ.get("SOLANA_RPC_FALLBACK_URLS", "").split(",")
            if item.strip()
        )

        helius_key = os.environ.get("HELIUS_API_KEY", "").strip()
        jupiter_key = os.environ.get("JUPITER_API_KEY", "").strip()
        rpc_url = os.environ.get("SOLANA_RPC_URL", "").strip()
        gmgn_key = os.environ.get("GMGN_API_KEY", "").strip()
        if not gmgn_key:
            raise ValueError(
                "GMGN_API_KEY is required on the deployer-prior-quality research branch"
            )

        # Lazy import avoids a module cycle: the standalone preflight imports this module only
        # for the frozen screening contract helper, while the live runner reuses its lower-level
        # in-process control preparation after this module has fully initialized.
        from benchmarks.launch_burst_sniper_v1.preflight import (
            PASS as SUPPORT_PREFLIGHT_PASS,
            prepare_preflight_control,
        )

        support_preflight, control_taker = prepare_preflight_control(
            contract_path=args.contract,
            fixture_path=args.fixture,
            smart_policy_path=args.smart_policy,
            sniper_policy_path=args.sniper_policy,
            duration_seconds=args.duration_seconds,
            helius_api_key=helius_key,
            jupiter_api_key=jupiter_key,
            rpc_url=rpc_url,
        )
        if support_preflight.get("classification") != SUPPORT_PREFLIGHT_PASS or not control_taker:
            raise RuntimeError(
                "Sniper V1 read-only support preflight did not PASS; acquisition was not started"
            )
        control_meta = support_preflight.get("public_control")
        if not isinstance(control_meta, dict):
            raise RuntimeError("Sniper support preflight did not return public control metadata")

        with (
            patched_price_impact_semantics(),
            patched_sniper_feature_enrichment_v1(),
            patched_deployer_prior_quality_v0(api_key=gmgn_key) as deployer_runtime,
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

        live_control = base.get("simulation_control_taker") or {}
        if (
            live_control.get("control_resolution_mode") != "EXACT_PREFLIGHT_REUSE"
            or live_control.get("owner_public_key_sha256") != control_meta.get("owner_public_key_sha256")
        ):
            raise RuntimeError("live simulation did not reuse the exact preflight public control")

        base_v4 = base.get("base_v4_report") or {}
        route_input_path = Path(str((base_v4.get("artifacts") or {}).get("input") or ""))
        route_result_path = Path(str((base.get("artifacts") or {}).get("fixed_60s_route_result") or ""))
        smart_result_path = Path(str((base.get("artifacts") or {}).get("smart_ladder_25_result") or ""))
        if not route_input_path.is_file() or not route_result_path.is_file() or not smart_result_path.is_file():
            raise RuntimeError("base V4 simulation did not produce the required route/smart artifacts")

        run_dir = Path(str((base.get("artifacts") or {}).get("simulation_report") or "")).resolve().parent
        deployer_evidence_path = run_dir / "deployer-prior-quality-v0-evidence.json"
        deployer_runtime.write_artifact(deployer_evidence_path)
        deployer_payload = deployer_runtime.artifact_payload()
        sniper_result_path = run_dir / "sniper-comparison-v1.json"
        wrapper_report_path = run_dir / "simulation-report-v4-sniper-v1.json"
        comparison = run_strict_sniper_comparison_v1(
            contract_path=args.contract,
            policy_path=args.sniper_policy,
            route_input_path=route_input_path,
            route_result_path=route_result_path,
            smart_result_path=smart_result_path,
            output_path=sniper_result_path,
        )
        if comparison.get("sniper_policy_hash_sha256") != preflight["policy_hash_sha256"]:
            raise RuntimeError("Sniper policy hash changed between preflight and post-run comparison")

        base_pass = str(base.get("classification") or "").startswith("PASS_")
        compare_pass = comparison.get("classification") == PASS_COMPARISON
        deployer_status_counts = deployer_payload.get("status_counts") or {}
        deployer_invalid_system_statuses = {
            "TASK_CANCELLED_AFTER_CAPTURE",
            "TASK_UNRESOLVED_AFTER_CAPTURE",
            "INTERNAL_ERROR",
        }
        deployer_invalid_system_counts = {
            status: int(deployer_status_counts.get(status) or 0)
            for status in deployer_invalid_system_statuses
            if int(deployer_status_counts.get(status) or 0) > 0
        }
        deployer_systems_valid = not deployer_invalid_system_counts
        report = dict(base)
        report.update(
            {
                "type": "launch_burst_control_taker_sim_report_v4_sniper_v1",
                "version": VERSION,
                "classification": (
                    PASS_CLASSIFICATION
                    if base_pass and compare_pass and deployer_systems_valid
                    else FAIL_CLASSIFICATION
                ),
                "economic_interpretation": (
                    "SNIPER_ROUTE_SHADOW_COMPARISON_AVAILABLE"
                    if int(comparison.get("baseline_selected_count") or 0) > 0
                    else "INCONCLUSIVE_NO_BASELINE_SELECTED_EPISODES"
                ),
                "sniper_policy_hash_sha256": preflight["policy_hash_sha256"],
                "sniper_screening_preflight": preflight,
                "sniper_support_preflight": support_preflight,
                "sniper_comparison": comparison,
                "price_impact_semantics_fix": {
                    "version": FIX_VERSION,
                    "jupiter_swap_v2_documentation": JUPITER_SWAP_V2_DOC,
                    "negative_finite_price_impact_allowed": True,
                    "upper_bound_still_frozen_at_pct_points": 2.0,
                    "frozen_contract_changed": False,
                },
                "sniper_runtime_enrichment": {
                    "version": ENRICHMENT_VERSION,
                    "canonical_pump_wallet_field_reused": "wallet",
                    "baseline_selector_changed": False,
                },
                "deployer_prior_quality_v0": {
                    "version": DEPLOYER_RUNTIME_VERSION,
                    "feature_id": DEPLOYER_FEATURE_ID,
                    "record_count": deployer_payload.get("record_count"),
                    "status_counts": deployer_status_counts,
                    "systems_valid": deployer_systems_valid,
                    "invalid_system_status_counts": deployer_invalid_system_counts,
                    "guardrails": deployer_payload.get("guardrails"),
                },
            }
        )
        artifacts = dict(report.get("artifacts") or {})
        artifacts.update(
            {
                "route_input": str(route_input_path.resolve()),
                "sniper_v1_comparison": str(sniper_result_path.resolve()),
                "simulation_report": str(wrapper_report_path.resolve()),
                "deployer_prior_quality_v0_evidence": str(deployer_evidence_path.resolve()),
            }
        )
        report["artifacts"] = artifacts
        guardrails = dict(report.get("guardrails") or {})
        guardrails.update(
            {
                "price_impact_semantics_fix_applied": True,
                "sniper_policy_preregistered_before_this_run": True,
                "sniper_policy_validated_before_acquisition": True,
                "sniper_screening_duration_frozen_before_acquisition": True,
                "sniper_support_preflight_pass_required_before_acquisition": True,
                "sniper_exact_preflight_control_reused_in_live": True,
                "sniper_source_artifact_exact_parity_required": True,
                "sniper_changes_frozen_baseline_provider_dispatch": False,
                "wallet_field_enrichment_only": True,
                "official_v4_economic_verdict_changed": False,
                "automatic_profitability_claim": False,
                "deployer_sidecar_research_plane_only": True,
                "deployer_sidecar_blocks_provider_dispatch": False,
                "deployer_late_evidence_backfilled": False,
                "gmgn_private_key_used": False,
                "deployer_selector_changed": False,
                "deployer_external_acquisition_systems_valid": deployer_systems_valid,
            }
        )
        report["guardrails"] = guardrails
        sim._write_json(wrapper_report_path, report)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": FAIL_CLASSIFICATION,
                    "error": sim._redacted_error(
                        exc,
                        helius_key,
                        jupiter_key,
                        rpc_url,
                        gmgn_key,
                    ),
                },
                indent=2,
            )
        )
        return 2

    print(json.dumps(_compact(report), indent=2, sort_keys=True))
    return 0 if report.get("classification") == PASS_CLASSIFICATION else 2


if __name__ == "__main__":
    raise SystemExit(main())
