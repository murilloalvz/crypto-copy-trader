from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.launch_burst_opportunity_lab_v0.analyze import (
    DEFAULT_CONTRACT,
    _auc_higher_in_positive,
    _feature_rows,
    _leave_one_positive_out_auc,
    _median,
    _read_json,
    _resolve_artifacts,
)


VERSION = "launch_burst_copyability_diagnostics_v0"
PASS = "PASS_LAUNCH_BURST_COPYABILITY_DIAGNOSTICS_V0"


def _feature_stat(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [row for row in rows if name in row["features"]]
    closed = [
        float(row["features"][name])
        for row in observed
        if str(row["status"]) == "ROUTE_CLOSED"
    ]
    unroutable = [
        float(row["features"][name])
        for row in observed
        if str(row["status"]).startswith("UNROUTABLE_EXIT")
    ]
    auc = _auc_higher_in_positive(closed, unroutable)
    coverage = 100.0 * len(observed) / len(rows) if rows else None
    robustness = _leave_one_positive_out_auc(closed, unroutable)
    direction = None
    if auc is not None:
        direction = "HIGHER_IN_ROUTE_CLOSED" if auc > 0.5 else (
            "LOWER_IN_ROUTE_CLOSED" if auc < 0.5 else "NO_DIRECTION"
        )
    enough = len(closed) >= 3 and len(unroutable) >= 3 and (coverage or 0.0) >= 80.0
    stable = bool(robustness.get("same_direction_all_folds"))
    if not enough:
        priority = "INSUFFICIENT_SAMPLE_OR_COVERAGE"
    elif auc is not None and abs(auc - 0.5) >= 0.15 and stable:
        priority = "COPYABILITY_RESEARCH_PRIORITY"
    elif auc is not None and abs(auc - 0.5) >= 0.10:
        priority = "COPYABILITY_EXPLORATORY_SIGNAL"
    else:
        priority = "WEAK_DESCRIPTIVE_SEPARATION"
    return {
        "feature": name,
        "observed_count": len(observed),
        "coverage_pct": coverage,
        "route_closed_count": len(closed),
        "unroutable_exit_count": len(unroutable),
        "route_closed_median": _median(closed),
        "unroutable_median": _median(unroutable),
        "auc_probability_higher_value_in_route_closed": auc,
        "direction": direction,
        "auc_separation_strength_0_to_1": 2.0 * abs(auc - 0.5) if auc is not None else None,
        "leave_one_route_closed_out": robustness,
        "hypothesis_generation_status": priority,
        "threshold_recommendation": None,
    }


def analyze_copyability(*, run_dir: Path, contract_path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    artifacts = _resolve_artifacts(run_dir)
    route_input_path = artifacts["route_input"]
    route_result_path = artifacts["route_result"]
    assert isinstance(route_input_path, Path)
    assert isinstance(route_result_path, Path)
    contract = _read_json(contract_path)
    route_input = _read_json(route_input_path)
    route_result = _read_json(route_result_path)
    route_hash = str(contract.get("contract_hash_sha256") or "")
    if route_input.get("contract_hash_sha256") != route_hash or route_result.get("contract_hash_sha256") != route_hash:
        raise ValueError("copyability diagnostics route contract mismatch")
    notional = float(contract["position"]["notional_usd"])
    rows = _feature_rows(route_input=route_input, route_result=route_result, notional=notional)
    names = sorted({name for row in rows for name in row["features"]})
    stats = [_feature_stat(name, rows) for name in names]
    stats.sort(
        key=lambda row: (
            row["hypothesis_generation_status"] != "COPYABILITY_RESEARCH_PRIORITY",
            -(float(row["auc_separation_strength_0_to_1"]) if row["auc_separation_strength_0_to_1"] is not None else -1.0),
            row["feature"],
        )
    )
    closed_count = sum(str(row["status"]) == "ROUTE_CLOSED" for row in rows)
    unroutable_count = sum(str(row["status"]).startswith("UNROUTABLE_EXIT") for row in rows)
    return {
        "type": "launch_burst_copyability_diagnostics",
        "version": VERSION,
        "classification": PASS,
        "inference_role": "OFFLINE_HYPOTHESIS_GENERATION_ONLY",
        "run_dir": str(Path(run_dir).resolve()),
        "route_result_file": route_result_path.name,
        "route_closed_count": closed_count,
        "unroutable_exit_count": unroutable_count,
        "feature_separation": stats,
        "research_priority_features": [
            row for row in stats if row["hypothesis_generation_status"] == "COPYABILITY_RESEARCH_PRIORITY"
        ],
        "guardrails": {
            "profitability_and_copyability_kept_separate": True,
            "same_sample_threshold_search_performed": False,
            "threshold_recommendations_emitted": False,
            "route_shadow_is_not_landed_fill": True,
            "results_are_hypothesis_generation_not_validation": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline copyability diagnostics for Launch Burst route-shadow outcomes")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = analyze_copyability(run_dir=args.run_dir, contract_path=args.contract)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        compact = {
            "classification": report["classification"],
            "run_dir": report["run_dir"],
            "route_result_file": report["route_result_file"],
            "route_closed_count": report["route_closed_count"],
            "unroutable_exit_count": report["unroutable_exit_count"],
            "research_priority_features": report["research_priority_features"][:15],
        }
        print(json.dumps(compact, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"classification": "FAIL_LAUNCH_BURST_COPYABILITY_DIAGNOSTICS_V0", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
