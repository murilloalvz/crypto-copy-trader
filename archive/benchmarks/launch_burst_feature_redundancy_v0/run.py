from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable


AUDIT_VERSION = "launch_burst_feature_redundancy_v0"
PASS_CLASSIFICATION = "PASS_LAUNCH_BURST_FEATURE_REDUNDANCY_V0"
FAIL_CLASSIFICATION = "FAIL_LAUNCH_BURST_FEATURE_REDUNDANCY_V0"
EXPECTED_ANALYSIS_CLASSIFICATION = "PASS_LAUNCH_BURST_LIVE_FEATURE_ANALYSIS_V0"
DEFAULT_HORIZONS = (1, 5, 10, 30)
PRIMARY_HORIZON = 5


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _percentile(values: list[float], p: float) -> float | None:
    clean = sorted(value for value in values if math.isfinite(value))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    rank = (len(clean) - 1) * p
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return clean[low]
    weight = rank - low
    return clean[low] * (1.0 - weight) + clean[high] * weight


def _distribution(values: Iterable[Any]) -> dict[str, Any]:
    clean = [number for value in values if (number := _finite_number(value)) is not None]
    if not clean:
        return {
            "n": 0,
            "min": None,
            "p25": None,
            "p50": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "max": None,
            "mean": None,
        }
    return {
        "n": len(clean),
        "min": min(clean),
        "p25": _percentile(clean, 0.25),
        "p50": _percentile(clean, 0.50),
        "p75": _percentile(clean, 0.75),
        "p90": _percentile(clean, 0.90),
        "p95": _percentile(clean, 0.95),
        "max": max(clean),
        "mean": sum(clean) / len(clean),
    }


def _ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda pair: pair[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        average_rank = ((i + 1) + j) / 2.0
        for position in range(i, j):
            ranks[indexed[position][0]] = average_rank
        i = j
    return ranks


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    dx = [value - mean_x for value in xs]
    dy = [value - mean_y for value in ys]
    var_x = sum(value * value for value in dx)
    var_y = sum(value * value for value in dy)
    if var_x <= 0.0 or var_y <= 0.0:
        return None
    covariance = sum(a * b for a, b in zip(dx, dy))
    return covariance / math.sqrt(var_x * var_y)


def _spearman(pairs: Iterable[tuple[Any, Any]]) -> dict[str, Any]:
    xs: list[float] = []
    ys: list[float] = []
    for raw_x, raw_y in pairs:
        x = _finite_number(raw_x)
        y = _finite_number(raw_y)
        if x is None or y is None:
            continue
        xs.append(x)
        ys.append(y)
    rho = _pearson(_ranks(xs), _ranks(ys)) if len(xs) >= 3 else None
    return {"n": len(xs), "rho": rho}


def _horizon_features(launch: dict[str, Any], horizon: int) -> dict[str, Any] | None:
    payload = ((launch.get("horizons") or {}).get(str(horizon)) or {})
    if payload.get("complete") is not True:
        return None
    features = payload.get("features")
    return features if isinstance(features, dict) else None


def _feature(features: dict[str, Any] | None, name: str) -> Any:
    if features is None:
        return None
    if name.startswith("time_to_"):
        n = name.removeprefix("time_to_").removesuffix("_events_ms")
        return (features.get("time_to_n_events_ms") or {}).get(n)
    return features.get(name)


def _flow_efficiency(features: dict[str, Any] | None) -> float | None:
    if features is None:
        return None
    signed = _finite_number(features.get("signed_flow_over_event_reserve"))
    gross = _finite_number(features.get("gross_turnover_over_event_reserve"))
    if signed is None or gross is None or gross <= 0.0:
        return None
    return signed / gross


def _pct(numerator: int, denominator: int) -> float | None:
    return 100.0 * numerator / denominator if denominator else None


def _coverage(values: Iterable[Any], denominator: int) -> dict[str, Any]:
    clean = [value for value in values if _finite_number(value) is not None]
    return {"n": len(clean), "pct": _pct(len(clean), denominator)}


def _stratum_audit(launches: list[dict[str, Any]], stratum: str) -> dict[str, Any]:
    rows = [row for row in launches if row.get("stratum") == stratum]
    anchor_count = len(rows)
    candidate_names = (
        "event_count",
        "signed_flow_over_event_reserve",
        "gross_turnover_over_event_reserve",
        "buy_sell_count_imbalance",
        "unique_wallet_count",
        "unique_transaction_count",
        "first_trade_delay_ms",
        "time_to_5_events_ms",
    )

    horizons: dict[str, Any] = {}
    for horizon in DEFAULT_HORIZONS:
        feature_rows = [
            features
            for row in rows
            if (features := _horizon_features(row, horizon)) is not None
        ]
        nonempty = [features for features in feature_rows if int(features.get("event_count") or 0) > 0]
        horizons[str(horizon)] = {
            "complete_count": len(feature_rows),
            "nonempty_count": len(nonempty),
            "nonempty_pct": _pct(len(nonempty), len(feature_rows)),
            "features": {
                name: {
                    "coverage": _coverage((_feature(features, name) for features in feature_rows), len(feature_rows)),
                    "distribution": _distribution(_feature(features, name) for features in feature_rows),
                }
                for name in candidate_names
            },
            "flow_efficiency": {
                "coverage": _coverage((_flow_efficiency(features) for features in feature_rows), len(feature_rows)),
                "distribution": _distribution(_flow_efficiency(features) for features in feature_rows),
            },
            "wallet_identity_coverage_pct": _distribution(
                features.get("wallet_identity_coverage_pct") for features in feature_rows
            ),
            "transaction_identity_coverage_pct": _distribution(
                features.get("transaction_identity_coverage_pct") for features in feature_rows
            ),
        }

    primary_rows = [
        features
        for row in rows
        if (features := _horizon_features(row, PRIMARY_HORIZON)) is not None
    ]
    primary_values: dict[str, list[Any]] = {
        name: [_feature(features, name) for features in primary_rows]
        for name in candidate_names
    }
    primary_values["flow_efficiency"] = [_flow_efficiency(features) for features in primary_rows]

    correlations: dict[str, Any] = {}
    correlation_names = (
        "event_count",
        "signed_flow_over_event_reserve",
        "gross_turnover_over_event_reserve",
        "buy_sell_count_imbalance",
        "unique_wallet_count",
        "time_to_5_events_ms",
        "flow_efficiency",
    )
    for index, left in enumerate(correlation_names):
        for right in correlation_names[index + 1 :]:
            correlations[f"{left}__{right}"] = _spearman(
                zip(primary_values[left], primary_values[right])
            )

    trajectories: dict[str, Any] = {}
    for start, end in ((1, 5), (5, 10)):
        event_delta: list[float] = []
        event_multiplier: list[float] = []
        signed_delta: list[float] = []
        gross_delta: list[float] = []
        wallet_delta: list[float] = []
        same_anchor_count = 0
        for row in rows:
            start_features = _horizon_features(row, start)
            end_features = _horizon_features(row, end)
            if start_features is None or end_features is None:
                continue
            same_anchor_count += 1
            start_events = _finite_number(start_features.get("event_count"))
            end_events = _finite_number(end_features.get("event_count"))
            if start_events is not None and end_events is not None:
                event_delta.append(end_events - start_events)
                event_multiplier.append(end_events / max(start_events, 1.0))
            start_signed = _finite_number(start_features.get("signed_flow_over_event_reserve"))
            end_signed = _finite_number(end_features.get("signed_flow_over_event_reserve"))
            if start_signed is not None and end_signed is not None:
                signed_delta.append(end_signed - start_signed)
            start_gross = _finite_number(start_features.get("gross_turnover_over_event_reserve"))
            end_gross = _finite_number(end_features.get("gross_turnover_over_event_reserve"))
            if start_gross is not None and end_gross is not None:
                gross_delta.append(end_gross - start_gross)
            start_wallet = _finite_number(start_features.get("unique_wallet_count"))
            end_wallet = _finite_number(end_features.get("unique_wallet_count"))
            if start_wallet is not None and end_wallet is not None:
                wallet_delta.append(end_wallet - start_wallet)
        trajectories[f"{start}_to_{end}"] = {
            "same_anchor_count": same_anchor_count,
            "event_delta": _distribution(event_delta),
            "event_multiplier": _distribution(event_multiplier),
            "signed_flow_delta": _distribution(signed_delta),
            "gross_turnover_delta": _distribution(gross_delta),
            "wallet_delta": _distribution(wallet_delta),
        }

    reach: dict[str, Any] = {}
    for horizon in (1, 5, 10):
        feature_rows = [
            features
            for row in rows
            if (features := _horizon_features(row, horizon)) is not None
        ]
        for n in (3, 5, 10):
            reached = sum(
                _feature(features, f"time_to_{n}_events_ms") is not None
                for features in feature_rows
            )
            reach[f"reach_{n}_events_by_{horizon}s"] = {
                "n": reached,
                "denominator": len(feature_rows),
                "pct": _pct(reached, len(feature_rows)),
            }

    return {
        "anchor_count": anchor_count,
        "primary_horizon_seconds": PRIMARY_HORIZON,
        "horizons": horizons,
        "primary_5s_spearman": correlations,
        "trajectories": trajectories,
        "reach_rates": reach,
    }


def run_audit(*, analysis_report: Path, output: Path) -> dict[str, Any]:
    analysis = _read_json(analysis_report)
    if analysis.get("classification") != EXPECTED_ANALYSIS_CLASSIFICATION:
        raise ValueError("analysis report must be PASS_LAUNCH_BURST_LIVE_FEATURE_ANALYSIS_V0")
    contract = analysis.get("research_contract") or {}
    if contract.get("outcome_blind") is not True or contract.get("future_outcomes_loaded") is not False:
        raise ValueError("analysis source is not outcome-blind")

    launches = list(analysis.get("launches") or [])
    result = {
        "type": "launch_burst_feature_redundancy_audit",
        "version": AUDIT_VERSION,
        "classification": PASS_CLASSIFICATION,
        "capture_id": analysis.get("capture_id"),
        "source_analysis_report": str(Path(analysis_report).resolve()),
        "outcome_blind": True,
        "future_outcomes_loaded": False,
        "thresholds_optimized": False,
        "strata": {
            stratum: _stratum_audit(launches, stratum)
            for stratum in ("pump_launch", "pumpswap_liquidity_launch")
        },
        "interpretation_contract": {
            "correlation_is_redundancy_evidence_not_edge": True,
            "trajectory_is_feature_dynamics_not_profit_evidence": True,
            "missing_identity_is_not_zero_participation": True,
            "pump_and_pumpswap_remain_separate": True,
        },
    }
    _write_json(output, result)
    return result


def _compact(result: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {
        "classification": result.get("classification"),
        "capture_id": result.get("capture_id"),
        "strata": {},
    }
    for stratum, payload in (result.get("strata") or {}).items():
        horizon5 = ((payload.get("horizons") or {}).get("5") or {})
        features5 = horizon5.get("features") or {}
        output["strata"][stratum] = {
            "anchor_count": payload.get("anchor_count"),
            "5s": {
                "event_count": features5.get("event_count"),
                "signed_flow_over_event_reserve": features5.get("signed_flow_over_event_reserve"),
                "gross_turnover_over_event_reserve": features5.get("gross_turnover_over_event_reserve"),
                "buy_sell_count_imbalance": features5.get("buy_sell_count_imbalance"),
                "unique_wallet_count": features5.get("unique_wallet_count"),
                "time_to_5_events_ms": features5.get("time_to_5_events_ms"),
                "flow_efficiency": horizon5.get("flow_efficiency"),
                "wallet_identity_coverage_pct": horizon5.get("wallet_identity_coverage_pct"),
            },
            "primary_5s_spearman": payload.get("primary_5s_spearman"),
            "trajectories": payload.get("trajectories"),
            "reach_rates": payload.get("reach_rates"),
        }
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Outcome-blind Launch Burst feature redundancy audit")
    parser.add_argument("--analysis-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_audit(analysis_report=args.analysis_report, output=args.output)
    except Exception as exc:
        print(json.dumps({"classification": FAIL_CLASSIFICATION, "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(_compact(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
