from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from typing import Any, Mapping

from benchmarks.launch_burst_control_taker_sim_v0.smart_exit import (
    _aggregate,
    _fixed_rows,
    _net_multiplier,
    _route_quality_ok,
)
from benchmarks.launch_burst_sniper_v1.strict_compare import validate_sniper_source_integrity_v1
from src.launch_burst_momentum_v0 import (
    evaluate_momentum_v0,
    load_momentum_policy_v0,
    momentum_decision_to_dict_v0,
)
from src.launch_burst_sniper_v1 import evaluate_launch_burst_sniper_v1, load_sniper_policy_v1


VERSION = "launch_burst_momentum_comparison_v0"
PASS = "PASS_LAUNCH_BURST_MOMENTUM_COMPARISON_V0"


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


def _indexed_rows(rows: object, *, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError(f"{label} must be a list")
    indexed: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{label}[{index}] must be an object")
        key = str(row.get("episode_key") or "").strip()
        if not key:
            raise ValueError(f"{label}[{index}] has no episode_key")
        if key in indexed:
            raise ValueError(f"duplicate episode_key in {label}: {key}")
        indexed[key] = row
    return indexed


def _selector_rows(episodes: list[dict[str, Any]], policy: Mapping[str, Any], selector_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for episode in episodes:
        snapshot = episode.get("feature_snapshot")
        if not isinstance(snapshot, Mapping):
            continue
        decision = evaluate_momentum_v0(snapshot=snapshot, policy=policy, selector_name=selector_name)
        row = momentum_decision_to_dict_v0(decision)
        row["episode_key"] = str(episode.get("episode_key") or "")
        row["token_mint"] = str(episode.get("token_mint") or "")
        rows.append(row)
    return rows


def _selected(rows: list[dict[str, Any]]) -> set[str]:
    return {str(row["episode_key"]) for row in rows if row.get("selected") is True}


def _counterfactual(rows: list[dict[str, Any]], pnl_key: str) -> dict[str, Any]:
    pnls = [float(row[pnl_key]) for row in rows if row.get(pnl_key) is not None]
    total = sum(pnls)
    return {
        "skipped_trade_count": len(pnls),
        "skipped_trade_pnl_usd": total,
        "counterfactual_value_of_skipping_usd": -total,
        "avoided_negative_trade_count": sum(x < 0 for x in pnls),
        "missed_positive_trade_count": sum(x > 0 for x in pnls),
        "avoided_loss_magnitude_usd": sum(-x for x in pnls if x < 0),
        "missed_profit_usd": sum(x for x in pnls if x > 0),
    }


def _reason_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        for reason in row.get("reasons") or []:
            counts[str(reason)] += 1
    return dict(sorted(counts.items()))


def _validate_market_paths_integrity(
    *,
    market_paths: dict[str, Any],
    baseline_keys: set[str],
    input_by_key: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    path_by_key = _indexed_rows(market_paths.get("episodes"), label="market_paths.episodes")
    path_keys = set(path_by_key)
    if path_keys != baseline_keys:
        missing = sorted(baseline_keys - path_keys)
        extra = sorted(path_keys - baseline_keys)
        raise ValueError(
            "market paths do not exactly match frozen admitted baseline: "
            f"missing={missing[:5]} extra={extra[:5]}"
        )
    token_mismatches: list[str] = []
    for key in sorted(path_keys):
        expected = str((input_by_key.get(key) or {}).get("token_mint") or "").strip()
        observed = str(path_by_key[key].get("token_mint") or "").strip()
        if not expected or observed != expected:
            token_mismatches.append(key)
    if token_mismatches:
        raise ValueError(
            "market path token mint mismatch for episode keys: "
            + ",".join(token_mismatches[:5])
        )
    return {
        "market_path_episode_count": len(path_by_key),
        "market_path_exact_baseline_key_parity": True,
        "market_path_exact_token_mint_parity": True,
        "market_path_unique_episode_keys": True,
    }


def _horizon_300_rows(
    *, route_result: dict[str, Any], market_paths: dict[str, Any], contract: dict[str, Any]
) -> list[dict[str, Any]]:
    notional = float(contract["position"]["notional_usd"])
    failure_return = float(contract["failure_policy"]["unexitable_return_pct"])
    path_by_key = _indexed_rows(market_paths.get("episodes"), label="market_paths.episodes")
    rows: list[dict[str, Any]] = []
    for decision in route_result.get("decisions") or []:
        key = str(decision.get("episode_key") or "")
        status = str(decision.get("status") or "")
        entry = decision.get("entry_quote")
        if not isinstance(entry, dict) or (status != "ROUTE_CLOSED" and not status.startswith("UNROUTABLE_EXIT")):
            continue
        episode = path_by_key.get(key)
        if episode is None:
            raise ValueError(f"economically usable episode missing market path: {key}")
        marks = [m for m in episode.get("path") or [] if int(m.get("offset_seconds") or 0) == 300]
        if len(marks) != 1:
            raise ValueError(
                f"economically usable episode must contain exactly one explicit 300s observation: {key} count={len(marks)}"
            )
        mark = marks[0]
        quote = mark.get("quote")
        ret = failure_return
        route_status = str(mark.get("status") or "UNKNOWN_300S_STATUS")
        if isinstance(quote, dict) and quote.get("executable") is False and _route_quality_ok(quote, contract):
            try:
                ret = 100.0 * (_net_multiplier(entry, quote, contract) - 1.0)
                route_status = "ROUTE_300S_AVAILABLE"
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                ret = failure_return
                route_status = "INVALID_300S_ROUTE"
        elif route_status == "AVAILABLE_ROUTE_ONLY":
            route_status = "INVALID_300S_ROUTE"
        rows.append({
            "episode_key": key,
            "token_mint": str(decision.get("token_mint") or ""),
            "decision_as_of": decision.get("decision_as_of"),
            "pnl_300_usd": notional * ret / 100.0,
            "return_300_pct": ret,
            "status_300": route_status,
        })
    rows.sort(key=lambda x: (int(x.get("decision_as_of") or 0), x["token_mint"]))
    return rows


def run_momentum_comparison_v0(
    *, contract_path: Path, momentum_policy_path: Path, sniper_v1_policy_path: Path,
    route_input_path: Path, route_result_path: Path, market_paths_path: Path,
    smart_result_path: Path | None, output_path: Path,
) -> dict[str, Any]:
    integrity = validate_sniper_source_integrity_v1(
        route_input_path=route_input_path,
        route_result_path=route_result_path,
        smart_result_path=smart_result_path,
    )
    contract = _read_json(contract_path)
    policy = load_momentum_policy_v0(momentum_policy_path)
    sniper_policy = load_sniper_policy_v1(sniper_v1_policy_path)
    route_input = _read_json(route_input_path)
    route_result = _read_json(route_result_path)
    market_paths = _read_json(market_paths_path)
    route_hash = str(contract.get("contract_hash_sha256") or "")
    if route_hash != policy.get("route_contract_hash_sha256"):
        raise ValueError("momentum/route contract hash mismatch")
    if market_paths.get("route_contract_hash_sha256") != route_hash:
        raise ValueError("market paths route contract hash mismatch")

    episodes = list(route_input.get("episodes") or [])
    decisions = list(route_result.get("decisions") or [])
    input_by_key = _indexed_rows(episodes, label="route_input.episodes")
    baseline_keys = {str(row.get("episode_key") or "") for row in decisions if row.get("admitted") is True}
    market_integrity = _validate_market_paths_integrity(
        market_paths=market_paths,
        baseline_keys=baseline_keys,
        input_by_key=input_by_key,
    )
    integrity = {**integrity, **market_integrity}

    primary_rows = _selector_rows(episodes, policy, "primary_selector")
    event_rows = _selector_rows(episodes, policy, "event_acceleration_2x")
    buy_rows = _selector_rows(episodes, policy, "buy_flow_acceleration_2x")
    primary_all = _selected(primary_rows)
    if primary_all - baseline_keys:
        raise ValueError("momentum primary selector escaped frozen Burst baseline")
    primary_keys = primary_all & baseline_keys
    event_keys = _selected(event_rows) & baseline_keys
    buy_keys = _selected(buy_rows) & baseline_keys

    sniper_keys: set[str] = set()
    for episode in episodes:
        snapshot = episode.get("feature_snapshot")
        if not isinstance(snapshot, Mapping):
            continue
        decision = evaluate_launch_burst_sniper_v1(snapshot=snapshot, policy=sniper_policy, selector_name="primary_selector")
        if decision.selected:
            sniper_keys.add(str(episode.get("episode_key") or ""))
    sniper_keys &= baseline_keys
    convergence_keys = primary_keys & sniper_keys

    notional = float(contract["position"]["notional_usd"])
    fixed_all = _fixed_rows(route_result, notional)
    fixed_baseline = [row for row in fixed_all if row["episode_key"] in baseline_keys]
    fixed_primary = [row for row in fixed_all if row["episode_key"] in primary_keys]
    fixed_skipped = [row for row in fixed_baseline if row["episode_key"] not in primary_keys]
    fixed_sniper = [row for row in fixed_all if row["episode_key"] in sniper_keys]
    fixed_convergence = [row for row in fixed_all if row["episode_key"] in convergence_keys]

    horizon_rows = _horizon_300_rows(route_result=route_result, market_paths=market_paths, contract=contract)
    h300_baseline = [row for row in horizon_rows if row["episode_key"] in baseline_keys]
    h300_primary = [row for row in horizon_rows if row["episode_key"] in primary_keys]
    h300_skipped = [row for row in h300_baseline if row["episode_key"] not in primary_keys]

    primary_usable = len(fixed_primary)
    gates = policy.get("evaluation_gates") or {}
    min_directional = int(gates.get("minimum_primary_usable_route_results_for_directional_read") or 0)
    min_replication = int(gates.get("minimum_primary_usable_route_results_before_replication") or 0)
    if primary_usable < min_directional:
        screening_status = "INSUFFICIENT_PRIMARY_SAMPLE"
    elif primary_usable < min_replication:
        screening_status = "DIRECTIONAL_READ_AVAILABLE_REPLICATION_NOT_ARMED"
    else:
        screening_status = "REPLICATION_SAMPLE_SIZE_ELIGIBLE_FRESH_RUN_STILL_REQUIRED"

    result = {
        "type": "launch_burst_momentum_comparison",
        "version": VERSION,
        "classification": PASS,
        "route_contract_hash_sha256": route_hash,
        "momentum_policy_hash_sha256": policy["policy_hash_sha256"],
        "source_integrity": integrity,
        "selection": {
            "baseline_selected_count": len(baseline_keys),
            "momentum_primary_selected_count": len(primary_keys),
            "momentum_selection_rate_pct_of_baseline": 100.0 * len(primary_keys) / len(baseline_keys) if baseline_keys else None,
            "sniper_v1_selected_count": len(sniper_keys),
            "momentum_and_sniper_v1_convergence_count": len(convergence_keys),
            "event_acceleration_diagnostic_count": len(event_keys),
            "buy_flow_acceleration_diagnostic_count": len(buy_keys),
        },
        "fixed_60s_primary_benchmark": {
            "baseline": _aggregate(fixed_baseline, "fixed_pnl_usd", notional),
            "momentum_primary": _aggregate(fixed_primary, "fixed_pnl_usd", notional),
            "sniper_v1_diagnostic": _aggregate(fixed_sniper, "fixed_pnl_usd", notional),
            "momentum_and_sniper_v1_convergence_diagnostic": _aggregate(fixed_convergence, "fixed_pnl_usd", notional),
            "skipped_by_momentum": _aggregate(fixed_skipped, "fixed_pnl_usd", notional),
            "counterfactual_skip": _counterfactual(fixed_skipped, "fixed_pnl_usd"),
        },
        "historical_alignment_300s_exploratory": {
            "inference_role": "EXPLORATORY_TRANSFER_VALIDATION_ONLY",
            "baseline": _aggregate(h300_baseline, "pnl_300_usd", notional),
            "momentum_primary": _aggregate(h300_primary, "pnl_300_usd", notional),
            "skipped_by_momentum": _aggregate(h300_skipped, "pnl_300_usd", notional),
            "counterfactual_skip": _counterfactual(h300_skipped, "pnl_300_usd"),
            "route_status_counts": dict(sorted(Counter(row["status_300"] for row in h300_baseline).items())),
        },
        "primary_selector_diagnostics": {
            "reason_counts": _reason_counts(primary_rows),
            "rows": primary_rows,
        },
        "diagnostic_selector_counts": {
            "event_acceleration_2x": len(event_keys),
            "buy_flow_acceleration_2x": len(buy_keys),
        },
        "screening": {
            "status": screening_status,
            "primary_usable_route_results": primary_usable,
            "evaluation_gates": gates,
            "threshold_retuning_permitted_from_this_run": False,
            "automatic_profitability_claim": False,
        },
        "guardrails": {
            "historical_wave_metric_exactly_reused": False,
            "historical_wave_acceleration_concept_transferred": True,
            "historical_2x_threshold_preregistered_before_fresh_outcomes": True,
            "sniper_v1_is_diagnostic_not_primary": True,
            "fixed_60s_remains_primary": True,
            "300s_is_exploratory_historical_alignment": True,
            "300s_missing_collector_evidence_is_integrity_error_not_economic_loss": True,
            "landed_fill_claim": False,
            "realized_pnl_claim": False,
            "official_v4_economic_verdict_changed": False,
        },
    }
    _write_json(output_path, result)
    return result
