from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


VERSION = "market_first_candidate_manifest_v0"
PASS = "PASS_MARKET_FIRST_CANDIDATE_MANIFEST_V0"
EXPECTED_REPORT_TYPE = "launch_burst_opportunity_selection_lab_report"
EXPECTED_INFERENCE_ROLE = "OFFLINE_HYPOTHESIS_GENERATION_ONLY"
REPLICATED_PRIORITY = "REPLICATED_DIRECTION_PRIORITY"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_source_report(report: Mapping[str, Any]) -> None:
    if report.get("type") != EXPECTED_REPORT_TYPE:
        raise ValueError("unsupported opportunity lab report type")
    if report.get("inference_role") != EXPECTED_INFERENCE_ROLE:
        raise ValueError("source report must be hypothesis-generation-only")
    if int(report.get("run_count") or 0) < 1:
        raise ValueError("source report must contain at least one run")

    constraints = report.get("next_protocol_constraints")
    if not isinstance(constraints, Mapping):
        raise ValueError("source report missing next_protocol_constraints")
    required_true = (
        "do_not_change_frozen_momentum_v0",
        "do_not_select_new_thresholds_from_these_outcomes",
        "candidate_features_must_be_preregistered_before_future_validation",
    )
    for key in required_true:
        if constraints.get(key) is not True:
            raise ValueError(f"source report guardrail not asserted: {key}")


def _candidate_from_replication(row: Mapping[str, Any]) -> dict[str, Any]:
    if row.get("cross_run_hypothesis_priority") != REPLICATED_PRIORITY:
        raise ValueError("candidate row is not a replicated-direction priority")
    if row.get("threshold_recommendation") is not None:
        raise ValueError("same-sample threshold recommendation is forbidden")
    if row.get("same_direction_across_runs") is not True:
        raise ValueError("candidate direction must replicate across runs")
    if row.get("leave_one_positive_out_direction_stable_in_every_run") is not True:
        raise ValueError("candidate direction must be stable in every run")

    directions = row.get("directions")
    if not isinstance(directions, list) or not directions:
        raise ValueError("candidate directions must be a non-empty list")
    normalized = [str(value) for value in directions]
    if len(set(normalized)) != 1 or normalized[0] == "NO_DIRECTION":
        raise ValueError("candidate must have one replicated non-zero direction")

    feature = str(row.get("feature") or "")
    if not feature:
        raise ValueError("candidate feature is required")

    return {
        "feature": feature,
        "direction": normalized[0],
        "evidence": {
            "independent_run_count": int(row.get("run_count") or 0),
            "min_auc_separation_strength": float(row["min_auc_separation_strength"]),
            "max_auc_separation_strength": float(row["max_auc_separation_strength"]),
            "leave_one_positive_out_direction_stable_in_every_run": True,
        },
        "hypothesis_role": "DIRECTION_ONLY_FROM_OFFLINE_GENERATION_SAMPLE",
        "threshold": None,
        "weight": None,
        "runtime_selector_eligible": False,
        "requires_future_preregistration": True,
        "requires_independent_future_validation": True,
    }


def build_candidate_manifest(
    *,
    report: Mapping[str, Any],
    source_report_sha256: str | None = None,
) -> dict[str, Any]:
    _validate_source_report(report)

    replicated = report.get("replicated_direction_priority_features")
    if not isinstance(replicated, list):
        raise ValueError("source report missing replicated_direction_priority_features")

    candidates = [_candidate_from_replication(row) for row in replicated if isinstance(row, Mapping)]
    candidates.sort(key=lambda row: str(row["feature"]))

    candidate_core = {
        "version": VERSION,
        "candidates": candidates,
        "protocol": {
            "same_sample_threshold_search_permitted": False,
            "same_sample_weight_fit_permitted": False,
            "runtime_selector_creation_permitted": False,
            "candidate_direction_is_hypothesis_not_validation": True,
            "future_thresholds_must_be_frozen_before_labeled_validation": True,
            "future_validation_requires_new_independent_causal_capture": True,
            "fixed_60s_remains_primary_economic_benchmark": True,
            "social_event_first_remains_independent_track": True,
            "convergence_requires_separate_future_hypothesis": True,
        },
    }
    manifest_hash = _stable_hash(candidate_core)

    return {
        "type": "market_first_candidate_manifest",
        "version": VERSION,
        "classification": PASS,
        "status": (
            "CANDIDATES_AVAILABLE_FOR_PREREGISTRATION_DESIGN"
            if candidates
            else "NO_REPLICATED_DIRECTION_CANDIDATES_YET"
        ),
        "source": {
            "report_type": report.get("type"),
            "report_version": report.get("version"),
            "report_run_count": int(report.get("run_count") or 0),
            "report_sha256": source_report_sha256,
        },
        "candidate_count": len(candidates),
        "candidates": candidates,
        "ordering": "ALPHABETICAL_NOT_ECONOMIC_RANKING",
        "protocol": candidate_core["protocol"],
        "manifest_hash_sha256": manifest_hash,
        "interpretation": (
            "Directions are offline hypothesis-generation evidence only. "
            "This artifact does not define thresholds, weights, a runtime selector, or economic edge."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a guarded Market-First candidate-direction manifest from an Opportunity Lab report"
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/market-first-candidate-manifest-v0.json"),
    )
    args = parser.parse_args()

    try:
        report = _read_json(args.report)
        manifest = build_candidate_manifest(
            report=report,
            source_report_sha256=_sha256_file(args.report),
        )
        _write_json(args.output, manifest)
        compact = {
            "classification": manifest["classification"],
            "status": manifest["status"],
            "candidate_count": manifest["candidate_count"],
            "candidates": manifest["candidates"],
            "manifest_hash_sha256": manifest["manifest_hash_sha256"],
            "output": str(args.output.resolve()),
        }
        print(json.dumps(compact, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": "FAIL_MARKET_FIRST_CANDIDATE_MANIFEST_V0",
                    "error": f"{type(exc).__name__}:{exc}",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
