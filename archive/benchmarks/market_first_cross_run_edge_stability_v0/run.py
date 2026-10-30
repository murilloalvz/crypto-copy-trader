from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

PASS = "PASS_MARKET_FIRST_CROSS_RUN_EDGE_STABILITY_V0"
REQUIRED_SOURCE_CLASSIFICATION = "PASS_MARKET_FIRST_ROUTEABLE_EDGE_DISCOVERY_V2"
PRIMARY_COHORT = "baseline_route_usable_default_sol_quote"


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


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def _sign(value: float | None) -> int | None:
    if value is None or value == 0:
        return None
    return -1 if value < 0 else 1


def _same_nonzero_sign(values: list[float | None]) -> bool:
    signs = [_sign(value) for value in values]
    return bool(signs) and all(sign is not None for sign in signs) and len(set(signs)) == 1


def run_cross_run_stability_v0(
    *,
    run_dirs: list[Path],
    output_path: Path | None = None,
) -> dict[str, Any]:
    if len(run_dirs) < 2:
        raise ValueError("at least two independent run dirs are required")

    sources: list[dict[str, Any]] = []
    feature_ids: set[str] = set()
    seen_capture_ids: set[str] = set()

    for raw_dir in run_dirs:
        run_dir = Path(raw_dir).resolve()
        artifact_path = run_dir / "market-first-routeable-edge-discovery-v2.json"
        if not artifact_path.is_file():
            raise ValueError(f"required cross-run source missing: {artifact_path}")
        payload = _read_json(artifact_path)
        if payload.get("classification") != REQUIRED_SOURCE_CLASSIFICATION:
            raise ValueError(f"routeable discovery source is not PASS: {artifact_path}")

        integrity = payload.get("source_integrity") or {}
        capture_id = str(integrity.get("run_dir") or run_dir)
        if capture_id in seen_capture_ids:
            raise ValueError(f"duplicate capture identity: {capture_id}")
        seen_capture_ids.add(capture_id)

        cohort = ((payload.get("cohorts") or {}).get(PRIMARY_COHORT) or {})
        features = cohort.get("features") or {}
        if not isinstance(features, dict):
            raise ValueError(f"primary cohort features missing: {artifact_path}")
        feature_ids.update(str(key) for key in features)
        sources.append(
            {
                "run_dir": str(run_dir),
                "artifact_path": str(artifact_path),
                "route_usable_count": int(integrity.get("route_usable_fixed_row_count") or 0),
                "cohort_trade_count": int(((cohort.get("outcomes") or {}).get("trade_count")) or 0),
                "features": features,
            }
        )

    feature_reports: dict[str, Any] = {}
    stable_direction_features: list[str] = []
    for feature_id in sorted(feature_ids):
        per_run: list[dict[str, Any]] = []
        full_rhos: list[float | None] = []
        without_best_rhos: list[float | None] = []
        loo_consistency: list[float | None] = []
        pair_counts: list[int] = []

        for source in sources:
            row = (source["features"] or {}).get(feature_id) or {}
            full = _finite(row.get("spearman_with_fixed_60s_return"))
            without_best = _finite(row.get("spearman_without_best_return_trade"))
            loo = _finite(row.get("leave_one_out_sign_consistency_fraction"))
            pairs = int(row.get("usable_pair_count") or 0)
            full_rhos.append(full)
            without_best_rhos.append(without_best)
            loo_consistency.append(loo)
            pair_counts.append(pairs)
            per_run.append(
                {
                    "run_dir": source["run_dir"],
                    "usable_pair_count": pairs,
                    "spearman": full,
                    "spearman_without_best_trade": without_best,
                    "leave_one_out_sign_consistency_fraction": loo,
                    "feature_mean_positive_outcomes": _finite(row.get("feature_mean_positive_outcomes")),
                    "feature_mean_nonpositive_outcomes": _finite(row.get("feature_mean_nonpositive_outcomes")),
                }
            )

        full_sign_consistent = _same_nonzero_sign(full_rhos)
        without_best_sign_consistent = _same_nonzero_sign(without_best_rhos)
        same_direction_full_vs_without_best = (
            full_sign_consistent
            and without_best_sign_consistent
            and _sign(full_rhos[0]) == _sign(without_best_rhos[0])
        )
        if same_direction_full_vs_without_best:
            stable_direction_features.append(feature_id)

        finite_full = [value for value in full_rhos if value is not None]
        finite_loo = [value for value in loo_consistency if value is not None]
        feature_reports[feature_id] = {
            "per_run": per_run,
            "runs_with_pairs": sum(count > 0 for count in pair_counts),
            "min_usable_pair_count": min(pair_counts) if pair_counts else 0,
            "full_spearman_sign_consistent_across_runs": full_sign_consistent,
            "without_best_sign_consistent_across_runs": without_best_sign_consistent,
            "same_direction_full_and_without_best_across_runs": same_direction_full_vs_without_best,
            "cross_run_direction": (
                "negative" if same_direction_full_vs_without_best and _sign(full_rhos[0]) == -1
                else "positive" if same_direction_full_vs_without_best and _sign(full_rhos[0]) == 1
                else None
            ),
            "median_spearman_across_runs": median(finite_full) if finite_full else None,
            "min_abs_spearman_across_runs": min(abs(value) for value in finite_full) if finite_full else None,
            "min_leave_one_out_sign_consistency_fraction": min(finite_loo) if finite_loo else None,
            "threshold_search_performed": False,
            "inference_role": "CROSS_RUN_RETROSPECTIVE_DISCOVERY_ONLY_NO_EDGE_CLAIM",
        }

    report = {
        "classification": PASS,
        "inference_role": "CROSS_RUN_RETROSPECTIVE_DISCOVERY_ONLY_NO_EDGE_CLAIM",
        "automatic_edge_claim": False,
        "threshold_search_performed": False,
        "selector_changed": False,
        "primary_cohort": PRIMARY_COHORT,
        "run_count": len(sources),
        "sources": [
            {key: value for key, value in source.items() if key != "features"}
            for source in sources
        ],
        "stable_direction_feature_ids": stable_direction_features,
        "features": feature_reports,
        "interpretation": (
            "This artifact compares already-generated routeable-only causal feature associations across independent captures. "
            "It does not search thresholds, combine features, or promote selectors. Stable direction is only hypothesis-generation "
            "evidence; any candidate still requires a new preregistered fresh confirmation."
        ),
    }

    if output_path is not None:
        _write_json(Path(output_path), report)
        report["artifact"] = str(Path(output_path).resolve())
    return report


def _compact(report: dict[str, Any]) -> dict[str, Any]:
    stable = set(report.get("stable_direction_feature_ids") or [])
    return {
        "classification": report.get("classification"),
        "inference_role": report.get("inference_role"),
        "run_count": report.get("run_count"),
        "primary_cohort": report.get("primary_cohort"),
        "stable_direction_feature_ids": sorted(stable),
        "stable_features": {
            key: value
            for key, value in (report.get("features") or {}).items()
            if key in stable
        },
        "threshold_search_performed": report.get("threshold_search_performed"),
        "selector_changed": report.get("selector_changed"),
        "artifact": report.get("artifact"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-run stability check for routeable-only Market-First discovery")
    parser.add_argument("--run-dir", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output
    if output is None:
        output = Path(args.run_dir[0]) / "market-first-cross-run-edge-stability-v0.json"
    try:
        report = run_cross_run_stability_v0(run_dirs=args.run_dir, output_path=output)
    except Exception as exc:
        print(json.dumps({"classification": "FAIL_MARKET_FIRST_CROSS_RUN_EDGE_STABILITY_V0", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(_compact(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
