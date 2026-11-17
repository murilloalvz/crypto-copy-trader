from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

SMART_RESULT_TYPE = "launch_burst_control_taker_smart_exit_result_v0"
EXPECTED_POLICY_SCHEMA = "launch_burst_smart_exit_policy_v0"


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


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_policy(policy: Mapping[str, Any], *, route_contract_hash: str) -> None:
    if policy.get("schema_version") != EXPECTED_POLICY_SCHEMA:
        raise ValueError("unsupported smart-exit policy schema")
    if policy.get("status") != "PREREGISTERED_EXPLORATORY":
        raise ValueError("smart-exit policy is not preregistered")
    if policy.get("route_contract_hash_sha256") != route_contract_hash:
        raise ValueError("smart-exit policy route contract hash mismatch")
    expected = str(policy.get("policy_hash_sha256") or "")
    shadow = {k: v for k, v in dict(policy).items() if k != "policy_hash_sha256"}
    actual = hashlib.sha256(_canonical_json(shadow).encode("utf-8")).hexdigest()
    if expected != actual:
        raise ValueError("smart-exit policy hash mismatch")
    offsets = policy.get("sample_offsets_seconds_from_entry")
    if not isinstance(offsets, list) or not offsets or offsets != sorted(set(offsets)):
        raise ValueError("sample offsets must be a sorted unique list")
    scale_out = policy.get("scale_out")
    if not isinstance(scale_out, list) or len(scale_out) != 3:
        raise ValueError("smart-exit v0 requires exactly three scale-outs")
    total = sum(float(x["sell_fraction_of_initial_position"]) for x in scale_out)
    runner = float(policy["runner"]["fraction_of_initial_position"])
    if not math.isclose(total + runner, 1.0, abs_tol=1e-12):
        raise ValueError("scale-outs plus runner must equal 1.0")


def _route_quality_ok(quote: Mapping[str, Any], contract: Mapping[str, Any]) -> bool:
    impact = quote.get("provider_price_impact_pct_points")
    if impact is None:
        return False
    try:
        value = float(impact)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and 0 <= value <= float(
        contract["route_quality"]["max_provider_price_impact_pct_points"]
    )


def _net_multiplier(entry: Mapping[str, Any], exit_quote: Mapping[str, Any], contract: Mapping[str, Any]) -> float:
    costs = contract["costs"]
    entry_drag = (float(costs["entry_fee_bps"]) + float(costs["entry_adverse_slippage_bps"])) / 10_000.0
    exit_drag = (float(costs["exit_fee_bps"]) + float(costs["exit_adverse_slippage_bps"])) / 10_000.0
    return (float(exit_quote["price_usd"]) * (1.0 - exit_drag)) / (float(entry["price_usd"]) * (1.0 + entry_drag))


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * fraction
    lo, hi = int(pos), min(int(pos) + 1, len(xs) - 1)
    w = pos - lo
    return xs[lo] * (1 - w) + xs[hi] * w


def _max_drawdown(pnls: list[float]) -> float:
    equity = peak = max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _aggregate(rows: list[dict[str, Any]], pnl_key: str, notional: float) -> dict[str, Any]:
    pnls = [float(r[pnl_key]) for r in rows if r.get(pnl_key) is not None]
    returns = [100.0 * p / notional for p in pnls]
    profits, losses = [p for p in pnls if p > 0], [-p for p in pnls if p < 0]
    deployed = notional * len(pnls)
    return {
        "trade_count": len(pnls),
        "deployed_capital_usd": deployed,
        "total_pnl_usd": sum(pnls),
        "roi_on_deployed_capital_pct": 100.0 * sum(pnls) / deployed if deployed else None,
        "positive_trade_share_pct": 100.0 * sum(p > 0 for p in pnls) / len(pnls) if pnls else None,
        "mean_return_pct": sum(returns) / len(returns) if returns else None,
        "median_return_pct": _percentile(returns, 0.5),
        "p10_return_pct": _percentile(returns, 0.10),
        "p90_return_pct": _percentile(returns, 0.90),
        "best_return_pct": max(returns) if returns else None,
        "worst_return_pct": min(returns) if returns else None,
        "profit_factor": sum(profits) / sum(losses) if losses else (float("inf") if profits else None),
        "max_drawdown_usd_on_sequential_pnl_curve": _max_drawdown(pnls),
    }


def _fixed_rows(route_result: Mapping[str, Any], notional: float) -> list[dict[str, Any]]:
    rows = []
    for item in route_result.get("decisions") or []:
        status = str(item.get("status") or "")
        if not item.get("admitted") or (status != "ROUTE_CLOSED" and not status.startswith("UNROUTABLE_EXIT")):
            continue
        pnl = item.get("route_paper_pnl_usd")
        rows.append({
            "episode_key": str(item.get("episode_key") or ""),
            "token_mint": str(item.get("token_mint") or ""),
            "decision_as_of": item.get("decision_as_of"),
            "status": status,
            "fixed_pnl_usd": float(pnl) if pnl is not None else None,
            "fixed_return_pct": 100.0 * float(pnl) / notional if pnl is not None else None,
        })
    rows.sort(key=lambda r: (int(r.get("decision_as_of") or 0), r["token_mint"]))
    return rows


def _smart_trade(*, path_episode: Mapping[str, Any], fixed_decision: Mapping[str, Any], contract: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
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

    observations = []
    for mark in path_episode.get("path") or []:
        quote = mark.get("quote")
        if not isinstance(quote, dict) or quote.get("executable") is not False or not _route_quality_ok(quote, contract):
            continue
        try:
            mult = _net_multiplier(entry, quote, contract)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
        observations.append({
            "offset_seconds": int(mark["offset_seconds"]),
            "observed_at": int(quote["observed_at"]),
            "multiplier": mult,
            "net_return_pct": 100.0 * (mult - 1.0),
        })
    observations.sort(key=lambda x: (x["offset_seconds"], x["observed_at"]))

    remaining = 1.0
    realized = 0.0
    realizations, hits = [], []
    thresholds = list(policy["scale_out"])
    index = 0
    runner_active = False
    peak = None
    runner_exit = None

    for obs in observations:
        while index < len(thresholds):
            target = thresholds[index]
            threshold_mult = 1.0 + float(target["threshold_return_pct"]) / 100.0
            if obs["multiplier"] < threshold_mult:
                break
            fraction = float(target["sell_fraction_of_initial_position"])
            remaining -= fraction
            realized += fraction * obs["multiplier"]
            hit = {
                "threshold_return_pct": float(target["threshold_return_pct"]),
                "fraction_of_initial_position": fraction,
                "offset_seconds": obs["offset_seconds"],
                "net_return_pct_at_observation": obs["net_return_pct"],
            }
            hits.append(hit)
            realizations.append({"reason": "SCALE_OUT", **hit})
            index += 1
            if index == len(thresholds):
                runner_active, peak = True, obs["multiplier"]

        if runner_active and remaining > 1e-12:
            peak = max(float(peak), obs["multiplier"])
            trigger = peak * (1.0 - float(policy["runner"]["trailing_drawdown_fraction_from_best_net_multiplier"]))
            if obs["multiplier"] <= trigger:
                fraction = remaining
                remaining = 0.0
                realized += fraction * obs["multiplier"]
                runner_exit = {
                    "reason": "TRAILING_STOP",
                    "fraction_of_initial_position": fraction,
                    "offset_seconds": obs["offset_seconds"],
                    "net_return_pct_at_observation": obs["net_return_pct"],
                    "peak_net_return_pct": 100.0 * (peak - 1.0),
                }
                realizations.append(dict(runner_exit))
                break

    if remaining > 1e-12:
        horizon = int(policy["runner"]["max_horizon_seconds_from_entry"])
        final = [x for x in observations if x["offset_seconds"] == horizon]
        if final:
            obs = final[-1]
            realized += remaining * obs["multiplier"]
            runner_exit = {
                "reason": "MAX_HORIZON_CLOSE",
                "fraction_of_initial_position": remaining,
                "offset_seconds": horizon,
                "net_return_pct_at_observation": obs["net_return_pct"],
            }
        else:
            loss_pct = float(contract["failure_policy"]["unexitable_return_pct"])
            realized += remaining * (1.0 + loss_pct / 100.0)
            runner_exit = {
                "reason": "MAX_HORIZON_UNROUTABLE",
                "fraction_of_initial_position": remaining,
                "offset_seconds": horizon,
                "applied_return_pct": loss_pct,
            }
        realizations.append(dict(runner_exit))
        remaining = 0.0

    ret = 100.0 * (realized - 1.0)
    base.update({
        "smart_status": "CLOSED",
        "smart_pnl_usd": notional * ret / 100.0,
        "smart_return_pct": ret,
        "realizations": realizations,
        "threshold_hits": hits,
        "runner_exit": runner_exit,
        "valid_path_observation_count": len(observations),
    })
    return base


def run_smart_exit(*, contract_path: Path, policy_path: Path, route_result_path: Path, market_paths_path: Path, output_path: Path) -> dict[str, Any]:
    contract, policy = _read_json(contract_path), _read_json(policy_path)
    route_result, paths = _read_json(route_result_path), _read_json(market_paths_path)
    route_hash = str(contract.get("contract_hash_sha256") or "")
    _validate_policy(policy, route_contract_hash=route_hash)
    if route_result.get("contract_hash_sha256") != route_hash or paths.get("route_contract_hash_sha256") != route_hash:
        raise ValueError("route contract hash mismatch in simulation artifacts")
    if paths.get("smart_exit_policy_hash_sha256") != policy["policy_hash_sha256"]:
        raise ValueError("smart-exit policy hash mismatch in market paths")

    decisions = {str(x.get("episode_key") or ""): x for x in route_result.get("decisions") or []}
    rows = []
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
    threshold_counts, runner_counts = Counter(), Counter()
    for row in paired:
        for hit in row["threshold_hits"]:
            threshold_counts[str(hit["threshold_return_pct"])] += 1
        if (row.get("runner_exit") or {}).get("reason"):
            runner_counts[str(row["runner_exit"]["reason"])] += 1

    result = {
        "type": SMART_RESULT_TYPE,
        "classification": "PASS_LAUNCH_BURST_CONTROL_TAKER_SMART_EXIT_SIM_V0",
        "route_contract_hash_sha256": route_hash,
        "smart_exit_policy_hash_sha256": policy["policy_hash_sha256"],
        "primary_benchmark": "FIXED_60S_ROUTE_PAPER",
        "exploratory_comparison": "PREREGISTERED_SMART_EXIT_V0",
        "paired_trade_count": len(paired),
        "fixed_60s": fixed_summary,
        "smart_exit": smart_summary,
        "smart_minus_fixed_total_pnl_usd": smart_summary["total_pnl_usd"] - fixed_summary["total_pnl_usd"] if paired else None,
        "threshold_hit_counts": dict(threshold_counts),
        "runner_exit_reason_counts": dict(runner_counts),
        "trades": paired,
        "guardrails": {
            "changes_launch_burst_selector": False,
            "changes_frozen_route_contract": False,
            "smart_exit_is_exploratory": True,
            "fixed_60s_is_primary_simulation_benchmark": True,
            "landed_fill_claim": False,
            "realized_pnl_claim": False,
            "continuous_first_touch_claim": False,
        },
        "interpretation": "Fixed +60s versus a preregistered grid-observed smart-exit route-shadow simulation. These are not landed fills or realized PnL and do not unblock the frozen funded-taker V4 gate.",
    }
    _write_json(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch Burst smart-exit evaluator v0")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--route-result", type=Path, required=True)
    parser.add_argument("--market-paths", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_smart_exit(contract_path=args.contract, policy_path=args.policy, route_result_path=args.route_result, market_paths_path=args.market_paths, output_path=args.output)
    except Exception as exc:
        print(json.dumps({"classification": "FAIL_LAUNCH_BURST_CONTROL_TAKER_SMART_EXIT_SIM_V0", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
