from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from benchmarks.launch_burst_control_taker_sim_v0.smart_exit import _fixed_rows
from src.market_first_bonding_curve_geometry_v1 import (
    FEATURE_IDS as GEOMETRY_FEATURE_IDS,
    SOL_QUOTE_MINT,
)
from src.market_first_feature_discovery_v1 import FEATURE_IDS as ACCELERATION_FEATURE_IDS
from src.opportunity_feature_matrix_v0 import FEATURE_MATRIX_V0, TRACK_MARKET_FIRST


VERSION = "market_first_routeable_edge_discovery_v2"
PASS = "PASS_MARKET_FIRST_ROUTEABLE_EDGE_DISCOVERY_V2"
DEFAULT_CONTRACT = (
    Path("benchmarks")
    / "launch_burst_prospective_economic_v1"
    / "pump_route_paper_contract_v2.frozen.json"
)

SNIPER_FEATURE_IDS = tuple(
    feature.feature_id
    for feature in FEATURE_MATRIX_V0.values()
    if feature.track == TRACK_MARKET_FIRST and feature.selector_eligible
)

FEATURE_FAMILIES = {
    **{feature_id: "frozen_sniper_v1" for feature_id in SNIPER_FEATURE_IDS},
    **{feature_id: "causal_dynamics_v1" for feature_id in ACCELERATION_FEATURE_IDS},
    **{feature_id: "bonding_curve_geometry_v1" for feature_id in GEOMETRY_FEATURE_IDS},
}
ALL_FEATURE_IDS = tuple(dict.fromkeys((*SNIPER_FEATURE_IDS, *ACCELERATION_FEATURE_IDS, *GEOMETRY_FEATURE_IDS)))


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


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _mean(values: Iterable[float]) -> float | None:
    rows = list(values)
    return sum(rows) / len(rows) if rows else None


def _average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2.0
        for position in range(start, end):
            ranks[order[position]] = rank
        start = end
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    lx = sum(left) / len(left)
    rx = sum(right) / len(right)
    numerator = sum((x - lx) * (y - rx) for x, y in zip(left, right))
    lss = sum((x - lx) ** 2 for x in left)
    rss = sum((y - rx) ** 2 for y in right)
    if lss <= 0 or rss <= 0:
        return None
    value = numerator / math.sqrt(lss * rss)
    return value if math.isfinite(value) else None


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    return _pearson(_average_ranks(left), _average_ranks(right))


def _outcome_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = [float(row["fixed_return_pct"]) for row in rows if _finite(row.get("fixed_return_pct")) is not None]
    if not returns:
        return {
            "trade_count": 0,
            "mean_return_pct": None,
            "median_return_pct": None,
            "positive_count": 0,
            "positive_share_pct": None,
            "best_return_pct": None,
            "worst_return_pct": None,
            "mean_return_without_best_trade_pct": None,
            "mean_return_without_worst_trade_pct": None,
        }
    best = max(returns)
    worst = min(returns)
    without_best = list(returns)
    without_best.remove(best)
    without_worst = list(returns)
    without_worst.remove(worst)
    positive_count = sum(value > 0 for value in returns)
    return {
        "trade_count": len(returns),
        "mean_return_pct": _mean(returns),
        "median_return_pct": median(returns),
        "positive_count": positive_count,
        "positive_share_pct": 100.0 * positive_count / len(returns),
        "best_return_pct": best,
        "worst_return_pct": worst,
        "mean_return_without_best_trade_pct": _mean(without_best),
        "mean_return_without_worst_trade_pct": _mean(without_worst),
    }


def _feature_association(rows: list[dict[str, Any]], feature_id: str) -> dict[str, Any]:
    pairs: list[tuple[float, float, str]] = []
    for row in rows:
        feature = _finite((row.get("features") or {}).get(feature_id))
        outcome = _finite(row.get("fixed_return_pct"))
        if feature is not None and outcome is not None:
            pairs.append((feature, outcome, str(row.get("episode_key") or "")))

    feature_values = [item[0] for item in pairs]
    outcomes = [item[1] for item in pairs]
    full_rho = _spearman(feature_values, outcomes)

    rho_without_best = None
    rho_without_worst = None
    if len(pairs) >= 3:
        best_index = max(range(len(pairs)), key=lambda index: pairs[index][1])
        worst_index = min(range(len(pairs)), key=lambda index: pairs[index][1])
        keep_best_removed = [item for index, item in enumerate(pairs) if index != best_index]
        keep_worst_removed = [item for index, item in enumerate(pairs) if index != worst_index]
        rho_without_best = _spearman(
            [item[0] for item in keep_best_removed],
            [item[1] for item in keep_best_removed],
        )
        rho_without_worst = _spearman(
            [item[0] for item in keep_worst_removed],
            [item[1] for item in keep_worst_removed],
        )

    leave_one_out: list[float] = []
    if len(pairs) >= 4:
        for drop_index in range(len(pairs)):
            reduced = [item for index, item in enumerate(pairs) if index != drop_index]
            rho = _spearman([item[0] for item in reduced], [item[1] for item in reduced])
            if rho is not None:
                leave_one_out.append(float(rho))

    positive_features = [feature for feature, outcome, _ in pairs if outcome > 0]
    nonpositive_features = [feature for feature, outcome, _ in pairs if outcome <= 0]

    sign_consistency = None
    if full_rho is not None and leave_one_out and full_rho != 0:
        same = sum((rho > 0) == (full_rho > 0) for rho in leave_one_out if rho != 0)
        nonzero = sum(rho != 0 for rho in leave_one_out)
        sign_consistency = same / nonzero if nonzero else None

    return {
        "family": FEATURE_FAMILIES.get(feature_id, "unknown"),
        "usable_pair_count": len(pairs),
        "missing_feature_count_with_outcome": sum(
            1
            for row in rows
            if _finite(row.get("fixed_return_pct")) is not None
            and _finite((row.get("features") or {}).get(feature_id)) is None
        ),
        "spearman_with_fixed_60s_return": full_rho,
        "spearman_without_best_return_trade": rho_without_best,
        "spearman_without_worst_return_trade": rho_without_worst,
        "leave_one_out_spearman_min": min(leave_one_out) if leave_one_out else None,
        "leave_one_out_spearman_median": median(leave_one_out) if leave_one_out else None,
        "leave_one_out_spearman_max": max(leave_one_out) if leave_one_out else None,
        "leave_one_out_sign_consistency_fraction": sign_consistency,
        "feature_mean": _mean(feature_values),
        "feature_median": median(feature_values) if feature_values else None,
        "feature_mean_positive_outcomes": _mean(positive_features),
        "feature_mean_nonpositive_outcomes": _mean(nonpositive_features),
        "positive_outcome_pair_count": len(positive_features),
        "nonpositive_outcome_pair_count": len(nonpositive_features),
        "threshold_search_performed": False,
        "inference_role": "RETROSPECTIVE_DISCOVERY_DIAGNOSTIC_ONLY_NO_EDGE_CLAIM",
    }


def _cohort(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "outcomes": _outcome_summary(rows),
        "features": {feature_id: _feature_association(rows, feature_id) for feature_id in ALL_FEATURE_IDS},
    }


def _index_rows(payload: dict[str, Any], name: str) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in payload.get("rows") or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("episode_key") or "")
        if not key:
            continue
        if key in output:
            raise ValueError(f"duplicate episode_key in {name}: {key}")
        output[key] = row
    return output


def run_discovery_v2(
    *,
    run_dir: Path,
    contract_path: Path = DEFAULT_CONTRACT,
    output_path: Path | None = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    route_input_path = run_dir / "route-input-v2.json"
    route_result_path = run_dir / "route-result-v2.json"
    sniper_path = run_dir / "sniper-comparison-v1.json"
    dynamics_path = run_dir / "market-first-feature-discovery-v1.json"
    geometry_path = run_dir / "market-first-bonding-curve-geometry-v1.json"
    for path in (route_input_path, route_result_path, sniper_path, dynamics_path, geometry_path, contract_path):
        if not Path(path).is_file():
            raise ValueError(f"required routeable edge source missing: {path}")

    route_input = _read_json(route_input_path)
    route_result = _read_json(route_result_path)
    sniper = _read_json(sniper_path)
    dynamics = _read_json(dynamics_path)
    geometry = _read_json(geometry_path)
    contract = _read_json(contract_path)

    contract_hash = str(contract.get("contract_hash_sha256") or "")
    if not contract_hash:
        raise ValueError("route contract hash missing")
    if route_input.get("contract_hash_sha256") != contract_hash or route_result.get("contract_hash_sha256") != contract_hash:
        raise ValueError("routeable edge source/contract hash mismatch")
    if route_input.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError("feature snapshots were not frozen before provider quotes")
    if dynamics.get("classification") != "PASS_MARKET_FIRST_FEATURE_DISCOVERY_V1":
        raise ValueError("causal dynamics artifact is not PASS")
    if geometry.get("classification") != "PASS_MARKET_FIRST_BONDING_CURVE_GEOMETRY_V1":
        raise ValueError("bonding-curve geometry artifact is not PASS")

    dyn_integrity = dynamics.get("source_integrity") or {}
    geo_integrity = geometry.get("source_integrity") or {}
    if dyn_integrity.get("route_contract_hash_sha256") != contract_hash:
        raise ValueError("causal dynamics route contract mismatch")
    if dyn_integrity.get("exact_reconstruction_parity") is not True:
        raise ValueError("causal dynamics reconstruction parity is not exact")
    if geo_integrity.get("route_contract_hash_sha256") != contract_hash:
        raise ValueError("geometry route contract mismatch")
    if geo_integrity.get("stored_event_count_parity") is not True or geo_integrity.get("geometry_payload_decode_failures") != 0:
        raise ValueError("geometry source integrity is not exact")

    episodes = {
        str(row.get("episode_key") or ""): row
        for row in route_input.get("episodes") or []
        if isinstance(row, dict)
    }
    dynamics_rows = _index_rows(dynamics, "market-first-feature-discovery-v1")
    geometry_rows = _index_rows(geometry, "market-first-bonding-curve-geometry-v1")
    selected_keys = {
        str(row.get("episode_key") or "")
        for row in ((sniper.get("primary_selector_diagnostics") or {}).get("rows") or [])
        if isinstance(row, dict) and row.get("selected") is True
    }

    notional = float(contract["position"]["notional_usd"])
    fixed_rows = _fixed_rows(route_result, notional)
    analysis_rows: list[dict[str, Any]] = []
    missing_join: list[str] = []

    for fixed in fixed_rows:
        episode_key = str(fixed.get("episode_key") or "")
        episode = episodes.get(episode_key)
        dyn = dynamics_rows.get(episode_key)
        geo = geometry_rows.get(episode_key)
        if episode is None or dyn is None or geo is None:
            missing_join.append(episode_key)
            continue
        snapshot = episode.get("feature_snapshot") or {}
        if snapshot.get("complete") is not True:
            missing_join.append(f"incomplete:{episode_key}")
            continue
        snapshot_features = snapshot.get("features") or {}
        features: dict[str, Any] = {
            feature_id: snapshot_features.get(feature_id)
            for feature_id in SNIPER_FEATURE_IDS
        }
        dyn_features = dyn.get("features") or {}
        for feature_id in ACCELERATION_FEATURE_IDS:
            features[feature_id] = dyn_features.get(feature_id)
        geo_features = geo.get("features") or {}
        for feature_id in GEOMETRY_FEATURE_IDS:
            features[feature_id] = geo_features.get(feature_id)

        analysis_rows.append(
            {
                "episode_key": episode_key,
                "token_mint": fixed.get("token_mint"),
                "sniper_selected": episode_key in selected_keys,
                "route_status": fixed.get("status"),
                "fixed_return_pct": fixed.get("fixed_return_pct"),
                "quote_mint": geo.get("quote_mint"),
                "is_default_sol_quote": geo.get("quote_mint") == SOL_QUOTE_MINT,
                "features": features,
            }
        )

    if missing_join:
        raise ValueError("routeable edge join failed: " + ";".join(missing_join[:10]))

    baseline_rows = list(analysis_rows)
    sniper_rows = [row for row in baseline_rows if row["sniper_selected"]]
    baseline_sol_rows = [row for row in baseline_rows if row["is_default_sol_quote"]]
    sniper_sol_rows = [row for row in sniper_rows if row["is_default_sol_quote"]]

    report = {
        "type": "market_first_routeable_edge_discovery_report_v2",
        "version": VERSION,
        "classification": PASS,
        "inference_role": "RETROSPECTIVE_DISCOVERY_ROUTEABLE_ONLY_NO_EDGE_CLAIM",
        "automatic_edge_claim": False,
        "threshold_search_performed": False,
        "selector_changed": False,
        "sniper_v1_changed": False,
        "economic_contract_changed": False,
        "primary_outcome": "frozen_fixed_plus_60s_route_shadow_return_pct",
        "source_integrity": {
            "run_dir": str(run_dir),
            "route_contract_hash_sha256": contract_hash,
            "feature_snapshot_frozen_before_provider_quotes": True,
            "dynamics_exact_reconstruction_parity": True,
            "geometry_stored_event_count_parity": True,
            "geometry_payload_decode_failures": 0,
            "route_usable_fixed_row_count": len(fixed_rows),
            "joined_route_usable_row_count": len(analysis_rows),
            "exact_routeable_join": len(fixed_rows) == len(analysis_rows),
        },
        "guardrails": {
            "entry_unavailable_excluded": True,
            "entry_price_impact_rejected_excluded": True,
            "provider_execution_metadata_used_as_feature": False,
            "future_outcome_used_as_feature": False,
            "same_sample_threshold_search_permitted": False,
            "multiple_feature_associations_are_hypothesis_generation_only": True,
            "fresh_capture_required_before_any_selector_promotion": True,
        },
        "feature_families": {
            "frozen_sniper_v1": list(SNIPER_FEATURE_IDS),
            "causal_dynamics_v1": list(ACCELERATION_FEATURE_IDS),
            "bonding_curve_geometry_v1": list(GEOMETRY_FEATURE_IDS),
        },
        "cohorts": {
            "baseline_route_usable": _cohort(baseline_rows),
            "sniper_route_usable": _cohort(sniper_rows),
            "baseline_route_usable_default_sol_quote": _cohort(baseline_sol_rows),
            "sniper_route_usable_default_sol_quote": _cohort(sniper_sol_rows),
        },
        "rows": analysis_rows,
        "interpretation": (
            "This artifact isolates alpha discovery from entry availability by keeping only route-paper episodes with a usable entry. "
            "Feature/outcome associations are descriptive and robustness-oriented; no feature is ranked into a selector and no threshold "
            "may be chosen on this sample. Any mechanistically plausible candidate must be frozen before a fresh prospective capture."
        ),
    }
    destination = output_path or (run_dir / "market-first-routeable-edge-discovery-v2.json")
    _write_json(Path(destination), report)
    report["artifact"] = str(Path(destination).resolve())
    return report


def _compact(report: dict[str, Any]) -> dict[str, Any]:
    cohorts = report.get("cohorts") or {}
    return {
        "classification": report.get("classification"),
        "inference_role": report.get("inference_role"),
        "source_integrity": report.get("source_integrity"),
        "guardrails": report.get("guardrails"),
        "baseline_route_usable": cohorts.get("baseline_route_usable"),
        "sniper_route_usable": cohorts.get("sniper_route_usable"),
        "baseline_route_usable_default_sol_quote": cohorts.get("baseline_route_usable_default_sol_quote"),
        "sniper_route_usable_default_sol_quote": cohorts.get("sniper_route_usable_default_sol_quote"),
        "artifact": report.get("artifact"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Routeable-only Market-First alpha discovery V2")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_discovery_v2(
            run_dir=args.run_dir,
            contract_path=args.contract,
            output_path=args.output,
        )
    except Exception as exc:
        print(json.dumps({"classification": "FAIL_MARKET_FIRST_ROUTEABLE_EDGE_DISCOVERY_V2", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(_compact(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
