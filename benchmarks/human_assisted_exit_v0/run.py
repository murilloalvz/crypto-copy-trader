from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping


VERSION = "causal_human_exit_v0"
PASS = "PASS_CAUSAL_HUMAN_EXIT_RETROSPECTIVE_DIAGNOSTIC_V0"
EXPECTED_POLICY_SCHEMA = "causal_human_exit_policy_v0"
DEFAULT_POLICY = (
    Path("benchmarks")
    / "human_assisted_exit_v0"
    / "causal_human_exit_policy_v0.frozen.json"
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _validate_policy(
    policy: Mapping[str, Any],
    *,
    route_contract_hash: str,
) -> None:
    if policy.get("schema_version") != EXPECTED_POLICY_SCHEMA:
        raise ValueError("unsupported causal human exit policy schema")
    if policy.get("status") != "FROZEN_RETROSPECTIVE_DIAGNOSTIC":
        raise ValueError("causal human exit policy is not frozen")
    if policy.get("route_contract_hash_sha256") != route_contract_hash:
        raise ValueError("causal human exit route contract hash mismatch")

    expected = str(policy.get("policy_hash_sha256") or "")
    shadow = {
        key: value
        for key, value in dict(policy).items()
        if key != "policy_hash_sha256"
    }
    actual = hashlib.sha256(
        _canonical_json(shadow).encode("utf-8")
    ).hexdigest()
    if expected != actual:
        raise ValueError("causal human exit policy hash mismatch")

    if policy.get("exit_order") != [
        "GOOD_PROFIT",
        "STRONG_DECELERATION",
        "RISK_BREAK",
    ]:
        raise ValueError("unexpected exit priority")

    if policy.get("censoring", {}).get("forced_time_exit") is not False:
        raise ValueError("V0 forbids a forced time exit")

    guardrails = policy.get("guardrails") or {}
    required_false = (
        "thresholds_selected_from_historical_pnl",
        "same_sample_retuning_allowed",
        "retrospective_result_can_confirm_edge",
    )
    if any(guardrails.get(name) is not False for name in required_false):
        raise ValueError("retrospective scientific guardrail mismatch")
    if guardrails.get("fixed_60_remains_standardized_benchmark") is not True:
        raise ValueError("fixed +60 benchmark must remain preserved")
    if guardrails.get("mfe_is_not_simulated_exit") is not True:
        raise ValueError("MFE cannot be treated as a simulated exit")


def _route_quality_ok(
    quote: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> bool:
    impact = quote.get("provider_price_impact_pct_points")
    if impact is None:
        return False
    try:
        value = float(impact)
    except (TypeError, ValueError):
        return False
    return math.isfinite(value) and value <= float(
        contract["route_quality"]["max_provider_price_impact_pct_points"]
    )


def _net_multiplier(
    entry: Mapping[str, Any],
    exit_quote: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> float:
    costs = contract["costs"]
    entry_drag = (
        float(costs["entry_fee_bps"])
        + float(costs["entry_adverse_slippage_bps"])
    ) / 10_000.0
    exit_drag = (
        float(costs["exit_fee_bps"])
        + float(costs["exit_adverse_slippage_bps"])
    ) / 10_000.0
    return (
        float(exit_quote["price_usd"]) * (1.0 - exit_drag)
    ) / (
        float(entry["price_usd"]) * (1.0 + entry_drag)
    )


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return (
        ordered[lower] * (1.0 - weight)
        + ordered[upper] * weight
    )


def _profit_factor(returns: list[float]) -> float | None:
    profits = sum(value for value in returns if value > 0)
    losses = -sum(value for value in returns if value < 0)
    if losses > 0:
        return profits / losses
    return float("inf") if profits > 0 else None


def _aggregate_returns(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "mean_return_pct": None,
            "median_return_pct": None,
            "positive_share_pct": None,
            "profit_factor": None,
            "p10_return_pct": None,
            "p90_return_pct": None,
            "best_return_pct": None,
            "worst_return_pct": None,
            "mean_without_best_return_pct": None,
        }
    best = max(values)
    without_best = list(values)
    without_best.remove(best)
    return {
        "n": len(values),
        "mean_return_pct": sum(values) / len(values),
        "median_return_pct": median(values),
        "positive_share_pct": (
            100.0 * sum(value > 0 for value in values) / len(values)
        ),
        "profit_factor": _profit_factor(values),
        "p10_return_pct": _percentile(values, 0.10),
        "p90_return_pct": _percentile(values, 0.90),
        "best_return_pct": best,
        "worst_return_pct": min(values),
        "mean_without_best_return_pct": (
            sum(without_best) / len(without_best)
            if without_best
            else None
        ),
    }


def _fixed_rows(
    route_result: Mapping[str, Any],
    *,
    notional: float,
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for item in route_result.get("decisions") or []:
        key = str(item.get("episode_key") or "")
        status = str(item.get("status") or "")
        pnl = item.get("route_paper_pnl_usd")
        if (
            not key
            or not item.get("admitted")
            or pnl is None
            or (
                status != "ROUTE_CLOSED"
                and not status.startswith("UNROUTABLE_EXIT")
            )
        ):
            continue
        rows[key] = {
            "episode_key": key,
            "token_mint": str(item.get("token_mint") or ""),
            "decision_as_of": item.get("decision_as_of"),
            "fixed_status": status,
            "fixed_return_pct": 100.0 * float(pnl) / notional,
            "entry_quote": item.get("entry_quote"),
        }
    return rows


def _path_observations(
    *,
    path_episode: Mapping[str, Any],
    fixed_decision: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    entry = fixed_decision.get("entry_quote")
    if not isinstance(entry, Mapping):
        return []

    observations: list[dict[str, Any]] = []
    for mark in path_episode.get("path") or []:
        quote = mark.get("quote")
        if not isinstance(quote, Mapping):
            continue
        if quote.get("executable") is not False:
            continue
        if not _route_quality_ok(quote, contract):
            continue
        try:
            multiplier = _net_multiplier(entry, quote, contract)
            offset = int(mark["offset_seconds"])
            observed_at = int(quote["observed_at"])
        except (
            KeyError,
            TypeError,
            ValueError,
            ZeroDivisionError,
        ):
            continue
        if offset < 0 or not math.isfinite(multiplier):
            continue
        observations.append(
            {
                "offset_seconds": offset,
                "observed_at": observed_at,
                "net_return_pct": 100.0 * (multiplier - 1.0),
            }
        )

    observations.sort(
        key=lambda row: (
            row["offset_seconds"],
            row["observed_at"],
        )
    )
    return observations


def _path_metrics(
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    if not observations:
        return {
            "valid_route_observation_count": 0,
            "observed_mfe_pct": None,
            "observed_mae_pct": None,
            "time_to_observed_mfe_seconds": None,
            "time_to_observed_mae_seconds": None,
            "last_observed_return_pct": None,
            "last_observed_offset_seconds": None,
        }

    mfe = max(observations, key=lambda row: row["net_return_pct"])
    mae = min(observations, key=lambda row: row["net_return_pct"])
    last = observations[-1]
    return {
        "valid_route_observation_count": len(observations),
        "observed_mfe_pct": mfe["net_return_pct"],
        "observed_mae_pct": mae["net_return_pct"],
        "time_to_observed_mfe_seconds": mfe["offset_seconds"],
        "time_to_observed_mae_seconds": mae["offset_seconds"],
        "last_observed_return_pct": last["net_return_pct"],
        "last_observed_offset_seconds": last["offset_seconds"],
    }


def _trigger_exit(
    *,
    observations: list[dict[str, Any]],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    good = policy["good_profit"]
    decel = policy["strong_deceleration"]
    risk = policy["risk_break"]

    prior_peak: float | None = None
    previous: dict[str, Any] | None = None

    for index, observation in enumerate(observations, start=1):
        current = float(observation["net_return_pct"])

        if current >= float(
            good["full_exit_at_or_above_net_return_pct"]
        ):
            return {
                "status": "CLOSED",
                "reason": "GOOD_PROFIT",
                "exit_offset_seconds": observation["offset_seconds"],
                "exit_observed_at": observation["observed_at"],
                "simulated_exit_return_pct": current,
                "prior_observed_peak_return_pct": prior_peak,
                "giveback_from_prior_peak_pct_points": (
                    prior_peak - current
                    if prior_peak is not None
                    else None
                ),
            }

        if previous is not None and prior_peak is not None:
            giveback = prior_peak - current
            step_deterioration = (
                float(previous["net_return_pct"]) - current
            )
            strong_deceleration = (
                prior_peak
                >= float(
                    decel["minimum_prior_peak_net_return_pct"]
                )
                and giveback
                >= float(
                    decel[
                        "minimum_giveback_from_observed_peak_pct_points"
                    ]
                )
                and step_deterioration
                >= float(
                    decel[
                        "minimum_single_step_deterioration_pct_points"
                    ]
                )
                and (
                    decel.get(
                        "requires_current_below_previous_observation"
                    )
                    is not True
                    or current < float(previous["net_return_pct"])
                )
            )
            if strong_deceleration:
                return {
                    "status": "CLOSED",
                    "reason": "STRONG_DECELERATION",
                    "exit_offset_seconds": observation["offset_seconds"],
                    "exit_observed_at": observation["observed_at"],
                    "simulated_exit_return_pct": current,
                    "prior_observed_peak_return_pct": prior_peak,
                    "giveback_from_prior_peak_pct_points": giveback,
                    "single_step_deterioration_pct_points": (
                        step_deterioration
                    ),
                }

        if (
            previous is not None
            and index >= int(risk["minimum_observation_count"])
            and current
            <= float(risk["full_exit_at_or_below_net_return_pct"])
            and (
                risk.get(
                    "requires_current_below_previous_observation"
                )
                is not True
                or current < float(previous["net_return_pct"])
            )
        ):
            return {
                "status": "CLOSED",
                "reason": "RISK_BREAK",
                "exit_offset_seconds": observation["offset_seconds"],
                "exit_observed_at": observation["observed_at"],
                "simulated_exit_return_pct": current,
                "prior_observed_peak_return_pct": prior_peak,
                "giveback_from_prior_peak_pct_points": (
                    prior_peak - current
                    if prior_peak is not None
                    else None
                ),
            }

        prior_peak = (
            current
            if prior_peak is None
            else max(prior_peak, current)
        )
        previous = observation

    last = observations[-1] if observations else None
    return {
        "status": "CENSORED_OPEN",
        "reason": "NO_CAUSAL_EXIT_TRIGGER_ON_OBSERVED_PATH",
        "exit_offset_seconds": None,
        "exit_observed_at": None,
        "simulated_exit_return_pct": None,
        "prior_observed_peak_return_pct": prior_peak,
        "giveback_from_prior_peak_pct_points": None,
        "last_observed_return_pct": (
            float(last["net_return_pct"]) if last else None
        ),
        "last_observed_offset_seconds": (
            int(last["offset_seconds"]) if last else None
        ),
    }


def _evaluate_trade(
    *,
    path_episode: Mapping[str, Any],
    fixed_decision: Mapping[str, Any],
    contract: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    observations = _path_observations(
        path_episode=path_episode,
        fixed_decision=fixed_decision,
        contract=contract,
    )
    path = _path_metrics(observations)
    exit_result = _trigger_exit(
        observations=observations,
        policy=policy,
    )
    simulated = exit_result.get("simulated_exit_return_pct")
    fixed = float(fixed_decision["fixed_return_pct"])

    return {
        "episode_key": fixed_decision["episode_key"],
        "token_mint": fixed_decision["token_mint"],
        "decision_as_of": fixed_decision.get("decision_as_of"),
        "fixed_60_return_pct": fixed,
        "path": path,
        "human_exit": exit_result,
        "human_minus_fixed_pct_points": (
            float(simulated) - fixed
            if simulated is not None
            else None
        ),
        "human_exit_better_than_fixed": (
            float(simulated) > fixed
            if simulated is not None
            else None
        ),
    }


def run_diagnostic(
    *,
    contract_path: Path,
    policy_path: Path,
    route_result_path: Path,
    market_paths_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    contract = _read_json(contract_path)
    policy = _read_json(policy_path)
    route_result = _read_json(route_result_path)
    market_paths = _read_json(market_paths_path)

    route_hash = str(contract.get("contract_hash_sha256") or "")
    _validate_policy(policy, route_contract_hash=route_hash)

    if route_result.get("contract_hash_sha256") != route_hash:
        raise ValueError("route-result contract hash mismatch")
    if market_paths.get("route_contract_hash_sha256") != route_hash:
        raise ValueError("market-path contract hash mismatch")

    notional = float(contract["position"]["notional_usd"])
    fixed = _fixed_rows(route_result, notional=notional)
    path_by_key = {
        str(item.get("episode_key") or ""): item
        for item in market_paths.get("episodes") or []
        if str(item.get("episode_key") or "")
    }

    trades: list[dict[str, Any]] = []
    for key, fixed_decision in fixed.items():
        path_episode = path_by_key.get(key)
        if path_episode is None:
            continue
        trades.append(
            _evaluate_trade(
                path_episode=path_episode,
                fixed_decision=fixed_decision,
                contract=contract,
                policy=policy,
            )
        )

    trades.sort(
        key=lambda row: (
            int(row.get("decision_as_of") or 0),
            row["token_mint"],
        )
    )

    triggered = [
        row
        for row in trades
        if row["human_exit"]["status"] == "CLOSED"
    ]
    censored = [
        row
        for row in trades
        if row["human_exit"]["status"] == "CENSORED_OPEN"
    ]
    human_returns = [
        float(row["human_exit"]["simulated_exit_return_pct"])
        for row in triggered
    ]
    fixed_triggered = [
        float(row["fixed_60_return_pct"])
        for row in triggered
    ]
    fixed_all = [float(row["fixed_60_return_pct"]) for row in trades]
    mfe_values = [
        float(row["path"]["observed_mfe_pct"])
        for row in trades
        if row["path"]["observed_mfe_pct"] is not None
    ]
    mae_values = [
        float(row["path"]["observed_mae_pct"])
        for row in trades
        if row["path"]["observed_mae_pct"] is not None
    ]

    reason_counts = Counter(
        str(row["human_exit"]["reason"]) for row in trades
    )
    better_count = sum(
        row["human_exit_better_than_fixed"] is True
        for row in triggered
    )
    worse_count = sum(
        row["human_exit_better_than_fixed"] is False
        for row in triggered
    )

    result = {
        "type": "causal_human_exit_retrospective_diagnostic_v0",
        "version": VERSION,
        "classification": PASS,
        "policy_hash_sha256": policy["policy_hash_sha256"],
        "route_contract_hash_sha256": route_hash,
        "paired_path_trade_count": len(trades),
        "causal_exit_triggered_count": len(triggered),
        "causal_exit_trigger_rate_pct": (
            100.0 * len(triggered) / len(trades)
            if trades
            else None
        ),
        "censored_open_count": len(censored),
        "exit_reason_counts": dict(sorted(reason_counts.items())),
        "fixed_60_all_path_entries": _aggregate_returns(fixed_all),
        "triggered_subset": {
            "fixed_60": _aggregate_returns(fixed_triggered),
            "causal_human_exit": _aggregate_returns(human_returns),
            "human_minus_fixed_mean_pct_points": (
                sum(
                    float(row["human_minus_fixed_pct_points"])
                    for row in triggered
                ) / len(triggered)
                if triggered
                else None
            ),
            "human_exit_better_count": better_count,
            "human_exit_worse_or_equal_count": worse_count,
            "human_exit_better_share_pct": (
                100.0 * better_count / len(triggered)
                if triggered
                else None
            ),
        },
        "market_path": {
            "observed_mfe": _aggregate_returns(mfe_values),
            "observed_mae": _aggregate_returns(mae_values),
            "mfe_at_least_10_pct_count": sum(
                value >= 10.0 for value in mfe_values
            ),
            "mfe_at_least_20_pct_count": sum(
                value >= 20.0 for value in mfe_values
            ),
            "mfe_at_least_25_pct_count": sum(
                value >= 25.0 for value in mfe_values
            ),
            "mfe_at_least_50_pct_count": sum(
                value >= 50.0 for value in mfe_values
            ),
        },
        "trades": trades,
        "guardrails": {
            "retrospective_only": True,
            "confirms_signal_edge": False,
            "confirms_human_assisted_edge": False,
            "confirms_autonomous_edge": False,
            "fixed_60_preserved": True,
            "no_policy_retuning_after_result": True,
            "mfe_is_not_exit": True,
            "censored_open_not_counted_as_realized_exit": True,
            "continuous_first_touch_claim": False,
            "flow_deceleration_claim": False,
        },
        "interpretation": (
            "Retrospective diagnostic on already-collected route-shadow "
            "paths. GOOD_PROFIT / price-path STRONG_DECELERATION / "
            "RISK_BREAK are evaluated only at observed route marks. "
            "This can show whether a human-realistic causal exit policy "
            "would have improved already-seen paths, but it cannot confirm "
            "edge because the market sample predates this policy."
        ),
    }
    _write_json(output_path, result)
    return result


def _compact(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "classification": result.get("classification"),
        "policy_hash_sha256": result.get("policy_hash_sha256"),
        "paired_path_trade_count": result.get("paired_path_trade_count"),
        "causal_exit_triggered_count": result.get(
            "causal_exit_triggered_count"
        ),
        "causal_exit_trigger_rate_pct": result.get(
            "causal_exit_trigger_rate_pct"
        ),
        "censored_open_count": result.get("censored_open_count"),
        "exit_reason_counts": result.get("exit_reason_counts"),
        "fixed_60_all_path_entries": result.get(
            "fixed_60_all_path_entries"
        ),
        "triggered_subset": result.get("triggered_subset"),
        "market_path": result.get("market_path"),
        "guardrails": result.get("guardrails"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Retrospective causal human-exit diagnostic over an existing "
            "real-market route-shadow path artifact."
        )
    )
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--route-result", type=Path, required=True)
    parser.add_argument("--market-paths", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        result = run_diagnostic(
            contract_path=args.contract,
            policy_path=args.policy,
            route_result_path=args.route_result,
            market_paths_path=args.market_paths,
            output_path=args.output,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": (
                        "FAIL_CAUSAL_HUMAN_EXIT_RETROSPECTIVE_DIAGNOSTIC_V0"
                    ),
                    "error": f"{type(exc).__name__}:{exc}",
                },
                indent=2,
            )
        )
        return 2

    print(json.dumps(_compact(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
