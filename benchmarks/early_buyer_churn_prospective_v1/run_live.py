from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any, Mapping

from dotenv import load_dotenv

from benchmarks.early_buyer_churn_prospective_v1.protocol import (
    DEFAULT_PROTOCOL,
    read_json,
    validate_protocol,
)
from benchmarks.early_buyer_churn_prospective_v1.runtime_enrichment import (
    EXTERNAL_EVIDENCE_KEY,
    patched_early_buyer_churn_prospective_v1,
)
from benchmarks.early_buyer_churn_v0.run import FEATURE_ID
from benchmarks.launch_burst_control_taker_sim_v0 import run as sim
from benchmarks.launch_burst_control_taker_sim_v0.run_v4_smart_ladder_25 import (
    DEFAULT_CONTRACT,
    DEFAULT_FIXTURE,
    DEFAULT_POLICY,
    run_sim_v4,
)
from benchmarks.launch_burst_prospective_route_live_v3 import live as v3
from benchmarks.launch_burst_prospective_route_live_v4 import live as v4


VERSION = "launch_burst_early_buyer_churn_prospective_v1"
PASS_CLASSIFICATION = "PASS_LAUNCH_BURST_EARLY_BUYER_CHURN_PROSPECTIVE_V1"
FAIL_CLASSIFICATION = "FAIL_LAUNCH_BURST_EARLY_BUYER_CHURN_PROSPECTIVE_V1"
DEFAULT_ARTIFACTS_ROOT = Path("artifacts") / VERSION


def _same_value(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        return abs(float(left) - float(right)) <= 1e-15
    except (TypeError, ValueError):
        return False


def _validate_parity_report(
    *,
    parity_report_path: Path,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    report = read_json(parity_report_path)
    if report.get("classification") != "PASS_EARLY_BUYER_CHURN_PROSPECTIVE_V1_PARITY":
        raise ValueError("prospective churn parity report did not PASS")
    if report.get("exact_parity") is not True:
        raise ValueError("prospective churn parity is not exact")
    if int(report.get("mismatch_count") or 0) != 0:
        raise ValueError("prospective churn parity has mismatches")
    if report.get("protocol_hash_sha256") != protocol.get("protocol_hash_sha256"):
        raise ValueError("prospective churn parity protocol hash mismatch")
    if report.get("feature_id") != FEATURE_ID:
        raise ValueError("prospective churn parity feature changed")

    expected_runs = list((protocol.get("instrumentation") or {}).get("parity_runs") or [])
    actual_runs = [
        str(row.get("run_id") or "")
        for row in report.get("per_run") or []
        if isinstance(row, dict)
    ]
    if actual_runs != expected_runs:
        raise ValueError("prospective churn parity run set/order changed")
    if not actual_runs:
        raise ValueError("prospective churn parity contains no run attestations")
    if any((row.get("all_guardrails_valid") is not True) for row in report.get("per_run") or []):
        raise ValueError("prospective churn parity guardrail failed")
    if any(int(row.get("mismatch_count") or 0) != 0 for row in report.get("per_run") or []):
        raise ValueError("prospective churn parity per-run mismatch detected")

    return {
        "classification": report.get("classification"),
        "exact_parity": True,
        "mismatch_count": 0,
        "compared_complete_episode_count": int(
            report.get("compared_complete_episode_count") or 0
        ),
        "protocol_hash_sha256": report.get("protocol_hash_sha256"),
        "run_ids": actual_runs,
        "artifact": str(Path(parity_report_path).resolve()),
    }


def _attest_route_input(run_dir: Path) -> dict[str, Any]:
    path = Path(run_dir) / "route-input-v2.json"
    route_input = read_json(path)
    if route_input.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError("fresh route input did not freeze feature snapshots before provider quotes")

    status_counts: dict[str, int] = {}
    complete_count = 0
    causal_available = 0
    missing_count = 0
    right_censored_count = 0
    errors: list[str] = []

    for episode in route_input.get("episodes") or []:
        if not isinstance(episode, dict):
            continue
        episode_key = str(episode.get("episode_key") or "")
        snapshot = episode.get("feature_snapshot") or {}
        features = snapshot.get("features") or {}
        evidence = (
            (snapshot.get("external_evidence") or {}).get(EXTERNAL_EVIDENCE_KEY)
            or {}
        )
        status = str(evidence.get("status") or "MISSING_EVIDENCE")
        status_counts[status] = status_counts.get(status, 0) + 1

        if snapshot.get("complete") is not True:
            right_censored_count += 1
            if status != "RIGHT_CENSORED":
                errors.append(f"right_censored_status:{episode_key}:{status}")
            if features.get(FEATURE_ID) is not None:
                errors.append(f"right_censored_feature_backfill:{episode_key}")
            continue

        complete_count += 1
        feature_value = features.get(FEATURE_ID)
        evidence_value = evidence.get("feature_value")
        if evidence.get("feature_id") != FEATURE_ID:
            errors.append(f"feature_id:{episode_key}")
        if evidence.get("computed_before_provider_quotes") is not True:
            errors.append(f"provider_order:{episode_key}")
        if evidence.get("external_provider_used") is not False:
            errors.append(f"external_provider:{episode_key}")
        if not _same_value(feature_value, evidence_value):
            errors.append(f"feature_evidence_value_mismatch:{episode_key}")

        if status == "CAUSAL_AVAILABLE":
            causal_available += 1
            if feature_value is None:
                errors.append(f"available_without_feature:{episode_key}")
        elif status == "MISSING_NO_OBSERVED_BUY":
            missing_count += 1
            if feature_value is not None:
                errors.append(f"missing_with_feature:{episode_key}")
        else:
            errors.append(f"unexpected_complete_status:{episode_key}:{status}")

    if errors:
        raise ValueError(
            "prospective churn route-input instrumentation failed: "
            + ";".join(errors[:20])
        )

    return {
        "route_input": str(path.resolve()),
        "complete_episode_count": complete_count,
        "causal_available_count": causal_available,
        "missing_no_buy_count": missing_count,
        "right_censored_count": right_censored_count,
        "status_counts": status_counts,
        "instrumentation_valid": True,
        "feature_snapshot_frozen_before_provider_quotes": True,
    }


def _compact(report: Mapping[str, Any]) -> dict[str, Any]:
    base = report.get("base_v4_report") or {}
    return {
        "classification": report.get("classification"),
        "capture_stop_reason": (base.get("capture") or {}).get("stop_reason"),
        "requested_duration_seconds": base.get("requested_duration_seconds"),
        "churn_prospective_v1": report.get("churn_prospective_v1"),
        "parity_attestation": report.get("parity_attestation"),
        "artifacts": report.get("artifacts"),
        "guardrails": report.get("guardrails"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Frozen fresh prospective acquisition for Early Buyer Churn V1"
    )
    parser.add_argument("--parity-report", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
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

    helius_key = ""
    jupiter_key = ""
    rpc_url = ""

    try:
        protocol = read_json(args.protocol)
        validate_protocol(protocol)
        expected_duration = int(
            (protocol.get("fresh_confirmation") or {}).get(
                "requested_duration_seconds"
            )
            or 0
        )
        if int(args.duration_seconds) != expected_duration:
            raise ValueError(
                f"fresh duration changed: {args.duration_seconds} != {expected_duration}"
            )
        parity = _validate_parity_report(
            parity_report_path=args.parity_report,
            protocol=protocol,
        )

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

        with patched_early_buyer_churn_prospective_v1():
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
                    decoder_target_dir=args.decoder_target_dir
                    or v4._default_decoder_target(),
                    helius_api_key=helius_key,
                    jupiter_api_key=jupiter_key,
                    rpc_url=rpc_url,
                    rpc_fallback_urls=fallback_urls,
                )
            )

        run_dir = Path(
            str((base.get("artifacts") or {}).get("simulation_report") or "")
        ).resolve().parent
        instrumentation = _attest_route_input(run_dir)
        base_v4 = base.get("base_v4_report") or {}
        capture = base_v4.get("capture") or {}
        base_pass = str(base.get("classification") or "").startswith(
            "PASS_LAUNCH_BURST_CONTROL_TAKER_SIM_V4_SMART_LADDER_25_V0"
        )
        systems_valid = (
            base_pass
            and str(capture.get("stop_reason") or "") == "duration_elapsed"
            and int(base_v4.get("requested_duration_seconds") or 0)
            == expected_duration
            and instrumentation.get("instrumentation_valid") is True
        )

        wrapper_path = (
            run_dir
            / "simulation-report-v4-early-buyer-churn-prospective-v1.json"
        )
        report = {
            "type": "launch_burst_early_buyer_churn_prospective_report_v1",
            "version": VERSION,
            "classification": (
                PASS_CLASSIFICATION if systems_valid else FAIL_CLASSIFICATION
            ),
            "base_simulation_classification": base.get("classification"),
            "base_v4_report": base_v4,
            "churn_prospective_v1": {
                "feature_id": FEATURE_ID,
                "systems_valid": systems_valid,
                **instrumentation,
            },
            "parity_attestation": parity,
            "protocol_hash_sha256": protocol.get("protocol_hash_sha256"),
            "artifacts": {
                **dict(base.get("artifacts") or {}),
                "route_input": str(
                    (run_dir / "route-input-v2.json").resolve()
                ),
                "simulation_report": str(wrapper_path.resolve()),
            },
            "guardrails": {
                "parity_required_before_capture": True,
                "exact_parity_attested": parity.get("exact_parity") is True,
                "feature_definition_changed": False,
                "feature_computed_before_provider_quotes": True,
                "external_provider_used_for_churn": False,
                "selector_changed": False,
                "participant_quality_changed": False,
                "route_contract_changed": False,
                "threshold_search_performed": False,
                "private_key_required": False,
                "transaction_signed": False,
                "transaction_submitted": False,
                "automatic_profitability_claim": False,
            },
        }
        sim._write_json(wrapper_path, report)

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
