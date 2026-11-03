from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable, Mapping

from benchmarks.launch_burst_control_taker_sim_v0.smart_exit import _aggregate, _fixed_rows
from benchmarks.launch_burst_sniper_v1.strict_compare import validate_sniper_source_integrity_v1
from src.launch_burst_sniper_v1 import load_sniper_policy_v1


VERSION = "launch_burst_opportunity_selection_lab_v0"
PASS = "PASS_LAUNCH_BURST_OPPORTUNITY_SELECTION_LAB_V0"
DEFAULT_CONTRACT = Path("benchmarks") / "launch_burst_prospective_economic_v1" / "pump_route_paper_contract_v2.frozen.json"
DEFAULT_SNIPER_POLICY = Path("benchmarks") / "launch_burst_sniper_v1" / "sniper_policy_v1.frozen.json"

# These names are metadata/validity markers rather than market-state quantities.
_EXCLUDED_FEATURE_TOKENS = (
    "version",
    "available",
    "valid",
)


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


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _flatten_numeric(value: Any, *, prefix: str = "") -> dict[str, float]:
    output: dict[str, float] = {}
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            output.update(_flatten_numeric(child, prefix=name))
        return output
    number = _finite_number(value)
    if number is not None and prefix:
        lowered = prefix.lower()
        if not any(token in lowered for token in _EXCLUDED_FEATURE_TOKENS):
            output[prefix] = number
    return output


def _rankdata(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda pair: pair[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        rank = (start + 1 + end) / 2.0
        for position in range(start, end):
            ranks[indexed[position][0]] = rank
        start = end
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    dx = [value - mean_x for value in xs]
    dy = [value - mean_y for value in ys]
    den = math.sqrt(sum(value * value for value in dx) * sum(value * value for value in dy))
    if den <= 0:
        return None
    value = sum(a * b for a, b in zip(dx, dy)) / den
    return value if math.isfinite(value) else None


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    return _pearson(_rankdata(xs), _rankdata(ys))


def _auc_higher_in_positive(positive: list[float], nonpositive: list[float]) -> float | None:
    if not positive or not nonpositive:
        return None
    score = 0.0
    pairs = 0
    for win in positive:
        for loss in nonpositive:
            pairs += 1
            if win > loss:
                score += 1.0
            elif win == loss:
                score += 0.5
    return score / pairs if pairs else None


def _leave_one_positive_out_auc(positive: list[float], nonpositive: list[float]) -> dict[str, Any]:
    if len(positive) < 3 or not nonpositive:
        return {"available": False, "auc_min": None, "auc_max": None, "same_direction_all_folds": None}
    values = []
    for index in range(len(positive)):
        fold = positive[:index] + positive[index + 1 :]
        auc = _auc_higher_in_positive(fold, nonpositive)
        if auc is not None:
            values.append(auc)
    if not values:
        return {"available": False, "auc_min": None, "auc_max": None, "same_direction_all_folds": None}
    original = _auc_higher_in_positive(positive, nonpositive)
    if original is None or original == 0.5:
        same = False
    elif original > 0.5:
        same = all(value > 0.5 for value in values)
    else:
        same = all(value < 0.5 for value in values)
    return {
        "available": True,
        "auc_min": min(values),
        "auc_max": max(values),
        "same_direction_all_folds": same,
    }


def _predicate_pass(value: float, op: str, threshold: float) -> bool:
    if op == ">=":
        return value >= threshold
    if op == "<=":
        return value <= threshold
    if op == ">":
        return value > threshold
    if op == "<":
        return value < threshold
    if op == "==":
        return value == threshold
    raise ValueError(f"unsupported predicate op: {op}")


def _resolve_artifacts(run_dir: Path) -> dict[str, Path | None]:
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise ValueError(f"run directory not found: {run_dir}")
    route_input = run_dir / "route-input-v2.json"
    route_result_candidates = [
        run_dir / "route-result-v2-price-impact-semantics-fix-v0.json",
        run_dir / "route-result-v2.json",
    ]
    smart_candidates = [
        run_dir / "smart-ladder-25-result-price-impact-semantics-fix-v0.json",
        run_dir / "smart-ladder-25-result-v0.json",
    ]
    route_result = next((path for path in route_result_candidates if path.is_file()), None)
    smart = next((path for path in smart_candidates if path.is_file()), None)
    if not route_input.is_file():
        raise ValueError(f"missing route input: {route_input}")
    if route_result is None:
        raise ValueError(f"no supported route result in {run_dir}")
    return {"route_input": route_input, "route_result": route_result, "smart_result": smart}


def _feature_rows(
    *,
    route_input: Mapping[str, Any],
    route_result: Mapping[str, Any],
    notional: float,
) -> list[dict[str, Any]]:
    inputs = {str(row.get("episode_key") or ""): row for row in route_input.get("episodes") or []}
    fixed = _fixed_rows(route_result, notional)
    rows: list[dict[str, Any]] = []
    for outcome in fixed:
        key = str(outcome["episode_key"])
        episode = inputs.get(key)
        if not isinstance(episode, Mapping):
            raise ValueError(f"economic episode missing input row: {key}")
        snapshot = episode.get("feature_snapshot")
        if not isinstance(snapshot, Mapping):
            raise ValueError(f"economic episode missing frozen feature snapshot: {key}")
        if snapshot.get("complete") is not True:
            raise ValueError(f"economic episode has incomplete snapshot: {key}")
        if snapshot.get("stratum") != "pump_launch":
            raise ValueError(f"unsupported economic stratum in offline lab: {key}")
        if int(snapshot.get("evidence_window_seconds") or 0) != 5:
            raise ValueError(f"unexpected evidence window in offline lab: {key}")
        features = snapshot.get("features")
        if not isinstance(features, Mapping):
            raise ValueError(f"economic episode missing features object: {key}")
        return_pct = float(outcome["fixed_return_pct"])
        rows.append(
            {
                "episode_key": key,
                "token_mint": str(outcome.get("token_mint") or ""),
                "status": str(outcome.get("status") or ""),
                "fixed_return_pct": return_pct,
                "fixed_pnl_usd": float(outcome["fixed_pnl_usd"]),
                "positive": return_pct > 0.0,
                "severe_loss": return_pct <= -20.0,
                "features": _flatten_numeric(features),
            }
        )
    return rows


def _feature_stat(name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [row for row in rows if name in row["features"]]
    positive = [float(row["features"][name]) for row in observed if row["positive"]]
    nonpositive = [float(row["features"][name]) for row in observed if not row["positive"]]
    values = [float(row["features"][name]) for row in observed]
    returns = [float(row["fixed_return_pct"]) for row in observed]
    auc = _auc_higher_in_positive(positive, nonpositive)
    leave_one = _leave_one_positive_out_auc(positive, nonpositive)
    coverage = 100.0 * len(observed) / len(rows) if rows else None
    direction = None
    if auc is not None:
        direction = "HIGHER_IN_POSITIVE" if auc > 0.5 else ("LOWER_IN_POSITIVE" if auc < 0.5 else "NO_DIRECTION")
    strength = 2.0 * abs(auc - 0.5) if auc is not None else None
    enough = len(positive) >= 3 and len(nonpositive) >= 10 and (coverage or 0.0) >= 80.0
    stable = bool(leave_one.get("same_direction_all_folds"))
    if not enough:
        priority = "INSUFFICIENT_SAMPLE_OR_COVERAGE"
    elif auc is not None and abs(auc - 0.5) >= 0.15 and stable:
        priority = "RESEARCH_PRIORITY"
    elif auc is not None and abs(auc - 0.5) >= 0.10:
        priority = "EXPLORATORY_SIGNAL"
    else:
        priority = "WEAK_DESCRIPTIVE_SEPARATION"
    return {
        "feature": name,
        "observed_count": len(observed),
        "coverage_pct": coverage,
        "positive_count": len(positive),
        "nonpositive_count": len(nonpositive),
        "positive_median": _median(positive),
        "nonpositive_median": _median(nonpositive),
        "median_difference_positive_minus_nonpositive": (
            _median(positive) - _median(nonpositive) if positive and nonpositive else None
        ),
        "auc_probability_higher_value_in_positive": auc,
        "direction": direction,
        "auc_separation_strength_0_to_1": strength,
        "leave_one_positive_out": leave_one,
        "spearman_feature_vs_return": _spearman(values, returns),
        "hypothesis_generation_status": priority,
        "threshold_recommendation": None,
    }


def _summary_without_top_winners(rows: list[dict[str, Any]], notional: float) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: float(row["fixed_return_pct"]), reverse=True)
    result: dict[str, Any] = {}
    for count in (0, 1, 2):
        sample = ordered[count:] if len(ordered) > count else []
        aggregate_rows = [
            {"fixed_pnl_usd": row["fixed_pnl_usd"]}
            for row in sample
        ]
        result[f"remove_top_{count}"] = _aggregate(aggregate_rows, "fixed_pnl_usd", notional)
    return result


def _single_gate_diagnostics(
    *,
    rows: list[dict[str, Any]],
    policy: Mapping[str, Any],
    notional: float,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for predicate in (policy.get("primary_selector") or {}).get("predicates") or []:
        feature = str(predicate.get("feature") or "")
        op = str(predicate.get("op") or "")
        threshold = float(predicate.get("value"))
        passed: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        missing: list[dict[str, Any]] = []
        for row in rows:
            value = row["features"].get(feature)
            bucket_row = {"fixed_pnl_usd": row["fixed_pnl_usd"]}
            if value is None:
                missing.append(bucket_row)
            elif _predicate_pass(float(value), op, threshold):
                passed.append(bucket_row)
            else:
                failed.append(bucket_row)
        pass_summary = _aggregate(passed, "fixed_pnl_usd", notional)
        fail_summary = _aggregate(failed, "fixed_pnl_usd", notional)
        p_mean = pass_summary.get("mean_return_pct")
        f_mean = fail_summary.get("mean_return_pct")
        expected_direction = "PASS_BETTER_THAN_FAIL"
        observed_direction = None
        if isinstance(p_mean, (int, float)) and isinstance(f_mean, (int, float)):
            observed_direction = "PASS_BETTER_THAN_FAIL" if p_mean > f_mean else (
                "PASS_WORSE_THAN_FAIL" if p_mean < f_mean else "NO_DIFFERENCE"
            )
        output.append(
            {
                "feature": feature,
                "op": op,
                "threshold": threshold,
                "threshold_origin": "PREREGISTERED_SNIPER_V1_BEFORE_SCREENING_OUTCOMES",
                "pass": pass_summary,
                "fail": fail_summary,
                "missing_count": len(missing),
                "observed_direction": observed_direction,
                "aligned_with_original_gate_intent": observed_direction == expected_direction if observed_direction else None,
                "mean_return_pass_minus_fail_pct_points": (
                    float(p_mean) - float(f_mean)
                    if isinstance(p_mean, (int, float)) and isinstance(f_mean, (int, float))
                    else None
                ),
                "retuning_permitted_from_this_sample": False,
            }
        )
    return output


def analyze_run(
    *,
    run_dir: Path,
    contract_path: Path,
    sniper_policy_path: Path,
) -> dict[str, Any]:
    artifacts = _resolve_artifacts(run_dir)
    route_input_path = artifacts["route_input"]
    route_result_path = artifacts["route_result"]
    smart_path = artifacts["smart_result"]
    assert isinstance(route_input_path, Path)
    assert isinstance(route_result_path, Path)
    integrity = validate_sniper_source_integrity_v1(
        route_input_path=route_input_path,
        route_result_path=route_result_path,
        smart_result_path=smart_path if isinstance(smart_path, Path) else None,
    )
    contract = _read_json(contract_path)
    sniper_policy = load_sniper_policy_v1(sniper_policy_path)
    route_input = _read_json(route_input_path)
    route_result = _read_json(route_result_path)
    route_hash = str(contract.get("contract_hash_sha256") or "")
    if route_input.get("contract_hash_sha256") != route_hash or route_result.get("contract_hash_sha256") != route_hash:
        raise ValueError("offline lab route contract mismatch")
    notional = float(contract["position"]["notional_usd"])
    rows = _feature_rows(route_input=route_input, route_result=route_result, notional=notional)
    feature_names = sorted({name for row in rows for name in row["features"]})
    stats = [_feature_stat(name, rows) for name in feature_names]
    stats.sort(
        key=lambda item: (
            item["hypothesis_generation_status"] != "RESEARCH_PRIORITY",
            -(float(item["auc_separation_strength_0_to_1"]) if item["auc_separation_strength_0_to_1"] is not None else -1.0),
            item["feature"],
        )
    )
    severe_losses = sum(bool(row["severe_loss"]) for row in rows)
    positives = sum(bool(row["positive"]) for row in rows)
    base_summary = _aggregate(
        [{"fixed_pnl_usd": row["fixed_pnl_usd"]} for row in rows],
        "fixed_pnl_usd",
        notional,
    )
    return {
        "run_dir": str(Path(run_dir).resolve()),
        "route_result_file": route_result_path.name,
        "source_integrity": integrity,
        "economic_sample": {
            "fixed_60s": base_summary,
            "positive_count": positives,
            "nonpositive_count": len(rows) - positives,
            "severe_loss_le_minus_20_pct_count": severe_losses,
            "unroutable_count": sum(str(row["status"]).startswith("UNROUTABLE_EXIT") for row in rows),
            "fragility": _summary_without_top_winners(rows, notional),
        },
        "numeric_causal_feature_count": len(stats),
        "feature_separation": stats,
        "research_priority_features": [
            item for item in stats if item["hypothesis_generation_status"] == "RESEARCH_PRIORITY"
        ],
        "preregistered_sniper_v1_single_gate_diagnostics": _single_gate_diagnostics(
            rows=rows,
            policy=sniper_policy,
            notional=notional,
        ),
        "guardrails": {
            "offline_only": True,
            "network_calls_performed": False,
            "features_read_only_from_frozen_pre_provider_snapshot": True,
            "outcomes_used_only_as_labels_for_hypothesis_generation": True,
            "same_sample_threshold_search_performed": False,
            "model_fit_performed": False,
            "policy_mutated": False,
            "threshold_recommendations_emitted": False,
            "results_are_hypothesis_generation_not_validation": True,
        },
    }


def _replication_across_runs(run_reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(run_reports) < 2:
        return []
    by_run = []
    for report in run_reports:
        by_run.append({item["feature"]: item for item in report["feature_separation"]})
    common = set(by_run[0])
    for mapping in by_run[1:]:
        common &= set(mapping)
    output = []
    for feature in sorted(common):
        rows = [mapping[feature] for mapping in by_run]
        usable = [row for row in rows if row.get("auc_probability_higher_value_in_positive") is not None]
        if len(usable) != len(rows):
            continue
        directions = [row.get("direction") for row in usable]
        same_direction = len(set(directions)) == 1 and directions[0] != "NO_DIRECTION"
        strengths = [float(row["auc_separation_strength_0_to_1"]) for row in usable]
        stable_each = all(bool((row.get("leave_one_positive_out") or {}).get("same_direction_all_folds")) for row in usable)
        output.append(
            {
                "feature": feature,
                "run_count": len(rows),
                "directions": directions,
                "same_direction_across_runs": same_direction,
                "min_auc_separation_strength": min(strengths),
                "max_auc_separation_strength": max(strengths),
                "leave_one_positive_out_direction_stable_in_every_run": stable_each,
                "cross_run_hypothesis_priority": (
                    "REPLICATED_DIRECTION_PRIORITY"
                    if same_direction and min(strengths) >= 0.20 and stable_each
                    else "NO_REPLICATED_PRIORITY"
                ),
                "threshold_recommendation": None,
            }
        )
    output.sort(
        key=lambda row: (
            row["cross_run_hypothesis_priority"] != "REPLICATED_DIRECTION_PRIORITY",
            -row["min_auc_separation_strength"],
            row["feature"],
        )
    )
    return output


def run_lab(
    *,
    run_dirs: Iterable[Path],
    contract_path: Path = DEFAULT_CONTRACT,
    sniper_policy_path: Path = DEFAULT_SNIPER_POLICY,
    output_path: Path | None = None,
) -> dict[str, Any]:
    run_dirs = [Path(path) for path in run_dirs]
    if not run_dirs:
        raise ValueError("at least one --run-dir is required")
    reports = [
        analyze_run(run_dir=path, contract_path=contract_path, sniper_policy_path=sniper_policy_path)
        for path in run_dirs
    ]
    cross = _replication_across_runs(reports)
    result = {
        "type": "launch_burst_opportunity_selection_lab_report",
        "version": VERSION,
        "classification": PASS,
        "inference_role": "OFFLINE_HYPOTHESIS_GENERATION_ONLY",
        "run_count": len(reports),
        "runs": reports,
        "cross_run_feature_replication": cross,
        "replicated_direction_priority_features": [
            row for row in cross if row["cross_run_hypothesis_priority"] == "REPLICATED_DIRECTION_PRIORITY"
        ],
        "next_protocol_constraints": {
            "do_not_change_frozen_momentum_v0": True,
            "do_not_select_new_thresholds_from_these_outcomes": True,
            "candidate_features_must_be_preregistered_before_future_validation": True,
            "prefer_features_with_cross_run_direction_replication": True,
            "narrative_or_social_features_require_their_own_causal_timestamp_before_use": True,
            "wallet_identity_features_can_be_reused_only_when_coverage_is_measured": True,
        },
    }
    if output_path is None:
        output_path = run_dirs[0] / "opportunity-selection-lab-v0.json"
    _write_json(output_path, result)
    result["output_path"] = str(Path(output_path).resolve())
    return result


def _compact(report: dict[str, Any]) -> dict[str, Any]:
    runs = []
    for run in report["runs"]:
        runs.append(
            {
                "run_dir": run["run_dir"],
                "route_result_file": run["route_result_file"],
                "economic_sample": run["economic_sample"],
                "research_priority_features": run["research_priority_features"][:10],
                "single_gate_diagnostics": run["preregistered_sniper_v1_single_gate_diagnostics"],
            }
        )
    return {
        "classification": report["classification"],
        "inference_role": report["inference_role"],
        "run_count": report["run_count"],
        "runs": runs,
        "replicated_direction_priority_features": report["replicated_direction_priority_features"][:15],
        "output_path": report.get("output_path"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline causal feature separation lab for existing Launch Burst artifacts")
    parser.add_argument("--run-dir", action="append", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--sniper-policy", type=Path, default=DEFAULT_SNIPER_POLICY)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_lab(
            run_dirs=args.run_dir,
            contract_path=args.contract,
            sniper_policy_path=args.sniper_policy,
            output_path=args.output,
        )
    except Exception as exc:
        print(json.dumps({"classification": "FAIL_LAUNCH_BURST_OPPORTUNITY_SELECTION_LAB_V0", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(_compact(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
