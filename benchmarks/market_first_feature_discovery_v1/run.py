from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from benchmarks.launch_burst_control_taker_sim_v0.smart_exit import _fixed_rows
from benchmarks.launch_burst_prospective_route_paper_v2 import live as live_v2
from benchmarks.launch_burst_sniper_v1.runtime_enrichment import (
    feature_snapshot_with_sniper_v1,
    patched_sniper_feature_enrichment_v1,
)
from src.market_first_feature_discovery_v1 import (
    FEATURE_IDS,
    VERSION as FEATURE_VERSION,
    acceleration_features_v1,
    feature_definitions_v1,
    liquidity_exitability_discovery_status_v1,
)


VERSION = "market_first_feature_discovery_benchmark_v1"
PASS = "PASS_MARKET_FIRST_FEATURE_DISCOVERY_V1"
DEFAULT_CONTRACT = (
    Path("benchmarks")
    / "launch_burst_prospective_economic_v1"
    / "pump_route_paper_contract_v2.frozen.json"
)


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


def _same_number(left: Any, right: Any, *, abs_tol: float = 1e-12) -> bool:
    lvalue = _finite(left)
    rvalue = _finite(right)
    if lvalue is None or rvalue is None:
        return left is None and right is None
    return math.isclose(lvalue, rvalue, rel_tol=1e-9, abs_tol=abs_tol)


def _average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        average_rank = (start + 1 + end) / 2.0
        for position in range(start, end):
            ranks[order[position]] = average_rank
        start = end
    return ranks


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    numerator = sum((x - mean_left) * (y - mean_right) for x, y in zip(left, right))
    left_ss = sum((x - mean_left) ** 2 for x in left)
    right_ss = sum((y - mean_right) ** 2 for y in right)
    if left_ss <= 0 or right_ss <= 0:
        return None
    result = numerator / math.sqrt(left_ss * right_ss)
    return result if math.isfinite(result) else None


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    return _pearson(_average_ranks(left), _average_ranks(right))


def _mean(values: Iterable[float]) -> float | None:
    rows = list(values)
    return sum(rows) / len(rows) if rows else None


def _feature_association(rows: list[dict[str, Any]], feature_id: str) -> dict[str, Any]:
    pairs: list[tuple[float, float]] = []
    for row in rows:
        feature = _finite((row.get("features") or {}).get(feature_id))
        outcome = _finite(row.get("fixed_return_pct"))
        if feature is not None and outcome is not None:
            pairs.append((feature, outcome))
    feature_values = [pair[0] for pair in pairs]
    outcomes = [pair[1] for pair in pairs]
    positive_features = [feature for feature, outcome in pairs if outcome > 0]
    nonpositive_features = [feature for feature, outcome in pairs if outcome <= 0]
    return {
        "usable_pair_count": len(pairs),
        "missing_feature_count_with_outcome": sum(
            1
            for row in rows
            if _finite(row.get("fixed_return_pct")) is not None
            and _finite((row.get("features") or {}).get(feature_id)) is None
        ),
        "spearman_rank_correlation_with_fixed_60s_return": _spearman(feature_values, outcomes),
        "feature_mean": _mean(feature_values),
        "feature_median": median(feature_values) if feature_values else None,
        "feature_mean_positive_outcomes": _mean(positive_features),
        "feature_mean_nonpositive_outcomes": _mean(nonpositive_features),
        "positive_outcome_count": len(positive_features),
        "nonpositive_outcome_count": len(nonpositive_features),
        "threshold_search_performed": False,
        "inference_role": "DISCOVERY_DIAGNOSTIC_ONLY",
    }


def _cohort_associations(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "route_usable_count": sum(_finite(row.get("fixed_return_pct")) is not None for row in rows),
        "features": {
            feature_id: _feature_association(rows, feature_id)
            for feature_id in FEATURE_IDS
        },
    }


def _reconstruct_state(processed_root: Path) -> tuple[live_v2.OnlinePumpFeatureState, int]:
    if not processed_root.is_dir():
        raise ValueError(f"processed-chunks directory not found: {processed_root}")
    state = live_v2.OnlinePumpFeatureState()
    chunk_dirs = sorted(path for path in processed_root.iterdir() if path.is_dir())
    with patched_sniper_feature_enrichment_v1():
        for chunk_dir in chunk_dirs:
            state.ingest_processed_chunk(chunk_dir)
    return state, len(chunk_dirs)


def run_discovery_v1(
    *,
    run_dir: Path,
    contract_path: Path = DEFAULT_CONTRACT,
    output_path: Path | None = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    route_input_path = run_dir / "route-input-v2.json"
    route_result_path = run_dir / "route-result-v2.json"
    sniper_path = run_dir / "sniper-comparison-v1.json"
    processed_root = run_dir / "processed-chunks"
    for path in (route_input_path, route_result_path, sniper_path, contract_path):
        if not Path(path).is_file():
            raise ValueError(f"required discovery source missing: {path}")

    route_input = _read_json(route_input_path)
    route_result = _read_json(route_result_path)
    sniper = _read_json(sniper_path)
    contract = _read_json(contract_path)
    if route_input.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError("route input did not freeze feature snapshots before provider quotes")
    if route_input.get("contract_hash_sha256") != contract.get("contract_hash_sha256"):
        raise ValueError("route input/contract hash mismatch")
    if route_result.get("contract_hash_sha256") != contract.get("contract_hash_sha256"):
        raise ValueError("route result/contract hash mismatch")

    state, processed_chunk_count = _reconstruct_state(processed_root)
    fixed_rows = _fixed_rows(route_result, float(contract["position"]["notional_usd"]))
    fixed_by_key = {row["episode_key"]: row for row in fixed_rows}
    selected_keys = {
        str(row.get("episode_key") or "")
        for row in ((sniper.get("primary_selector_diagnostics") or {}).get("rows") or [])
        if row.get("selected") is True
    }
    decisions_by_key = {
        str(row.get("episode_key") or ""): row
        for row in route_result.get("decisions") or []
        if isinstance(row, dict)
    }

    analysis_rows: list[dict[str, Any]] = []
    parity_errors: list[str] = []
    complete_episode_count = 0
    reconstructed_count = 0

    for episode in route_input.get("episodes") or []:
        if not isinstance(episode, dict):
            continue
        snapshot = episode.get("feature_snapshot") or {}
        if snapshot.get("complete") is not True:
            continue
        complete_episode_count += 1
        episode_key = str(episode.get("episode_key") or "")
        token_mint = str(episode.get("token_mint") or "")
        anchor_wall_ns = int(snapshot.get("observed_t0_wall_ns") or 0)
        cutoff_wall_ns = int(snapshot.get("decision_cutoff_wall_ns") or 0)
        anchor = state.anchors.get((token_mint, "pump"))
        if not anchor:
            parity_errors.append(f"missing_anchor:{episode_key}")
            continue
        if int(anchor.get("observed_wall_ns") or 0) != anchor_wall_ns:
            parity_errors.append(f"anchor_clock_mismatch:{episode_key}")
            continue
        chain_t0 = int(anchor.get("chain_t0") or 0)
        rows = [
            item
            for item in state.adapted
            if item.token_mint == token_mint
            and item.venue == "pump"
            and anchor_wall_ns <= item.observed_wall_ns <= cutoff_wall_ns
            and chain_t0 <= item.chain_time <= chain_t0 + 5
        ]
        replay = feature_snapshot_with_sniper_v1(rows, anchor_wall_ns=anchor_wall_ns)
        stored = snapshot.get("features") or {}
        checks = {
            "event_count": replay.get("event_count") == stored.get("event_count"),
            "signed_flow_over_event_reserve": _same_number(
                replay.get("signed_flow_over_event_reserve"),
                stored.get("signed_flow_over_event_reserve"),
            ),
            "directional_flow_efficiency": _same_number(
                replay.get("directional_flow_efficiency"),
                stored.get("directional_flow_efficiency"),
            ),
            "unique_buy_wallet_count": replay.get("unique_buy_wallet_count")
            == stored.get("unique_buy_wallet_count"),
        }
        failed_checks = [name for name, passed in checks.items() if not passed]
        if failed_checks:
            parity_errors.append(f"feature_parity:{episode_key}:{','.join(failed_checks)}")
            continue
        reconstructed_count += 1
        features = acceleration_features_v1(
            rows,
            anchor_wall_ns=anchor_wall_ns,
            cutoff_wall_ns=cutoff_wall_ns,
        )
        fixed = fixed_by_key.get(episode_key)
        decision = decisions_by_key.get(episode_key) or {}
        analysis_rows.append(
            {
                "episode_key": episode_key,
                "token_mint": token_mint,
                "baseline_admitted": decision.get("admitted") is True,
                "sniper_selected": episode_key in selected_keys,
                "route_status": decision.get("status"),
                "fixed_return_pct": fixed.get("fixed_return_pct") if fixed else None,
                "features": features,
            }
        )

    if parity_errors:
        raise ValueError(
            "causal reconstruction parity failed; discovery aborted: " + ";".join(parity_errors[:10])
        )

    baseline_rows = [row for row in analysis_rows if row["baseline_admitted"]]
    sniper_rows = [row for row in baseline_rows if row["sniper_selected"]]
    report = {
        "type": "market_first_feature_discovery_report_v1",
        "version": VERSION,
        "classification": PASS,
        "feature_version": FEATURE_VERSION,
        "inference_role": "RETROSPECTIVE_DISCOVERY_DIAGNOSTIC_ONLY",
        "automatic_edge_claim": False,
        "threshold_search_performed": False,
        "selector_changed": False,
        "sniper_v1_changed": False,
        "source_integrity": {
            "run_dir": str(run_dir),
            "processed_chunk_count": processed_chunk_count,
            "route_input_episode_count": len(route_input.get("episodes") or []),
            "complete_episode_count": complete_episode_count,
            "reconstructed_complete_episode_count": reconstructed_count,
            "exact_reconstruction_parity": True,
            "feature_snapshot_frozen_before_provider_quotes": True,
            "route_contract_hash_sha256": contract.get("contract_hash_sha256"),
        },
        "temporal_contract": {
            "window_seconds": 5.0,
            "early_half": "[t0,t0+2.5s)",
            "late_half": "[t0+2.5s,t0+5s]",
            "wall_clock_and_chain_window_replayed": True,
            "published_at_used": False,
            "provider_quote_used_for_features": False,
            "future_outcome_used_for_features": False,
        },
        "feature_definitions": feature_definitions_v1(),
        "liquidity_exitability": liquidity_exitability_discovery_status_v1(),
        "cohorts": {
            "baseline_admitted_count": len(baseline_rows),
            "sniper_selected_count": len(sniper_rows),
            "baseline": _cohort_associations(baseline_rows),
            "sniper_selected": _cohort_associations(sniper_rows),
        },
        "rows": analysis_rows,
        "interpretation": (
            "This report may generate hypotheses only. Correlations and group summaries are descriptive; "
            "they must not be converted into a selector threshold on this sample. Any future policy must "
            "be separately preregistered and evaluated on a fresh causal capture."
        ),
    }
    destination = output_path or (run_dir / "market-first-feature-discovery-v1.json")
    _write_json(Path(destination), report)
    report["artifact"] = str(Path(destination).resolve())
    return report


def _compact(report: dict[str, Any]) -> dict[str, Any]:
    cohorts = report.get("cohorts") or {}
    return {
        "classification": report.get("classification"),
        "inference_role": report.get("inference_role"),
        "source_integrity": report.get("source_integrity"),
        "liquidity_exitability": report.get("liquidity_exitability"),
        "baseline": cohorts.get("baseline"),
        "sniper_selected": cohorts.get("sniper_selected"),
        "artifact": report.get("artifact"),
        "threshold_search_performed": report.get("threshold_search_performed"),
        "selector_changed": report.get("selector_changed"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retrospective diagnostic-only Market-First feature discovery from preserved causal chunks"
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_discovery_v1(
            run_dir=args.run_dir,
            contract_path=args.contract,
            output_path=args.output,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": "FAIL_MARKET_FIRST_FEATURE_DISCOVERY_V1",
                    "error": f"{type(exc).__name__}:{exc}",
                },
                indent=2,
            )
        )
        return 2
    print(json.dumps(_compact(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
