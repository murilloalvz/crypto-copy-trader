from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping

VERSION = "buy_event_acceleration_replication_v0"
PASS = "PASS_BUY_EVENT_ACCELERATION_REPLICATION_V0"
FEATURE_ID = "mf_buy_event_rate_acceleration_per_s2"
DEFAULT_PROTOCOL = Path("benchmarks") / "buy_event_acceleration_replication_v0" / "protocol.frozen.json"
DEFAULT_CONTRACT = Path("benchmarks") / "launch_burst_prospective_economic_v1" / "pump_route_paper_contract_v2.frozen.json"
ROUTEABLE_ARTIFACT = "market-first-routeable-edge-discovery-v2.json"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def _ordered(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    out = float(value)
    return None if math.isnan(out) else out


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    p = (len(xs) - 1) * q
    lo, hi = int(math.floor(p)), int(math.ceil(p))
    if lo == hi:
        return xs[lo]
    w = p - lo
    return xs[lo] * (1 - w) + xs[hi] * w


def _profit_factor(returns: list[float]) -> float | None:
    gains = sum(x for x in returns if x > 0)
    losses = -sum(x for x in returns if x < 0)
    if losses > 0:
        return gains / losses
    if gains > 0:
        return float("inf")
    return None


def _average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2.0
        for pos in range(start, end):
            ranks[order[pos]] = rank
        start = end
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    lm, rm = sum(left) / len(left), sum(right) / len(right)
    numerator = sum((x - lm) * (y - rm) for x, y in zip(left, right))
    lss = sum((x - lm) ** 2 for x in left)
    rss = sum((y - rm) ** 2 for y in right)
    if lss <= 0 or rss <= 0:
        return None
    out = numerator / math.sqrt(lss * rss)
    return out if math.isfinite(out) else None


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    return _pearson(_average_ranks(left), _average_ranks(right))


def _max_drawdown_usd(returns: list[float], notional_usd: float) -> float | None:
    if not returns:
        return None
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in returns:
        equity += notional_usd * value / 100.0
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def _summary(
    rows: list[dict[str, Any]],
    *,
    decisions: Mapping[str, Mapping[str, Any]],
    notional_usd: float,
) -> dict[str, Any]:
    returns = [float(row["fixed_return_pct"]) for row in rows if _finite(row.get("fixed_return_pct")) is not None]
    gross: list[float] = []
    for row in rows:
        decision = decisions.get(str(row.get("episode_key") or "")) or {}
        value = _finite(decision.get("gross_route_return_pct"))
        if value is not None:
            gross.append(value)

    without_best = list(returns)
    if without_best:
        without_best.remove(max(without_best))
    gains = [value for value in returns if value > 0]
    positive_sum = sum(gains)
    largest_winner_share = (
        100.0 * max(gains) / positive_sum
        if gains and positive_sum > 0
        else None
    )
    return {
        "n": len(returns),
        "gross_return_available_n": len(gross),
        "mean_gross_return_pct": sum(gross) / len(gross) if gross else None,
        "mean_return_pct": sum(returns) / len(returns) if returns else None,
        "median_return_pct": median(returns) if returns else None,
        "expectancy_per_trade_pct": sum(returns) / len(returns) if returns else None,
        "p10_return_pct": _percentile(returns, 0.10),
        "p05_return_pct": _percentile(returns, 0.05),
        "best_return_pct": max(returns) if returns else None,
        "worst_return_pct": min(returns) if returns else None,
        "mean_without_best_trade_pct": sum(without_best) / len(without_best) if without_best else None,
        "win_rate_pct": 100.0 * sum(value > 0 for value in returns) / len(returns) if returns else None,
        "profit_factor": _profit_factor(returns),
        "largest_winner_share_of_gross_positive_return_pct": largest_winner_share,
        "total_pnl_usd": notional_usd * sum(returns) / 100.0 if returns else None,
        "max_drawdown_usd_on_sequential_pnl_curve": _max_drawdown_usd(returns, notional_usd),
        "positive_trade_count": sum(value > 0 for value in returns),
        "negative_trade_count": sum(value < 0 for value in returns),
        "zero_trade_count": sum(value == 0 for value in returns),
    }


def _validate_protocol(protocol: Mapping[str, Any], contract: Mapping[str, Any]) -> None:
    expected = str(protocol.get("protocol_hash_sha256") or "")
    shadow = {key: value for key, value in dict(protocol).items() if key != "protocol_hash_sha256"}
    actual = hashlib.sha256(_canonical_json(shadow).encode("utf-8")).hexdigest()
    if expected != actual:
        raise ValueError("buy-event-acceleration protocol hash mismatch")
    if protocol.get("status") != "PREREGISTERED_FRESH_CONFIRMATION":
        raise ValueError("protocol is not preregistered")
    if (protocol.get("hypothesis") or {}).get("feature_id") != FEATURE_ID:
        raise ValueError("unexpected feature")
    if (protocol.get("economic_contract") or {}).get("route_contract_hash_sha256") != contract.get("contract_hash_sha256"):
        raise ValueError("route contract hash mismatch")


def _status_summary(route_result: Mapping[str, Any]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    admitted = 0
    routeable = 0
    exit_failures = 0
    for decision in route_result.get("decisions") or []:
        if not isinstance(decision, dict) or decision.get("admitted") is not True:
            continue
        admitted += 1
        status = str(decision.get("status") or "MISSING")
        statuses[status] = statuses.get(status, 0) + 1
        if status == "ROUTE_CLOSED" or status.startswith("UNROUTABLE_EXIT"):
            routeable += 1
        if status.startswith("UNROUTABLE_EXIT"):
            exit_failures += 1
    return {
        "baseline_admitted_count": admitted,
        "route_usable_count": routeable,
        "routeability_pct": 100.0 * routeable / admitted if admitted else None,
        "entry_failure_count": admitted - routeable,
        "exit_failure_count": exit_failures,
        "status_counts": dict(sorted(statuses.items())),
    }


def _gt(left: Any, right: Any) -> bool:
    a, b = _ordered(left), _ordered(right)
    return a is not None and b is not None and a > b


def _gte(left: Any, right: Any) -> bool:
    a, b = _ordered(left), _ordered(right)
    return a is not None and b is not None and a >= b


def run_replication(
    *,
    discovery_run_dirs: list[Path],
    fresh_run_dir: Path,
    protocol_path: Path = DEFAULT_PROTOCOL,
    contract_path: Path = DEFAULT_CONTRACT,
    output_path: Path | None = None,
) -> dict[str, Any]:
    fresh_run_dir = Path(fresh_run_dir).resolve()
    discovery_run_dirs = [Path(path).resolve() for path in discovery_run_dirs]
    protocol = _read_json(protocol_path)
    contract = _read_json(contract_path)
    _validate_protocol(protocol, contract)

    required_discovery_count = int((protocol.get("sample_contract") or {}).get("discovery_capture_count") or 0)
    if len(discovery_run_dirs) != required_discovery_count:
        raise ValueError(f"expected exactly {required_discovery_count} discovery captures")

    contract_hash = str(contract.get("contract_hash_sha256") or "")
    fresh_route_input_path = fresh_run_dir / "route-input-v2.json"
    fresh_route_result_path = fresh_run_dir / "route-result-v2.json"
    routeable_path = fresh_run_dir / ROUTEABLE_ARTIFACT
    for path in (fresh_route_input_path, fresh_route_result_path, routeable_path):
        if not path.is_file():
            raise ValueError(f"required replication source missing: {path}")

    discovery_hashes: list[str] = []
    for run_dir in discovery_run_dirs:
        route_input_path = run_dir / "route-input-v2.json"
        if not route_input_path.is_file():
            raise ValueError(f"discovery route input missing: {route_input_path}")
        discovery_hashes.append(hashlib.sha256(route_input_path.read_bytes()).hexdigest())
    if len(set(discovery_hashes)) != len(discovery_hashes):
        raise ValueError("discovery capture identities are not unique")

    fresh_hash = hashlib.sha256(fresh_route_input_path.read_bytes()).hexdigest()
    if fresh_hash in set(discovery_hashes):
        raise ValueError("fresh capture identity matches a discovery capture")

    route_input = _read_json(fresh_route_input_path)
    route_result = _read_json(fresh_route_result_path)
    routeable = _read_json(routeable_path)
    if route_input.get("contract_hash_sha256") != contract_hash or route_result.get("contract_hash_sha256") != contract_hash:
        raise ValueError("fresh route source/contract mismatch")
    if route_input.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError("fresh feature snapshots were not frozen before provider quotes")
    if routeable.get("classification") != "PASS_MARKET_FIRST_ROUTEABLE_EDGE_DISCOVERY_V2":
        raise ValueError("fresh routeable artifact is not PASS")

    integrity = routeable.get("source_integrity") or {}
    if integrity.get("route_contract_hash_sha256") != contract_hash:
        raise ValueError("fresh routeable contract mismatch")
    if integrity.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError("fresh routeable snapshot timing integrity failed")
    if integrity.get("dynamics_exact_reconstruction_parity") is not True:
        raise ValueError("fresh dynamics reconstruction parity failed")
    if integrity.get("geometry_stored_event_count_parity") is not True:
        raise ValueError("fresh geometry event-count parity failed")
    if integrity.get("geometry_payload_decode_failures") != 0:
        raise ValueError("fresh geometry payload decode failures present")
    if integrity.get("exact_routeable_join") is not True:
        raise ValueError("fresh routeable join is not exact")

    decisions = {
        str(row.get("episode_key") or ""): row
        for row in route_result.get("decisions") or []
        if isinstance(row, dict) and str(row.get("episode_key") or "")
    }

    rows: list[dict[str, Any]] = []
    for row in routeable.get("rows") or []:
        if not isinstance(row, dict) or row.get("is_default_sol_quote") is not True:
            continue
        feature = _finite((row.get("features") or {}).get(FEATURE_ID))
        outcome = _finite(row.get("fixed_return_pct"))
        if feature is None or outcome is None:
            continue
        rows.append(
            {
                "episode_key": str(row.get("episode_key") or ""),
                "feature": feature,
                "fixed_return_pct": outcome,
            }
        )

    n = len(rows)
    xs = [row["feature"] for row in rows]
    ys = [row["fixed_return_pct"] for row in rows]
    rho = _spearman(xs, ys)

    rho_without_best = None
    if n >= 3:
        best_index = max(range(n), key=lambda index: ys[index])
        kept = [row for index, row in enumerate(rows) if index != best_index]
        rho_without_best = _spearman(
            [row["feature"] for row in kept],
            [row["fixed_return_pct"] for row in kept],
        )

    loo: list[float] = []
    if n >= 4:
        for drop_index in range(n):
            kept = [row for index, row in enumerate(rows) if index != drop_index]
            value = _spearman(
                [row["feature"] for row in kept],
                [row["fixed_return_pct"] for row in kept],
            )
            if value is not None:
                loo.append(value)

    sign_consistency = None
    if rho is not None and rho != 0 and loo:
        nonzero = [value for value in loo if value != 0]
        if nonzero:
            sign_consistency = sum((value < 0) == (rho < 0) for value in nonzero) / len(nonzero)

    split = median(xs) if xs else None
    lower_rows = [
        {"episode_key": row["episode_key"], "fixed_return_pct": row["fixed_return_pct"]}
        for row in rows
        if split is not None and row["feature"] <= split
    ]
    upper_rows = [
        {"episode_key": row["episode_key"], "fixed_return_pct": row["fixed_return_pct"]}
        for row in rows
        if split is not None and row["feature"] > split
    ]

    notional = float(contract["position"]["notional_usd"])
    lower = _summary(lower_rows, decisions=decisions, notional_usd=notional)
    upper = _summary(upper_rows, decisions=decisions, notional_usd=notional)
    minimum = int((protocol.get("population") or {}).get("minimum_primary_usable_route_results") or 0)

    checks = {
        "minimum_sample_met": n >= minimum,
        "spearman_negative": rho is not None and rho < 0,
        "spearman_without_best_negative": rho_without_best is not None and rho_without_best < 0,
        "leave_one_out_sign_consistency_gte_0_90": sign_consistency is not None and sign_consistency >= 0.90,
        "lower_half_mean_return_gt_0": _gt(lower.get("mean_return_pct"), 0.0),
        "lower_half_mean_without_best_gt_0": _gt(lower.get("mean_without_best_trade_pct"), 0.0),
        "lower_half_profit_factor_gt_1": _gt(lower.get("profit_factor"), 1.0),
        "lower_half_mean_gt_upper_half": _gt(lower.get("mean_return_pct"), upper.get("mean_return_pct")),
        "lower_half_median_gt_upper_half": _gt(lower.get("median_return_pct"), upper.get("median_return_pct")),
        "lower_half_mean_without_best_gt_upper_half": _gt(lower.get("mean_without_best_trade_pct"), upper.get("mean_without_best_trade_pct")),
        "lower_half_profit_factor_gt_upper_half": _gt(lower.get("profit_factor"), upper.get("profit_factor")),
        "lower_half_p10_gte_upper_half": _gte(lower.get("p10_return_pct"), upper.get("p10_return_pct")),
    }

    rules = protocol.get("decision_rule") or {}
    if n < minimum:
        decision = "ITERATE"
        reasons = ["fresh_route_usable_feature_n_below_preregistered_minimum"]
    elif all(checks.get(name) is True for name in rules.get("keep_if_all") or []):
        decision = "KEEP"
        reasons = ["all_preregistered_keep_conditions_passed"]
    elif all(checks.get(name) is True for name in rules.get("iterate_if_all") or []):
        decision = "ITERATE"
        reasons = ["directional_replication_present_but_absolute_robust_profitability_not_met"]
    else:
        decision = "KILL"
        reasons = ["preregistered_keep_and_iterate_conditions_not_met"]

    report = {
        "type": "buy_event_acceleration_replication_report_v0",
        "version": VERSION,
        "classification": PASS,
        "decision": decision,
        "decision_reasons": reasons,
        "protocol_hash_sha256": protocol.get("protocol_hash_sha256"),
        "hypothesis": protocol.get("hypothesis"),
        "population": {
            "fresh_feature_route_usable_default_sol_n": n,
            "minimum_required_n": minimum,
            "fresh_median_feature_value": split,
            "lower_half_n": lower.get("n"),
            "upper_half_n": upper.get("n"),
        },
        "association": {
            "spearman_feature_vs_fixed_60s_return": rho,
            "spearman_without_best_trade": rho_without_best,
            "leave_one_out_spearman_min": min(loo) if loo else None,
            "leave_one_out_spearman_median": median(loo) if loo else None,
            "leave_one_out_spearman_max": max(loo) if loo else None,
            "leave_one_out_sign_consistency_fraction": sign_consistency,
        },
        "economics": {
            "lower_half_more_negative_acceleration": lower,
            "upper_half_less_negative_or_positive_acceleration": upper,
        },
        "routeability": _status_summary(route_result),
        "decision_rule_checks": checks,
        "economic_assumptions": protocol.get("economic_contract"),
        "source_integrity": {
            "discovery_route_input_sha256s": discovery_hashes,
            "fresh_route_input_sha256": fresh_hash,
            "fresh_capture_identity_differs_from_all_discovery": fresh_hash not in set(discovery_hashes),
            "route_contract_hash_sha256": contract_hash,
            "fresh_feature_snapshot_frozen_before_provider_quotes": True,
            "fresh_dynamics_exact_reconstruction_parity": True,
            "fresh_geometry_stored_event_count_parity": True,
            "fresh_geometry_payload_decode_failures": 0,
            "fresh_exact_routeable_join": True,
        },
        "guardrails": {
            "fresh_capture_required": True,
            "fixed_feature_threshold_used": False,
            "fresh_sample_median_split_supporting_only": True,
            "threshold_search_performed": False,
            "selector_changed": False,
            "economic_contract_changed": False,
            "landed_fill_claim": False,
            "realized_pnl_claim": False,
        },
    }

    destination = output_path or (fresh_run_dir / "buy-event-acceleration-replication-v0.json")
    destination.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    report["artifact"] = str(destination.resolve())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Fresh confirmation of BUY event-rate acceleration vs Fixed+60 return")
    parser.add_argument("--discovery-run-dir", type=Path, action="append", required=True)
    parser.add_argument("--fresh-run-dir", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    try:
        report = run_replication(
            discovery_run_dirs=args.discovery_run_dir,
            fresh_run_dir=args.fresh_run_dir,
            protocol_path=args.protocol,
            contract_path=args.contract,
            output_path=args.output,
        )
    except Exception as exc:
        print(json.dumps({
            "classification": "FAIL_BUY_EVENT_ACCELERATION_REPLICATION_V0",
            "error": f"{type(exc).__name__}:{exc}",
        }, indent=2))
        return 2

    compact = {
        "classification": report["classification"],
        "decision": report["decision"],
        "decision_reasons": report["decision_reasons"],
        "population": report["population"],
        "association": report["association"],
        "economics": report["economics"],
        "routeability": report["routeability"],
        "decision_rule_checks": report["decision_rule_checks"],
        "economic_assumptions": report["economic_assumptions"],
        "source_integrity": report["source_integrity"],
        "artifact": report["artifact"],
    }
    print(json.dumps(compact, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
