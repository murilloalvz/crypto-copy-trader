from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping

from benchmarks.launch_burst_control_taker_sim_v0.smart_exit import _fixed_rows
from src.market_first_bonding_curve_geometry_v1 import SOL_QUOTE_MINT

VERSION = "curve_capacity_replication_v0"
PASS = "PASS_CURVE_CAPACITY_REPLICATION_V0"
FEATURE_ID = "mf_curve_real_token_capacity_ratio_0_10_sol"
DEFAULT_PROTOCOL = Path("benchmarks") / "curve_capacity_replication_v0" / "protocol.frozen.json"
DEFAULT_CONTRACT = Path("benchmarks") / "launch_burst_prospective_economic_v1" / "pump_route_paper_contract_v2.frozen.json"


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
    value = float(value)
    return value if math.isfinite(value) else None


def _ordered(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return None if math.isnan(value) else value


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


def _pearson(a: list[float], b: list[float]) -> float | None:
    if len(a) != len(b) or len(a) < 2:
        return None
    am, bm = sum(a) / len(a), sum(b) / len(b)
    num = sum((x - am) * (y - bm) for x, y in zip(a, b))
    aa = sum((x - am) ** 2 for x in a)
    bb = sum((y - bm) ** 2 for y in b)
    if aa <= 0 or bb <= 0:
        return None
    out = num / math.sqrt(aa * bb)
    return out if math.isfinite(out) else None


def _spearman(a: list[float], b: list[float]) -> float | None:
    return _pearson(_average_ranks(a), _average_ranks(b)) if len(a) == len(b) and len(a) >= 2 else None


def _summary(rows: list[dict[str, Any]], decisions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    returns = [float(r["fixed_return_pct"]) for r in rows if _finite(r.get("fixed_return_pct")) is not None]
    gross = []
    for r in rows:
        d = decisions.get(str(r["episode_key"])) or {}
        g = _finite(d.get("gross_route_return_pct"))
        if g is not None:
            gross.append(g)
    without_best = list(returns)
    if without_best:
        without_best.remove(max(without_best))
    return {
        "n": len(returns),
        "mean_gross_return_pct": sum(gross) / len(gross) if gross else None,
        "gross_return_available_n": len(gross),
        "mean_return_pct": sum(returns) / len(returns) if returns else None,
        "median_return_pct": median(returns) if returns else None,
        "p10_return_pct": _percentile(returns, 0.10),
        "p05_return_pct": _percentile(returns, 0.05),
        "best_return_pct": max(returns) if returns else None,
        "worst_return_pct": min(returns) if returns else None,
        "mean_without_best_trade_pct": sum(without_best) / len(without_best) if without_best else None,
        "win_rate_pct": 100.0 * sum(x > 0 for x in returns) / len(returns) if returns else None,
        "profit_factor": _profit_factor(returns),
    }


def _validate_protocol(protocol: Mapping[str, Any], contract: Mapping[str, Any]) -> None:
    expected = str(protocol.get("protocol_hash_sha256") or "")
    shadow = {k: v for k, v in dict(protocol).items() if k != "protocol_hash_sha256"}
    actual = hashlib.sha256(_canonical_json(shadow).encode("utf-8")).hexdigest()
    if expected != actual:
        raise ValueError("curve-capacity protocol hash mismatch")
    if protocol.get("status") != "PREREGISTERED_FRESH_CONFIRMATION":
        raise ValueError("protocol is not preregistered")
    if (protocol.get("hypothesis") or {}).get("feature_id") != FEATURE_ID:
        raise ValueError("unexpected feature")
    if (protocol.get("economic_contract") or {}).get("route_contract_hash_sha256") != contract.get("contract_hash_sha256"):
        raise ValueError("route contract hash mismatch")


def _index_geometry(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in payload.get("rows") or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("episode_key") or "")
        if key:
            if key in out:
                raise ValueError(f"duplicate geometry episode_key: {key}")
            out[key] = row
    return out


def _status_summary(route_result: Mapping[str, Any]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    admitted = 0
    routeable = 0
    exit_failures = 0
    for d in route_result.get("decisions") or []:
        if not isinstance(d, dict) or d.get("admitted") is not True:
            continue
        admitted += 1
        status = str(d.get("status") or "MISSING")
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


def _gt(a: Any, b: Any) -> bool:
    x, y = _ordered(a), _ordered(b)
    return x is not None and y is not None and x > y


def _gte(a: Any, b: Any) -> bool:
    x, y = _ordered(a), _ordered(b)
    return x is not None and y is not None and x >= y


def run_replication(
    *,
    discovery_run_dir: Path,
    fresh_run_dir: Path,
    protocol_path: Path = DEFAULT_PROTOCOL,
    contract_path: Path = DEFAULT_CONTRACT,
    output_path: Path | None = None,
) -> dict[str, Any]:
    discovery_run_dir = Path(discovery_run_dir).resolve()
    fresh_run_dir = Path(fresh_run_dir).resolve()
    protocol, contract = _read_json(protocol_path), _read_json(contract_path)
    _validate_protocol(protocol, contract)
    contract_hash = str(contract["contract_hash_sha256"])

    old_route_input_path = discovery_run_dir / "route-input-v2.json"
    route_input_path = fresh_run_dir / "route-input-v2.json"
    route_result_path = fresh_run_dir / "route-result-v2.json"
    geometry_path = fresh_run_dir / "market-first-bonding-curve-geometry-v1.json"
    for p in (old_route_input_path, route_input_path, route_result_path, geometry_path):
        if not p.is_file():
            raise ValueError(f"required replication source missing: {p}")

    old_sha = hashlib.sha256(old_route_input_path.read_bytes()).hexdigest()
    fresh_sha = hashlib.sha256(route_input_path.read_bytes()).hexdigest()
    if old_sha == fresh_sha:
        raise ValueError("fresh capture identity matches discovery capture")

    route_input, route_result, geometry = _read_json(route_input_path), _read_json(route_result_path), _read_json(geometry_path)
    if route_input.get("contract_hash_sha256") != contract_hash or route_result.get("contract_hash_sha256") != contract_hash:
        raise ValueError("fresh route source/contract mismatch")
    if route_input.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError("fresh feature snapshots were not frozen before provider quotes")
    if geometry.get("classification") != "PASS_MARKET_FIRST_BONDING_CURVE_GEOMETRY_V1":
        raise ValueError("fresh geometry artifact is not PASS")
    gi = geometry.get("source_integrity") or {}
    if gi.get("route_contract_hash_sha256") != contract_hash:
        raise ValueError("fresh geometry route contract mismatch")
    if gi.get("stored_event_count_parity") is not True or gi.get("geometry_payload_decode_failures") != 0:
        raise ValueError("fresh geometry integrity failed")

    decisions = {
        str(d.get("episode_key") or ""): d
        for d in route_result.get("decisions") or []
        if isinstance(d, dict) and str(d.get("episode_key") or "")
    }
    fixed = _fixed_rows(route_result, float(contract["position"]["notional_usd"]))
    geo = _index_geometry(geometry)
    rows: list[dict[str, Any]] = []
    for f in fixed:
        key = str(f["episode_key"])
        g = geo.get(key)
        if not g or g.get("quote_mint") != SOL_QUOTE_MINT:
            continue
        feature = _finite((g.get("features") or {}).get(FEATURE_ID))
        outcome = _finite(f.get("fixed_return_pct"))
        if feature is None or outcome is None:
            continue
        rows.append({"episode_key": key, "feature": feature, "fixed_return_pct": outcome})

    n = len(rows)
    xs = [r["feature"] for r in rows]
    ys = [r["fixed_return_pct"] for r in rows]
    rho = _spearman(xs, ys)
    rho_without_best = None
    if n >= 3:
        best_i = max(range(n), key=lambda i: ys[i])
        kept = [r for i, r in enumerate(rows) if i != best_i]
        rho_without_best = _spearman([r["feature"] for r in kept], [r["fixed_return_pct"] for r in kept])

    loo: list[float] = []
    if n >= 4:
        for drop in range(n):
            kept = [r for i, r in enumerate(rows) if i != drop]
            rr = _spearman([r["feature"] for r in kept], [r["fixed_return_pct"] for r in kept])
            if rr is not None:
                loo.append(rr)
    sign_consistency = None
    if rho is not None and rho != 0 and loo:
        nonzero = [x for x in loo if x != 0]
        if nonzero:
            sign_consistency = sum((x < 0) == (rho < 0) for x in nonzero) / len(nonzero)

    split = median(xs) if xs else None
    lower_rows = [
        {"episode_key": r["episode_key"], "fixed_return_pct": r["fixed_return_pct"]}
        for r in rows if split is not None and r["feature"] <= split
    ]
    upper_rows = [
        {"episode_key": r["episode_key"], "fixed_return_pct": r["fixed_return_pct"]}
        for r in rows if split is not None and r["feature"] > split
    ]
    lower = _summary(lower_rows, decisions)
    upper = _summary(upper_rows, decisions)
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
        decision, reasons = "ITERATE", ["fresh_route_usable_feature_n_below_preregistered_minimum"]
    elif all(checks.get(name) is True for name in rules.get("keep_if_all") or []):
        decision, reasons = "KEEP", ["all_preregistered_keep_conditions_passed"]
    elif all(checks.get(name) is True for name in rules.get("iterate_if_all") or []):
        decision, reasons = "ITERATE", ["directional_replication_present_but_absolute_robust_profitability_not_met"]
    else:
        decision, reasons = "KILL", ["preregistered_keep_and_iterate_conditions_not_met"]

    report = {
        "type": "curve_capacity_replication_report_v0",
        "version": VERSION,
        "classification": PASS,
        "decision": decision,
        "decision_reasons": reasons,
        "protocol_hash_sha256": protocol.get("protocol_hash_sha256"),
        "hypothesis": protocol.get("hypothesis"),
        "population": {
            "fresh_feature_route_usable_n": n,
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
        "economics": {"lower_half": lower, "upper_half": upper},
        "routeability": _status_summary(route_result),
        "decision_rule_checks": checks,
        "source_integrity": {
            "discovery_route_input_sha256": old_sha,
            "fresh_route_input_sha256": fresh_sha,
            "fresh_capture_identity_differs": old_sha != fresh_sha,
            "route_contract_hash_sha256": contract_hash,
            "fresh_feature_snapshot_frozen_before_provider_quotes": True,
            "fresh_geometry_stored_event_count_parity": True,
            "fresh_geometry_payload_decode_failures": 0,
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
    dest = output_path or (fresh_run_dir / "curve-capacity-replication-v0.json")
    dest.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    report["artifact"] = str(dest.resolve())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Fresh replication of curve-capacity ratio vs Fixed+60 route-shadow return")
    parser.add_argument("--discovery-run-dir", type=Path, required=True)
    parser.add_argument("--fresh-run-dir", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_replication(
            discovery_run_dir=args.discovery_run_dir,
            fresh_run_dir=args.fresh_run_dir,
            protocol_path=args.protocol,
            contract_path=args.contract,
            output_path=args.output,
        )
    except Exception as exc:
        print(json.dumps({"classification": "FAIL_CURVE_CAPACITY_REPLICATION_V0", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
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
        "source_integrity": report["source_integrity"],
        "artifact": report["artifact"],
    }
    print(json.dumps(compact, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
