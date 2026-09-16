from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from benchmarks.launch_burst_control_taker_sim_v0.smart_exit import (
    _aggregate,
    _canonical_json,
    _fixed_rows,
    _net_multiplier,
    _read_json,
    _route_quality_ok,
    _write_json,
)

SMART_RESULT_TYPE = "launch_burst_control_taker_smart_ladder_25_result_v0"
EXPECTED_POLICY_SCHEMA = "launch_burst_smart_ladder_25_policy_v0"


def _validate_policy(policy: Mapping[str, Any], *, route_contract_hash: str) -> None:
    if policy.get("schema_version") != EXPECTED_POLICY_SCHEMA:
        raise ValueError("unsupported SMART-LADDER-25 policy schema")
    if policy.get("status") != "PREREGISTERED_EXPLORATORY":
        raise ValueError("SMART-LADDER-25 policy is not preregistered")
    if policy.get("route_contract_hash_sha256") != route_contract_hash:
        raise ValueError("SMART-LADDER-25 route contract hash mismatch")
    expected = str(policy.get("policy_hash_sha256") or "")
    shadow = {k: v for k, v in dict(policy).items() if k != "policy_hash_sha256"}
    actual = hashlib.sha256(_canonical_json(shadow).encode("utf-8")).hexdigest()
    if expected != actual:
        raise ValueError("SMART-LADDER-25 policy hash mismatch")

    offsets = policy.get("sample_offsets_seconds_from_entry")
    if not isinstance(offsets, list) or offsets != [5, 10, 20, 30, 45, 60]:
        raise ValueError("SMART-LADDER-25 observation grid must be [5,10,20,30,45,60]")

    scale_out = policy.get("scale_out")
    expected_thresholds = [(20.0, 0.25), (50.0, 0.25), (100.0, 0.25)]
    if not isinstance(scale_out, list) or len(scale_out) != 3:
        raise ValueError("SMART-LADDER-25 requires exactly three scale-outs")
    actual_thresholds = [
        (float(x["threshold_return_pct"]), float(x["sell_fraction_of_initial_position"]))
        for x in scale_out
    ]
    if actual_thresholds != expected_thresholds:
        raise ValueError("SMART-LADDER-25 thresholds/fractions differ from frozen contract")

    runner = policy.get("runner") or {}
    if runner.get("mode") != "fixed_horizon_close":
        raise ValueError("SMART-LADDER-25 runner must use fixed_horizon_close")
    if int(runner.get("horizon_seconds_from_entry") or 0) != 60:
        raise ValueError("SMART-LADDER-25 final runner horizon must be +60s")
    if not math.isclose(float(runner.get("fraction_of_initial_position") or 0.0), 0.25, abs_tol=1e-12):
        raise ValueError("SMART-LADDER-25 runner fraction must be 25%")
    if policy.get("stop_loss") is not None:
        raise ValueError("SMART-LADDER-25 V0 has no stop loss")
    if "trailing_drawdown_fraction_from_best_net_multiplier" in runner:
        raise ValueError("SMART-LADDER-25 V0 has no trailing stop")


def _smart_trade(
    *,
    path_episode: Mapping[str, Any],
    fixed_decision: Mapping[str, Any],
    contract: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    notional = float(contract["position"]["notional_usd"])
    entry = fixed_decision.get("entry_quote")
    status = str(fixed_decision.get("status") or "")
    base = {
        "episode_key": str(path_episode.get("episode_key") or ""),
        "token_mint": str(path_episode.get("token_mint") or ""),
        "decision_as_of": fixed_decision.get("decision_as_of"),
        "fixed_status": status,
        "smart_status": "ENTRY_NOT_USABLE",
        "smart_pnl_usd": None,
        "smart_return_pct": None,
        "realizations": [],
        "threshold_hits": [],
        "runner_exit": None,
    }
    if entry is None or (status != "ROUTE_CLOSED" and not status.startswith("UNROUTABLE_EXIT")):
        return base

    observations: list[dict[str, Any]] = []
    for mark in path_episode.get("path") or []:
        quote = mark.get("quote")
        if not isinstance(quote, dict) or quote.get("executable") is not False or not _route_quality_ok(quote, contract):
            continue
        try:
            mult = _net_multiplier(entry, quote, contract)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
        observations.append(
            {
                "offset_seconds": int(mark["offset_seconds"]),
                "observed_at": int(quote["observed_at"]),
                "multiplier": mult,
                "net_return_pct": 100.0 * (mult - 1.0),
            }
        )
    observations.sort(key=lambda x: (x["offset_seconds"], x["observed_at"]))

    remaining = 1.0
    realized_multiplier = 0.0
    realizations: list[dict[str, Any]] = []
    hits: list[dict[str, Any]] = []
    thresholds = list(policy["scale_out"])
    threshold_index = 0

    # Gap crossing rule: if one observed executable mark jumps across multiple
    # thresholds, each crossed tranche is filled at that first observed mark.
    for obs in observations:
        if obs["offset_seconds"] > 60:
            break
        while threshold_index < len(thresholds):
            target = thresholds[threshold_index]
            threshold_mult = 1.0 + float(target["threshold_return_pct"]) / 100.0
            if obs["multiplier"] < threshold_mult:
                break
            fraction = float(target["sell_fraction_of_initial_position"])
            remaining -= fraction
            realized_multiplier += fraction * obs["multiplier"]
            hit = {
                "threshold_return_pct": float(target["threshold_return_pct"]),
                "fraction_of_initial_position": fraction,
                "offset_seconds": obs["offset_seconds"],
                "net_return_pct_at_observation": obs["net_return_pct"],
            }
            hits.append(hit)
            realizations.append({"reason": "SCALE_OUT", **hit})
            threshold_index += 1

    horizon = 60
    final = [x for x in observations if x["offset_seconds"] == horizon]
    if remaining > 1e-12:
        if final:
            obs = final[-1]
            realized_multiplier += remaining * obs["multiplier"]
            runner_exit = {
                "reason": "FIXED_60S_CLOSE",
                "fraction_of_initial_position": remaining,
                "offset_seconds": horizon,
                "net_return_pct_at_observation": obs["net_return_pct"],
            }
        else:
            loss_pct = float(contract["failure_policy"]["unexitable_return_pct"])
            realized_multiplier += remaining * (1.0 + loss_pct / 100.0)
            runner_exit = {
                "reason": "FIXED_60S_UNROUTABLE",
                "fraction_of_initial_position": remaining,
                "offset_seconds": horizon,
                "applied_return_pct": loss_pct,
            }
        realizations.append(dict(runner_exit))
        remaining = 0.0
    else:
        runner_exit = {
            "reason": "FULLY_SCALED_OUT_BEFORE_60S",
            "fraction_of_initial_position": 0.0,
            "offset_seconds": None,
        }

    ret = 100.0 * (realized_multiplier - 1.0)
    base.update(
        {
            "smart_status": "CLOSED",
            "smart_pnl_usd": notional * ret / 100.0,
            "smart_return_pct": ret,
            "realizations": realizations,
            "threshold_hits": hits,
            "runner_exit": runner_exit,
            "valid_path_observation_count": len(observations),
        }
    )
    return base


def run_smart_ladder_25(
    *,
    contract_path: Path,
    policy_path: Path,
    route_result_path: Path,
    market_paths_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    contract, policy = _read_json(contract_path), _read_json(policy_path)
    route_result, paths = _read_json(route_result_path), _read_json(market_paths_path)
    route_hash = str(contract.get("contract_hash_sha256") or "")
    _validate_policy(policy, route_contract_hash=route_hash)
    if route_result.get("contract_hash_sha256") != route_hash or paths.get("route_contract_hash_sha256") != route_hash:
        raise ValueError("route contract hash mismatch in simulation artifacts")
    if paths.get("smart_exit_policy_hash_sha256") != policy["policy_hash_sha256"]:
        raise ValueError("SMART-LADDER-25 policy hash mismatch in market paths")

    decisions = {str(x.get("episode_key") or ""): x for x in route_result.get("decisions") or []}
    rows: list[dict[str, Any]] = []
    for path_episode in paths.get("episodes") or []:
        fixed = decisions.get(str(path_episode.get("episode_key") or ""))
        if fixed is None:
            continue
        row = _smart_trade(path_episode=path_episode, fixed_decision=fixed, contract=contract, policy=policy)
        if row["smart_pnl_usd"] is not None:
            rows.append(row)
    rows.sort(key=lambda r: (int(r.get("decision_as_of") or 0), r["token_mint"]))

    notional = float(contract["position"]["notional_usd"])
    fixed_all = _fixed_rows(route_result, notional)
    fixed_by_key = {x["episode_key"]: x for x in fixed_all}
    paired = [x for x in rows if x["episode_key"] in fixed_by_key]
    fixed_paired = [fixed_by_key[x["episode_key"]] for x in paired]
    smart_summary = _aggregate(paired, "smart_pnl_usd", notional)
    fixed_summary = _aggregate(fixed_paired, "fixed_pnl_usd", notional)

    threshold_counts: Counter[str] = Counter()
    runner_counts: Counter[str] = Counter()
    fixed_wins = 0
    smart_wins = 0
    fixed_profit_given_up_usd = 0.0
    smart_drawdown_improvement_rows = 0
    for row in paired:
        for hit in row["threshold_hits"]:
            threshold_counts[str(hit["threshold_return_pct"])] += 1
        reason = (row.get("runner_exit") or {}).get("reason")
        if reason:
            runner_counts[str(reason)] += 1
        fixed = fixed_by_key[row["episode_key"]]
        fixed_pnl = float(fixed["fixed_pnl_usd"])
        smart_pnl = float(row["smart_pnl_usd"])
        if fixed_pnl > smart_pnl:
            fixed_wins += 1
            fixed_profit_given_up_usd += fixed_pnl - smart_pnl
        elif smart_pnl > fixed_pnl:
            smart_wins += 1
            if smart_pnl < 0 and smart_pnl > fixed_pnl:
                smart_drawdown_improvement_rows += 1

    result = {
        "type": SMART_RESULT_TYPE,
        "classification": "PASS_LAUNCH_BURST_CONTROL_TAKER_SMART_LADDER_25_SIM_V0",
        "route_contract_hash_sha256": route_hash,
        "smart_exit_policy_hash_sha256": policy["policy_hash_sha256"],
        "primary_benchmark": "FIXED_60S_ROUTE_PAPER",
        "exploratory_comparison": "SMART_LADDER_25_V0",
        "paired_trade_count": len(paired),
        "fixed_60s": fixed_summary,
        "smart_ladder_25": smart_summary,
        "smart_minus_fixed_total_pnl_usd": smart_summary["total_pnl_usd"] - fixed_summary["total_pnl_usd"] if paired else None,
        "threshold_hit_counts": dict(threshold_counts),
        "runner_exit_reason_counts": dict(runner_counts),
        "fixed_trade_win_count": fixed_wins,
        "smart_trade_win_count": smart_wins,
        "profit_given_up_vs_fixed_when_fixed_wins_usd": fixed_profit_given_up_usd,
        "smart_loss_reduction_trade_count": smart_drawdown_improvement_rows,
        "trades": paired,
        "guardrails": {
            "changes_launch_burst_selector": False,
            "changes_frozen_route_contract": False,
            "smart_exit_is_exploratory": True,
            "fixed_60s_is_primary_simulation_benchmark": True,
            "landed_fill_claim": False,
            "realized_pnl_claim": False,
            "continuous_first_touch_claim": False,
            "trailing_stop_used": False,
            "final_runner_exit_seconds": 60,
        },
        "interpretation": "Fixed +60s versus preregistered SMART-LADDER-25 V0 route-shadow evidence. Threshold fills occur only at the first observed executable sample at or above each threshold. Remaining quantity closes at +60s; no trailing stop is used. These are not landed fills or realized PnL.",
    }
    _write_json(output_path, result)
    return result
