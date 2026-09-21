from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from benchmarks.holder_ownership_native_v1.runtime_enrichment import (
    FEATURE_ID,
    VERSION as HOLDER_RUNTIME_VERSION,
    patched_holder_ownership_native_v1,
)
from benchmarks.launch_burst_control_taker_sim_v0 import run as sim
from benchmarks.launch_burst_control_taker_sim_v0.run_v4_smart_ladder_25 import (
    DEFAULT_CONTRACT,
    DEFAULT_FIXTURE,
    DEFAULT_POLICY,
    run_sim_v4,
)
from benchmarks.launch_burst_prospective_route_live_v3 import live as v3
from benchmarks.launch_burst_prospective_route_live_v4 import live as v4


VERSION = "launch_burst_holder_ownership_native_v1"
PASS_CLASSIFICATION = "PASS_LAUNCH_BURST_HOLDER_OWNERSHIP_NATIVE_V1"
FAIL_CLASSIFICATION = "FAIL_LAUNCH_BURST_HOLDER_OWNERSHIP_NATIVE_V1"
DEFAULT_ARTIFACTS_ROOT = Path("artifacts") / VERSION


def _compact(report: dict) -> dict:
    holder = report.get("holder_ownership_native_v1") or {}
    base = report.get("base_v4_report") or {}
    return {
        "classification": report.get("classification"),
        "capture_stop_reason": (base.get("capture") or {}).get("stop_reason"),
        "requested_duration_seconds": base.get("requested_duration_seconds"),
        "holder_ownership_native_v1": holder,
        "artifacts": report.get("artifacts"),
        "guardrails": report.get("guardrails"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prospective no-capital Helius-native Holder Ownership V1 acquisition"
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--duration-seconds", type=int, default=900)
    parser.add_argument("--rotation-seconds", type=float, default=v3.DEFAULT_ROTATION_SECONDS)
    parser.add_argument("--chunk-max-mib", type=int, default=v3.DEFAULT_CHUNK_MAX_BYTES // (1024 * 1024))
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--decoder-target-dir", type=Path, default=None)
    parser.add_argument("--env-file", type=Path, default=None)
    args = parser.parse_args()

    if int(args.duration_seconds) != 900:
        print(json.dumps({
            "classification": FAIL_CLASSIFICATION,
            "error": "Holder Ownership Native V1 duration is frozen at 900 seconds",
        }, indent=2))
        return 2

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

    try:
        if not helius_key:
            raise ValueError("HELIUS_API_KEY is required for Holder Ownership Native V1")

        with patched_holder_ownership_native_v1(helius_api_key=helius_key) as holder_runtime:
            base = asyncio.run(
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
                    helius_api_key=helius_key,
                    jupiter_api_key=jupiter_key,
                    rpc_url=rpc_url,
                    rpc_fallback_urls=fallback_urls,
                )
            )

        run_dir = Path(str((base.get("artifacts") or {}).get("simulation_report") or "")).resolve().parent
        evidence_path = run_dir / "holder-ownership-native-v1-evidence.json"
        holder_runtime.write_artifact(evidence_path)
        holder_payload = holder_runtime.artifact_payload()

        status_counts = holder_payload.get("status_counts") or {}
        invalid_system_statuses = {
            "TASK_CANCELLED_AFTER_CAPTURE",
            "TASK_UNRESOLVED_AFTER_CAPTURE",
            "INTERNAL_ERROR",
            "HELIUS_RATE_LIMITED",
        }
        invalid_counts = {
            status: int(status_counts.get(status) or 0)
            for status in invalid_system_statuses
            if int(status_counts.get(status) or 0) > 0
        }
        systems_valid = not invalid_counts
        base_v4 = base.get("base_v4_report") or {}
        base_pass = str(base.get("classification") or "").startswith(
            "PASS_LAUNCH_BURST_CONTROL_TAKER_SIM_V4_SMART_LADDER_25_V0"
        )

        wrapper_path = run_dir / "simulation-report-v4-holder-ownership-native-v1.json"
        report = {
            "type": "launch_burst_holder_ownership_native_report_v1",
            "version": VERSION,
            "classification": PASS_CLASSIFICATION if base_pass and systems_valid else FAIL_CLASSIFICATION,
            "base_simulation_classification": base.get("classification"),
            "base_v4_report": base_v4,
            "holder_ownership_native_v1": {
                "version": HOLDER_RUNTIME_VERSION,
                "feature_id": FEATURE_ID,
                "record_count": holder_payload.get("record_count"),
                "status_counts": status_counts,
                "systems_valid": systems_valid,
                "invalid_system_status_counts": invalid_counts,
                "guardrails": holder_payload.get("guardrails"),
            },
            "artifacts": {
                **dict(base.get("artifacts") or {}),
                "route_input": str((run_dir / "route-input-v2.json").resolve()),
                "holder_ownership_native_v1_evidence": str(evidence_path.resolve()),
                "simulation_report": str(wrapper_path.resolve()),
            },
            "guardrails": {
                "holder_research_plane_only": True,
                "holder_sidecar_blocks_signal_plane": False,
                "helius_api_key_only": True,
                "gmgn_holder_dependency": False,
                "private_key_used": False,
                "capital_used": False,
                "transaction_signed": False,
                "transaction_submitted": False,
                "selector_changed": False,
                "participant_quality_changed": False,
                "route_contract_changed": False,
                "late_evidence_backfilled": False,
                "bonding_curve_excluded": True,
                "graduated_before_snapshot_is_missing": True,
                "tradeable_float_rebase_used": False,
                "automatic_profitability_claim": False,
            },
        }
        sim._write_json(wrapper_path, report)

    except Exception as exc:
        print(json.dumps({
            "classification": FAIL_CLASSIFICATION,
            "error": sim._redacted_error(exc, helius_key, jupiter_key, rpc_url),
        }, indent=2))
        return 2

    print(json.dumps(_compact(report), indent=2, sort_keys=True))
    return 0 if report.get("classification") == PASS_CLASSIFICATION else 2


if __name__ == "__main__":
    raise SystemExit(main())
