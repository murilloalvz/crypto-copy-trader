from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
from typing import Any, Mapping

from benchmarks.launch_burst_control_taker_sim_v0.smart_exit import (
    _aggregate,
    _fixed_rows,
    _read_json,
    _write_json,
)
from src.launch_burst_sniper_v1 import (
    evaluate_launch_burst_sniper_v1,
    load_sniper_policy_v1,
    sniper_decision_to_dict_v1,
)


COMPARISON_VERSION = "launch_burst_sniper_comparison_v1"
PASS_CLASSIFICATION = "PASS_LAUNCH_BURST_SNIPER_COMPARISON_V1"


def _status_summary(decisions: list[dict[str, Any]], keys: set[str]) -> dict[str, Any]:
    rows = [item for item in decisions if str(item.get("episode_key") or "") in keys]
    statuses = Counter(str(item.get("status") or "UNKNOWN") for item in rows)
    entry_usable = sum(
        1
        for item in rows
        if str(item.get("status") or "") == "ROUTE_CLOSED"
        or str(item.get("status") or "").startswith("UNROUTABLE_EXIT")
    )
    return {
        "selected_count": len(rows),
        "status_counts": dict(sorted(statuses.items())),
        "entry_usable_count": entry_usable,
        "entry_usable_pct": 100.0 * entry_usable / len(rows) if rows else None,
    }


def _robustness(rows: list[dict[str, Any]], *, pnl_key: str, notional: float) -> dict[str, Any]:
    pnls = [float(item[pnl_key]) for item in rows if item.get(pnl_key) is not None]
    returns = [100.0 * pnl / notional for pnl in pnls]
    positive = [pnl for pnl in pnls if pnl > 0]
    mean_without_best = None
    if len(returns) >= 2:
        without_best = list(returns)
        without_best.remove(max(without_best))
        mean_without_best = sum(without_best) / len(without_best)
    positive_total = sum(positive)
    best_profit_concentration = max(positive) / positive_total if positive and positive_total > 0 else None
    return {
        "mean_return_pct_without_best_trade": mean_without_best,
        "best_positive_pnl_share": best_profit_concentration,
        "negative_trade_count": sum(pnl < 0 for pnl in pnls),
        "zero_trade_count": sum(pnl == 0 for pnl in pnls),
        "positive_trade_count": sum(pnl > 0 for pnl in pnls),
    }


def _counterfactual_skip_value(rows: list[dict[str, Any]], *, pnl_key: str) -> dict[str, Any]:
    pnls = [float(item[pnl_key]) for item in rows if item.get(pnl_key) is not None]
    skipped_pnl = sum(pnls)
    return {
        "skipped_trade_count": len(pnls),
        "skipped_trade_pnl_usd": skipped_pnl,
        "counterfactual_value_of_skipping_usd": -skipped_pnl,
        "avoided_negative_trade_count": sum(pnl < 0 for pnl in pnls),
        "missed_positive_trade_count": sum(pnl > 0 for pnl in pnls),
        "avoided_loss_magnitude_usd": sum(-pnl for pnl in pnls if pnl < 0),
        "missed_profit_usd": sum(pnl for pnl in pnls if pnl > 0),
    }


def _screening_status(*, usable_count: int, policy: Mapping[str, Any]) -> str:
    gates = policy.get("evaluation_gates") or {}
    directional = int(gates.get("minimum_primary_usable_route_results_for_directional_read") or 0)
    replication = int(gates.get("minimum_primary_usable_route_results_before_replication") or 0)
    if usable_count < directional:
        return "INSUFFICIENT_PRIMARY_SAMPLE"
    if usable_count < replication:
        return "DIRECTIONAL_READ_AVAILABLE_REPLICATION_NOT_ARMED"
    return "REPLICATION_SAMPLE_SIZE_ELIGIBLE_FRESH_RUN_STILL_REQUIRED"


def _selector_rows(
    *,
    episodes: list[dict[str, Any]],
    policy: Mapping[str, Any],
    selector_name: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        snapshot = episode.get("feature_snapshot")
        if not isinstance(snapshot, Mapping):
            continue
        decision = evaluate_launch_burst_sniper_v1(
            snapshot=snapshot,
            policy=policy,
            selector_name=selector_name,
        )
        row = sniper_decision_to_dict_v1(decision)
        row["episode_key"] = str(episode.get("episode_key") or "")
        row["token_mint"] = str(episode.get("token_mint") or "")
        rows.append(row)
    return rows


def _reason_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        for reason in row.get("reasons") or []:
            counts[str(reason)] += 1
    return dict(sorted(counts.items()))


def _metric_delta(primary: Mapping[str, Any], baseline: Mapping[str, Any], name: str) -> float | None:
    p = primary.get(name)
    b = baseline.get(name)
    if isinstance(p, bool) or isinstance(b, bool) or not isinstance(p, (int, float)) or not isinstance(b, (int, float)):
        return None
    pf, bf = float(p), float(b)
    if not math.isfinite(pf) or not math.isfinite(bf):
        return None
    return pf - bf


def run_sniper_comparison_v1(
    *,
    contract_path: Path,
    policy_path: Path,
    route_input_path: Path,
    route_result_path: Path,
    smart_result_path: Path | None,
    output_path: Path,
) -> dict[str, Any]:
    contract = _read_json(contract_path)
    policy = load_sniper_policy_v1(policy_path)
    route_input = _read_json(route_input_path)
    route_result = _read_json(route_result_path)

    route_hash = str(contract.get("contract_hash_sha256") or "")
    if route_hash != policy.get("route_contract_hash_sha256"):
        raise ValueError("sniper/route contract hash mismatch")
    if route_input.get("contract_hash_sha256") != route_hash:
        raise ValueError("route input contract hash mismatch")
    if route_result.get("contract_hash_sha256") != route_hash:
        raise ValueError("route result contract hash mismatch")
    if route_input.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError("sniper comparison requires pre-provider frozen feature snapshots")

    episodes = list(route_input.get("episodes") or [])
    decisions = list(route_result.get("decisions") or [])
    if len(episodes) != len(decisions):
        raise ValueError("route input/result episode count mismatch")

    baseline_selected_keys = {
        str(item.get("episode_key") or "")
        for item in decisions
        if item.get("admitted") is True
    }
    primary_rows = _selector_rows(episodes=episodes, policy=policy, selector_name="primary_selector")
    diagnostic_rows = _selector_rows(episodes=episodes, policy=policy, selector_name="diagnostic_selector")
    primary_selected_all = {row["episode_key"] for row in primary_rows if row.get("selected") is True}
    diagnostic_selected_all = {row["episode_key"] for row in diagnostic_rows if row.get("selected") is True}

    outside_baseline = sorted(primary_selected_all - baseline_selected_keys)
    if outside_baseline:
        raise ValueError("primary sniper selector escaped the frozen baseline universe")
    primary_keys = primary_selected_all & baseline_selected_keys
    diagnostic_keys = diagnostic_selected_all & baseline_selected_keys

    notional = float(contract["position"]["notional_usd"])
    fixed_all = _fixed_rows(route_result, notional)
    fixed_baseline = [row for row in fixed_all if row["episode_key"] in baseline_selected_keys]
    fixed_primary = [row for row in fixed_all if row["episode_key"] in primary_keys]
    fixed_skipped = [row for row in fixed_baseline if row["episode_key"] not in primary_keys]
    fixed_diagnostic = [row for row in fixed_all if row["episode_key"] in diagnostic_keys]

    baseline_fixed_summary = _aggregate(fixed_baseline, "fixed_pnl_usd", notional)
    primary_fixed_summary = _aggregate(fixed_primary, "fixed_pnl_usd", notional)
    skipped_fixed_summary = _aggregate(fixed_skipped, "fixed_pnl_usd", notional)
    diagnostic_fixed_summary = _aggregate(fixed_diagnostic, "fixed_pnl_usd", notional)

    smart_section = None
    if smart_result_path is not None:
        smart_result = _read_json(smart_result_path)
        if smart_result.get("route_contract_hash_sha256") != route_hash:
            raise ValueError("SMART-LADDER result route contract hash mismatch")
        smart_rows = [
            dict(item)
            for item in smart_result.get("trades") or []
            if item.get("smart_pnl_usd") is not None
        ]
        smart_baseline = [row for row in smart_rows if row.get("episode_key") in baseline_selected_keys]
        smart_primary = [row for row in smart_rows if row.get("episode_key") in primary_keys]
        smart_skipped = [row for row in smart_baseline if row.get("episode_key") not in primary_keys]
        smart_section = {
            "inference_role": "EXPLORATORY_EXIT_ONLY",
            "baseline": _aggregate(smart_baseline, "smart_pnl_usd", notional),
            "primary_sniper": _aggregate(smart_primary, "smart_pnl_usd", notional),
            "skipped_by_primary": _aggregate(smart_skipped, "smart_pnl_usd", notional),
            "counterfactual_skip": _counterfactual_skip_value(smart_skipped, pnl_key="smart_pnl_usd"),
            "primary_robustness": _robustness(smart_primary, pnl_key="smart_pnl_usd", notional=notional),
        }

    primary_usable = len(fixed_primary)
    result = {
        "type": "launch_burst_sniper_comparison",
        "version": COMPARISON_VERSION,
        "classification": PASS_CLASSIFICATION,
        "route_contract_hash_sha256": route_hash,
        "sniper_policy_hash_sha256": policy["policy_hash_sha256"],
        "baseline_selector": "FROZEN_SIGNED_FLOW_GE_0_08",
        "primary_selector": policy.get("policy_name"),
        "episode_count": len(episodes),
        "baseline_selected_count": len(baseline_selected_keys),
        "primary_selected_count": len(primary_keys),
        "diagnostic_selected_count": len(diagnostic_keys),
        "primary_selection_rate_pct_of_baseline": (
            100.0 * len(primary_keys) / len(baseline_selected_keys)
            if baseline_selected_keys
            else None
        ),
        "coverage": {
            "baseline": _status_summary(decisions, baseline_selected_keys),
            "primary_sniper": _status_summary(decisions, primary_keys),
            "diagnostic": _status_summary(decisions, diagnostic_keys),
        },
        "fixed_60s_primary_benchmark": {
            "baseline": baseline_fixed_summary,
            "primary_sniper": primary_fixed_summary,
            "diagnostic_only": diagnostic_fixed_summary,
            "skipped_by_primary": skipped_fixed_summary,
            "counterfactual_skip": _counterfactual_skip_value(fixed_skipped, pnl_key="fixed_pnl_usd"),
            "baseline_robustness": _robustness(fixed_baseline, pnl_key="fixed_pnl_usd", notional=notional),
            "primary_robustness": _robustness(fixed_primary, pnl_key="fixed_pnl_usd", notional=notional),
            "primary_minus_baseline": {
                "roi_on_deployed_capital_pct_points": _metric_delta(
                    primary_fixed_summary, baseline_fixed_summary, "roi_on_deployed_capital_pct"
                ),
                "mean_return_pct_points": _metric_delta(
                    primary_fixed_summary, baseline_fixed_summary, "mean_return_pct"
                ),
                "median_return_pct_points": _metric_delta(
                    primary_fixed_summary, baseline_fixed_summary, "median_return_pct"
                ),
                "positive_trade_share_pct_points": _metric_delta(
                    primary_fixed_summary, baseline_fixed_summary, "positive_trade_share_pct"
                ),
            },
        },
        "smart_ladder_25_exploratory": smart_section,
        "primary_selector_diagnostics": {
            "status_counts": dict(sorted(Counter(str(row.get("status") or "") for row in primary_rows).items())),
            "reason_counts": _reason_counts(primary_rows),
            "rows": primary_rows,
        },
        "diagnostic_selector_diagnostics": {
            "status_counts": dict(sorted(Counter(str(row.get("status") or "") for row in diagnostic_rows).items())),
            "reason_counts": _reason_counts(diagnostic_rows),
        },
        "screening": {
            "status": _screening_status(usable_count=primary_usable, policy=policy),
            "primary_usable_route_results": primary_usable,
            "evaluation_gates": policy.get("evaluation_gates"),
            "automatic_profitability_claim": False,
            "threshold_retuning_permitted_from_this_run": False,
        },
        "guardrails": {
            "frozen_baseline_routes_reused": True,
            "primary_sniper_is_postprocessed_strict_subset": True,
            "no_extra_provider_calls_for_rejected_sniper_candidates": True,
            "missing_features_not_imputed": True,
            "fixed_60s_remains_primary": True,
            "smart_ladder_remains_exploratory": True,
            "official_v4_economic_verdict_changed": False,
            "landed_fill_claim": False,
            "realized_pnl_claim": False,
        },
        "interpretation": (
            "Prospective route-shadow comparison of the frozen Launch Burst baseline against a preregistered "
            "high-precision subset using only the feature snapshot frozen before provider quotes. Fixed +60s "
            "remains the primary benchmark. SMART-LADDER-25 remains exploratory. PASS means accounting and "
            "comparison completed; it does not mean profitable edge was established."
        ),
    }
    _write_json(output_path, result)
    return result
