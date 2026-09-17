from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping

from benchmarks.launch_burst_control_taker_sim_v0.smart_exit import _fixed_rows


VERSION = "launch_burst_concentration_decay_v0"
PASS = "PASS_LAUNCH_BURST_CONCENTRATION_DECAY_V0_EVALUATION"
DEFAULT_POLICY = Path("benchmarks") / "launch_burst_concentration_decay_v0" / "policy.frozen.json"
DEFAULT_CONTRACT = Path("benchmarks") / "launch_burst_prospective_economic_v1" / "pump_route_paper_contract_v2.frozen.json"
FEATURE_ID = "mf_top_wallet_gross_share_delta_pct_points_late_minus_early"


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


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _validate_policy(policy: Mapping[str, Any], contract: Mapping[str, Any]) -> None:
    if policy.get("schema_version") != "launch_burst_concentration_decay_hypothesis_v0":
        raise ValueError("unsupported concentration-decay policy schema")
    if policy.get("status") != "PREREGISTERED_DISCOVERY_ONLY_FRESH_CONFIRMATION_REQUIRED":
        raise ValueError("concentration-decay policy is not preregistered in the expected role")
    expected_hash = str(policy.get("policy_hash_sha256") or "")
    shadow = {key: value for key, value in dict(policy).items() if key != "policy_hash_sha256"}
    actual_hash = hashlib.sha256(_canonical_json(shadow).encode("utf-8")).hexdigest()
    if not expected_hash or actual_hash != expected_hash:
        raise ValueError("concentration-decay policy hash mismatch")

    feature_rule = policy.get("feature_rule") or {}
    if feature_rule.get("feature_id") != FEATURE_ID:
        raise ValueError("unexpected feature in concentration-decay policy")
    if feature_rule.get("op") != "<=" or float(feature_rule.get("value")) != 0.0:
        raise ValueError("concentration-decay threshold contract changed")

    route_hash = str(contract.get("contract_hash_sha256") or "")
    econ = policy.get("economic_contract") or {}
    if econ.get("route_contract_hash_sha256") != route_hash:
        raise ValueError("concentration-decay policy route contract hash mismatch")

    expected = {
        "notional_usd": float(contract["position"]["notional_usd"]),
        "entry_latency_seconds_after_cutoff": int(contract["entry"]["latency_seconds"]),
        "exit_horizon_seconds_after_observed_entry": int(contract["exit"]["horizon_seconds"]),
        "entry_fee_bps": int(contract["costs"]["entry_fee_bps"]),
        "exit_fee_bps": int(contract["costs"]["exit_fee_bps"]),
        "entry_adverse_slippage_bps": int(contract["costs"]["entry_adverse_slippage_bps"]),
        "exit_adverse_slippage_bps": int(contract["costs"]["exit_adverse_slippage_bps"]),
        "max_provider_price_impact_pct_points": float(contract["route_quality"]["max_provider_price_impact_pct_points"]),
        "unroutable_exit_return_pct": float(contract["failure_policy"]["unexitable_return_pct"]),
    }
    for key, value in expected.items():
        observed = econ.get(key)
        if isinstance(value, float):
            if _finite(observed) is None or not math.isclose(float(observed), value, abs_tol=1e-12):
                raise ValueError(f"economic contract field mismatch: {key}")
        elif observed != value:
            raise ValueError(f"economic contract field mismatch: {key}")


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    position = (len(xs) - 1) * fraction
    lo = int(math.floor(position))
    hi = int(math.ceil(position))
    if lo == hi:
        return xs[lo]
    weight = position - lo
    return xs[lo] * (1.0 - weight) + xs[hi] * weight


def _profit_factor(returns: list[float]) -> float | None:
    profits = sum(value for value in returns if value > 0)
    losses = -sum(value for value in returns if value < 0)
    if losses > 0:
        return profits / losses
    if profits > 0:
        return float("inf")
    return None


def _max_drawdown_usd(rows: list[dict[str, Any]], notional: float) -> float:
    ordered = sorted(rows, key=lambda row: (int(row.get("decision_as_of") or 0), str(row.get("episode_key") or "")))
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for row in ordered:
        ret = _finite(row.get("fixed_return_pct"))
        if ret is None:
            continue
        equity += notional * ret / 100.0
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _economic_summary(rows: list[dict[str, Any]], decisions_by_key: Mapping[str, Mapping[str, Any]], *, notional: float) -> dict[str, Any]:
    returns = [float(row["fixed_return_pct"]) for row in rows if _finite(row.get("fixed_return_pct")) is not None]
    gross_returns: list[float] = []
    for row in rows:
        decision = decisions_by_key.get(str(row.get("episode_key") or "")) or {}
        gross = _finite(decision.get("gross_route_return_pct"))
        if gross is not None:
            gross_returns.append(gross)

    positives = [value for value in returns if value > 0]
    without_best = list(returns)
    if without_best:
        without_best.remove(max(without_best))
    top_winner_share = 100.0 * max(positives) / sum(positives) if positives and sum(positives) > 0 else None
    return {
        "n": len(returns),
        "gross_return_available_n": len(gross_returns),
        "mean_gross_return_pct": sum(gross_returns) / len(gross_returns) if gross_returns else None,
        "net_return_pct": {
            "mean": sum(returns) / len(returns) if returns else None,
            "median": median(returns) if returns else None,
            "expectancy_per_trade_pct": sum(returns) / len(returns) if returns else None,
            "p10": _percentile(returns, 0.10),
            "p05": _percentile(returns, 0.05),
            "best": max(returns) if returns else None,
            "worst": min(returns) if returns else None,
            "mean_without_best_trade": sum(without_best) / len(without_best) if without_best else None,
        },
        "win_rate_pct": 100.0 * sum(value > 0 for value in returns) / len(returns) if returns else None,
        "profit_factor": _profit_factor(returns),
        "total_pnl_usd": notional * sum(returns) / 100.0 if returns else 0.0,
        "max_drawdown_usd_on_sequential_pnl_curve": _max_drawdown_usd(rows, notional),
        "largest_winner_share_of_gross_positive_return_pct": top_winner_share,
        "positive_trade_count": sum(value > 0 for value in returns),
        "negative_trade_count": sum(value < 0 for value in returns),
        "zero_trade_count": sum(value == 0 for value in returns),
    }


def _status_summary(keys: set[str], decisions_by_key: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    entry_usable = 0
    exit_failures = 0
    for key in keys:
        decision = decisions_by_key.get(key) or {}
        status = str(decision.get("status") or "MISSING_DECISION")
        statuses[status] = statuses.get(status, 0) + 1
        if status == "ROUTE_CLOSED" or status.startswith("UNROUTABLE_EXIT"):
            entry_usable += 1
        if status.startswith("UNROUTABLE_EXIT"):
            exit_failures += 1
    selected = len(keys)
    return {
        "selected_count": selected,
        "entry_usable_count": entry_usable,
        "routeability_pct": 100.0 * entry_usable / selected if selected else None,
        "entry_failure_count": selected - entry_usable,
        "exit_failure_count": exit_failures,
        "status_counts": dict(sorted(statuses.items())),
    }


def _ordered_number(value: Any) -> float | None:
    """Numeric value usable in ordering checks; infinities are valid PF sentinels, NaN is not."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return None if math.isnan(result) else result


def _gt(left: Any, right: Any) -> bool:
    lvalue, rvalue = _ordered_number(left), _ordered_number(right)
    return lvalue is not None and rvalue is not None and lvalue > rvalue


def _gte(left: Any, right: Any) -> bool:
    lvalue, rvalue = _ordered_number(left), _ordered_number(right)
    return lvalue is not None and rvalue is not None and lvalue >= rvalue


def _classify(*, candidate: Mapping[str, Any], baseline: Mapping[str, Any], signal_frequency_pct: float | None, policy: Mapping[str, Any]) -> tuple[str, dict[str, bool], list[str]]:
    rules = policy.get("decision_rule") or {}
    minimum_n = int(rules.get("minimum_route_usable_candidate_n") or 0)
    minimum_frequency = float(rules.get("minimum_signal_frequency_pct") or 0.0)
    candidate_net = candidate.get("net_return_pct") or {}
    baseline_net = baseline.get("net_return_pct") or {}
    sample_ok = int(candidate.get("n") or 0) >= minimum_n
    frequency_ok = signal_frequency_pct is not None and signal_frequency_pct >= minimum_frequency

    checks = {
        "minimum_sample_and_frequency_met": sample_ok and frequency_ok,
        "candidate_mean_net_return_pct_gt_0": _gt(candidate_net.get("mean"), 0.0),
        "candidate_profit_factor_gt_1": _gt(candidate.get("profit_factor"), 1.0),
        "candidate_mean_without_best_trade_pct_gt_0": _gt(candidate_net.get("mean_without_best_trade"), 0.0),
        "candidate_median_net_return_pct_gt_baseline": _gt(candidate_net.get("median"), baseline_net.get("median")),
        "candidate_p10_net_return_pct_gte_baseline": _gte(candidate_net.get("p10"), baseline_net.get("p10")),
        "candidate_mean_net_return_pct_gt_baseline": _gt(candidate_net.get("mean"), baseline_net.get("mean")),
        "candidate_profit_factor_gt_baseline": _gt(candidate.get("profit_factor"), baseline.get("profit_factor")),
        "candidate_mean_without_best_trade_pct_gt_baseline": _gt(candidate_net.get("mean_without_best_trade"), baseline_net.get("mean_without_best_trade")),
    }

    if not sample_ok or not frequency_ok:
        reasons = []
        if not sample_ok:
            reasons.append("candidate_route_usable_n_below_preregistered_minimum")
        if not frequency_ok:
            reasons.append("signal_frequency_below_preregistered_minimum")
        return "ITERATE", checks, reasons
    if all(checks.get(name) is True for name in (rules.get("keep_if_all") or [])):
        return "KEEP", checks, ["all_preregistered_keep_conditions_passed"]
    if all(checks.get(name) is True for name in (rules.get("iterate_if_all") or [])):
        return "ITERATE", checks, ["relative_separation_is_coherent_but_absolute_robust_profitability_not_yet_met"]
    return "KILL", checks, ["preregistered_keep_and_iterate_conditions_not_met"]


def run_evaluation(*, run_dir: Path, policy_path: Path = DEFAULT_POLICY, contract_path: Path = DEFAULT_CONTRACT, output_path: Path | None = None) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    route_input_path = run_dir / "route-input-v2.json"
    route_result_path = run_dir / "route-result-v2.json"
    dynamics_path = run_dir / "market-first-feature-discovery-v1.json"
    for path in (route_input_path, route_result_path, dynamics_path, policy_path, contract_path):
        if not Path(path).is_file():
            raise ValueError(f"required concentration-decay source missing: {path}")

    route_input = _read_json(route_input_path)
    route_result = _read_json(route_result_path)
    dynamics = _read_json(dynamics_path)
    policy = _read_json(policy_path)
    contract = _read_json(contract_path)
    _validate_policy(policy, contract)

    contract_hash = str(contract.get("contract_hash_sha256") or "")
    if route_input.get("contract_hash_sha256") != contract_hash or route_result.get("contract_hash_sha256") != contract_hash:
        raise ValueError("route source/contract hash mismatch")
    if route_input.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError("feature snapshots were not frozen before provider quotes")
    if dynamics.get("classification") != "PASS_MARKET_FIRST_FEATURE_DISCOVERY_V1":
        raise ValueError("Market-First Feature Discovery V1 artifact is not PASS")
    integrity = dynamics.get("source_integrity") or {}
    if integrity.get("exact_reconstruction_parity") is not True or integrity.get("route_contract_hash_sha256") != contract_hash:
        raise ValueError("Feature Discovery source integrity is not exact")

    decisions = [row for row in (route_result.get("decisions") or []) if isinstance(row, dict)]
    decisions_by_key = {str(row.get("episode_key") or ""): row for row in decisions if str(row.get("episode_key") or "")}
    all_baseline_keys = {str(row.get("episode_key") or "") for row in decisions if row.get("admitted") is True and str(row.get("episode_key") or "")}
    dynamics_by_key = {str(row.get("episode_key") or ""): row for row in (dynamics.get("rows") or []) if isinstance(row, dict) and str(row.get("episode_key") or "")}
    missing_dynamics = sorted(all_baseline_keys - set(dynamics_by_key))
    if missing_dynamics:
        raise ValueError("baseline episodes missing Feature Discovery rows: " + ",".join(missing_dynamics[:10]))

    feature_available_keys: set[str] = set()
    candidate_keys: set[str] = set()
    for key in sorted(all_baseline_keys):
        feature = _finite((dynamics_by_key[key].get("features") or {}).get(FEATURE_ID))
        if feature is None:
            continue
        feature_available_keys.add(key)
        if feature <= 0.0:
            candidate_keys.add(key)

    notional = float(contract["position"]["notional_usd"])
    fixed = _fixed_rows(route_result, notional)
    fixed_by_key = {str(row["episode_key"]): dict(row) for row in fixed}
    all_baseline_fixed = [fixed_by_key[key] for key in all_baseline_keys if key in fixed_by_key]
    eligible_fixed = [fixed_by_key[key] for key in feature_available_keys if key in fixed_by_key]
    candidate_fixed = [fixed_by_key[key] for key in candidate_keys if key in fixed_by_key]

    all_baseline_econ = _economic_summary(all_baseline_fixed, decisions_by_key, notional=notional)
    eligible_baseline_econ = _economic_summary(eligible_fixed, decisions_by_key, notional=notional)
    candidate_econ = _economic_summary(candidate_fixed, decisions_by_key, notional=notional)
    feature_coverage_pct = 100.0 * len(feature_available_keys) / len(all_baseline_keys) if all_baseline_keys else None
    signal_frequency_pct = 100.0 * len(candidate_keys) / len(feature_available_keys) if feature_available_keys else None
    decision, checks, reasons = _classify(candidate=candidate_econ, baseline=eligible_baseline_econ, signal_frequency_pct=signal_frequency_pct, policy=policy)

    report = {
        "type": "launch_burst_concentration_decay_evaluation_v0",
        "version": VERSION,
        "classification": PASS,
        "decision": decision,
        "decision_reasons": reasons,
        "hypothesis_id": policy.get("hypothesis_id"),
        "policy_hash_sha256": policy.get("policy_hash_sha256"),
        "inference_role": "RETROSPECTIVE_DISCOVERY_ONLY_NOT_CONFIRMATION",
        "automatic_edge_claim": False,
        "fresh_confirmation_required": True,
        "threshold_search_performed": False,
        "selector_changed": False,
        "sniper_v1_changed": False,
        "coordination_entity_acquisition_used": False,
        "feature": {
            "feature_id": FEATURE_ID,
            "rule": "<= 0.0 percentage points",
            "semantic_meaning": "top-wallet gross-flow concentration did not increase from the early 2.5s half to the late 2.5s half of the frozen 5s decision window",
            "observed_only_by_decision_cutoff": True,
        },
        "population": {
            "baseline_admitted_count": len(all_baseline_keys),
            "feature_available_count": len(feature_available_keys),
            "feature_coverage_pct": feature_coverage_pct,
            "candidate_selected_count": len(candidate_keys),
            "signal_frequency_pct_of_feature_available_baseline": signal_frequency_pct,
        },
        "routeability": {
            "all_baseline": _status_summary(all_baseline_keys, decisions_by_key),
            "feature_available_baseline": _status_summary(feature_available_keys, decisions_by_key),
            "candidate": _status_summary(candidate_keys, decisions_by_key),
        },
        "economics": {
            "all_baseline_reference": all_baseline_econ,
            "feature_available_baseline_comparator": eligible_baseline_econ,
            "candidate": candidate_econ,
        },
        "economic_assumptions": {
            "route_contract_hash_sha256": contract_hash,
            "notional_usd": notional,
            "fees_bps": {"entry": int(contract["costs"]["entry_fee_bps"]), "exit": int(contract["costs"]["exit_fee_bps"])},
            "adverse_slippage_bps": {"entry": int(contract["costs"]["entry_adverse_slippage_bps"]), "exit": int(contract["costs"]["exit_adverse_slippage_bps"])},
            "entry_latency_seconds_after_cutoff": int(contract["entry"]["latency_seconds"]),
            "exit_horizon_seconds_after_observed_entry": int(contract["exit"]["horizon_seconds"]),
            "max_provider_price_impact_pct_points": float(contract["route_quality"]["max_provider_price_impact_pct_points"]),
            "unroutable_exit_return_pct": float(contract["failure_policy"]["unexitable_return_pct"]),
        },
        "decision_rule_checks": checks,
        "source_integrity": {
            "run_dir": str(run_dir),
            "feature_snapshot_frozen_before_provider_quotes": True,
            "feature_discovery_exact_reconstruction_parity": True,
            "route_contract_hash_sha256": contract_hash,
            "route_input_episode_count": len(route_input.get("episodes") or []),
            "route_result_decision_count": len(decisions),
        },
        "interpretation": "This is a preregistered retrospective discovery evaluation of one semantic threshold. KEEP means only worth testing on a fresh causal capture; it is not prospective edge proof. KILL means do not rescue this exact hypothesis with same-sample retuning. ITERATE permits only one clearly justified follow-up.",
    }
    destination = output_path or (run_dir / "concentration-decay-evaluation-v0.json")
    _write_json(Path(destination), report)
    report["artifact"] = str(Path(destination).resolve())
    return report


def _compact(report: Mapping[str, Any]) -> dict[str, Any]:
    economics = report.get("economics") or {}
    return {
        "classification": report.get("classification"),
        "decision": report.get("decision"),
        "decision_reasons": report.get("decision_reasons"),
        "hypothesis_id": report.get("hypothesis_id"),
        "policy_hash_sha256": report.get("policy_hash_sha256"),
        "population": report.get("population"),
        "routeability": report.get("routeability"),
        "baseline": economics.get("feature_available_baseline_comparator"),
        "candidate": economics.get("candidate"),
        "decision_rule_checks": report.get("decision_rule_checks"),
        "artifact": report.get("artifact"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Preregistered retrospective test of non-increasing top-wallet concentration inside the frozen 5s Launch Burst window.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_evaluation(run_dir=args.run_dir, policy_path=args.policy, contract_path=args.contract, output_path=args.output)
    except Exception as exc:
        print(json.dumps({"classification": "FAIL_LAUNCH_BURST_CONCENTRATION_DECAY_V0_EVALUATION", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(_compact(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
