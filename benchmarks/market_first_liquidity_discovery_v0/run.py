from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from benchmarks.launch_burst_prospective_route_paper_v2 import live as live_v2
from src.market_first_liquidity_discovery_v0 import (
    FEATURE_IDS,
    VERSION as FEATURE_VERSION,
    feature_definitions_v0,
    liquidity_features_v0,
)


VERSION = "market_first_liquidity_discovery_benchmark_v0"
PASS = "PASS_MARKET_FIRST_LIQUIDITY_DISCOVERY_V0"
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
    out = float(value)
    return out if math.isfinite(out) else None


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
    out = numerator / math.sqrt(lss * rss)
    return out if math.isfinite(out) else None


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    return _pearson(_average_ranks(left), _average_ranks(right))


def _text(row: dict[str, Any], name: str) -> str | None:
    value = row.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _nonnegative_int(row: dict[str, Any], name: str) -> int | None:
    value = row.get(name)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _entry_group(status: str) -> str:
    if status == "ROUTE_CLOSED" or status.startswith("UNROUTABLE_EXIT"):
        return "ENTRY_USABLE"
    if status == "ENTRY_UNAVAILABLE":
        return "ENTRY_UNAVAILABLE"
    if status.startswith("ENTRY_REJECTED:PRICE_IMPACT_EXCEEDS_LIMIT"):
        return "ENTRY_PRICE_IMPACT_REJECTED"
    if status.startswith("ENTRY_REJECTED:"):
        return "ENTRY_OTHER_REJECTED"
    return "OTHER"


def _entry_usable(status: str) -> bool:
    return _entry_group(status) == "ENTRY_USABLE"


def _provider_impact(decision: dict[str, Any]) -> float | None:
    quote = decision.get("entry_quote")
    if not isinstance(quote, dict):
        return None
    return _finite(quote.get("provider_price_impact_pct_points"))


def _load_causal_market_rows(processed_root: Path) -> tuple[dict[str, list[dict[str, Any]]], int, list[str]]:
    by_token: dict[str, list[dict[str, Any]]] = defaultdict(list)
    errors: list[str] = []
    chunk_count = 0
    for chunk_dir in sorted(path for path in processed_root.iterdir() if path.is_dir()):
        carbon = chunk_dir / "carbon-canonical.jsonl"
        manifest = chunk_dir / "target-manifest.jsonl"
        if not carbon.exists():
            continue
        chunk_count += 1
        paired, pairing_errors = live_v2._paired_rows(carbon, manifest)
        errors.extend(pairing_errors)
        for row, manifest_row in paired:
            if row.get("status") != "decoded" or row.get("event_type") != "pump_trade":
                continue
            mint = _text(row, "mint")
            wall_ns = manifest_row.get("first_received_wall_ns")
            chain_time = _nonnegative_int(row, "timestamp")
            if mint is None or not isinstance(wall_ns, int) or isinstance(wall_ns, bool) or wall_ns <= 0 or chain_time is None:
                errors.append(f"invalid_pump_liquidity_row:{row.get('event_key')}")
                continue
            by_token[mint].append(
                {
                    "event_key": str(row.get("event_key") or ""),
                    "token_mint": mint,
                    "observed_wall_ns": wall_ns,
                    "chain_time": chain_time,
                    "quote_mint": _text(row, "quote_mint"),
                    "real_quote_reserves_raw": _nonnegative_int(row, "real_quote_reserves_raw"),
                    "virtual_quote_reserves_raw": _nonnegative_int(row, "virtual_quote_reserves_raw"),
                }
            )
    for rows in by_token.values():
        rows.sort(key=lambda item: (int(item["observed_wall_ns"]), item["event_key"]))
    return by_token, chunk_count, errors


def _reconstruct_state(processed_root: Path) -> live_v2.OnlinePumpFeatureState:
    state = live_v2.OnlinePumpFeatureState()
    for chunk_dir in sorted(path for path in processed_root.iterdir() if path.is_dir()):
        if (chunk_dir / "carbon-canonical.jsonl").exists():
            state.ingest_processed_chunk(chunk_dir)
    return state


def _feature_summary(rows: list[dict[str, Any]], feature_id: str, *, raw_feature: bool) -> dict[str, Any]:
    available = [
        (float(value), row)
        for row in rows
        if (value := _finite((row.get("features") or {}).get(feature_id))) is not None
    ]
    groups: dict[str, list[float]] = defaultdict(list)
    for value, row in available:
        groups[str(row.get("entry_group") or "OTHER")].append(value)

    usable_pairs = [(value, 1.0 if row.get("entry_usable") else 0.0) for value, row in available]
    impact_pairs = [
        (value, float(impact))
        for value, row in available
        if (impact := _finite(row.get("provider_price_impact_pct_points"))) is not None
    ]
    quote_mints = sorted({str(row.get("quote_mint")) for _, row in available if row.get("quote_mint")})
    globally_comparable = not raw_feature or len(quote_mints) <= 1

    def group_stats(values: list[float]) -> dict[str, Any]:
        return {
            "count": len(values),
            "mean": _mean(values),
            "median": median(values) if values else None,
        }

    return {
        "available_count": len(available),
        "missing_count": len(rows) - len(available),
        "quote_mints": quote_mints,
        "globally_comparable": globally_comparable,
        "entry_groups": {name: group_stats(values) for name, values in sorted(groups.items())},
        "spearman_with_entry_usable": (
            _spearman([x for x, _ in usable_pairs], [y for _, y in usable_pairs])
            if globally_comparable else None
        ),
        "provider_price_impact_pair_count": len(impact_pairs),
        "spearman_with_postdecision_provider_price_impact": (
            _spearman([x for x, _ in impact_pairs], [y for _, y in impact_pairs])
            if globally_comparable else None
        ),
        "provider_price_impact_role": "POSTDECISION_EVALUATION_LABEL_ONLY_NOT_FEATURE",
        "threshold_search_performed": False,
        "inference_role": "DISCOVERY_DIAGNOSTIC_ONLY",
    }


def _cohort(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "entry_group_counts": dict(sorted(Counter(str(row["entry_group"]) for row in rows).items())),
        "quote_mint_counts": dict(sorted(Counter(str(row.get("quote_mint") or "MISSING") for row in rows).items())),
        "features": {
            feature_id: _feature_summary(
                rows,
                feature_id,
                raw_feature=(feature_id == "mf_pump_real_quote_reserve_raw_at_cutoff"),
            )
            for feature_id in FEATURE_IDS
        },
    }


def run_discovery_v0(*, run_dir: Path, contract_path: Path = DEFAULT_CONTRACT, output_path: Path | None = None) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    route_input_path = run_dir / "route-input-v2.json"
    route_result_path = run_dir / "route-result-v2.json"
    sniper_path = run_dir / "sniper-comparison-v1.json"
    processed_root = run_dir / "processed-chunks"
    for path in (route_input_path, route_result_path, sniper_path, contract_path):
        if not Path(path).is_file():
            raise ValueError(f"required liquidity discovery source missing: {path}")
    if not processed_root.is_dir():
        raise ValueError(f"processed-chunks directory not found: {processed_root}")

    route_input = _read_json(route_input_path)
    route_result = _read_json(route_result_path)
    sniper = _read_json(sniper_path)
    contract = _read_json(contract_path)
    contract_hash = str(contract.get("contract_hash_sha256") or "")
    if route_input.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError("route input did not freeze feature snapshots before provider quotes")
    if route_input.get("contract_hash_sha256") != contract_hash or route_result.get("contract_hash_sha256") != contract_hash:
        raise ValueError("liquidity discovery source/contract hash mismatch")

    state = _reconstruct_state(processed_root)
    causal_rows_by_token, chunk_count, row_errors = _load_causal_market_rows(processed_root)
    if row_errors:
        raise ValueError("causal market-row reconstruction failed: " + ";".join(row_errors[:10]))

    decisions = {
        str(row.get("episode_key") or ""): row
        for row in route_result.get("decisions") or []
        if isinstance(row, dict)
    }
    selected_keys = {
        str(row.get("episode_key") or "")
        for row in ((sniper.get("primary_selector_diagnostics") or {}).get("rows") or [])
        if isinstance(row, dict) and row.get("selected") is True
    }

    analysis_rows: list[dict[str, Any]] = []
    parity_errors: list[str] = []
    complete_episode_count = 0

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
        if anchor is None or int(anchor.get("observed_wall_ns") or 0) != anchor_wall_ns:
            parity_errors.append(f"anchor_mismatch:{episode_key}")
            continue
        chain_t0 = int(anchor.get("chain_t0") or 0)

        adapted_rows = [
            item
            for item in state.adapted
            if item.token_mint == token_mint
            and item.venue == "pump"
            and anchor_wall_ns <= item.observed_wall_ns <= cutoff_wall_ns
            and chain_t0 <= item.chain_time <= chain_t0 + 5
        ]
        direct_rows = [
            row
            for row in causal_rows_by_token.get(token_mint, [])
            if anchor_wall_ns <= int(row["observed_wall_ns"]) <= cutoff_wall_ns
            and chain_t0 <= int(row["chain_time"]) <= chain_t0 + 5
        ]
        adapted_keys = {str(item.event_key) for item in adapted_rows}
        direct_keys = {str(row["event_key"]) for row in direct_rows}
        if adapted_keys != direct_keys:
            parity_errors.append(f"event_key_parity:{episode_key}")
            continue
        stored_event_count = (snapshot.get("features") or {}).get("event_count")
        if stored_event_count != len(adapted_rows):
            parity_errors.append(f"stored_event_count_parity:{episode_key}")
            continue

        liquidity = liquidity_features_v0(
            direct_rows,
            anchor_wall_ns=anchor_wall_ns,
            cutoff_wall_ns=cutoff_wall_ns,
        )
        decision = decisions.get(episode_key) or {}
        status = str(decision.get("status") or "UNKNOWN")
        analysis_rows.append(
            {
                "episode_key": episode_key,
                "token_mint": token_mint,
                "baseline_admitted": decision.get("admitted") is True,
                "sniper_selected": episode_key in selected_keys,
                "route_status": status,
                "entry_group": _entry_group(status),
                "entry_usable": _entry_usable(status),
                "provider_price_impact_pct_points": _provider_impact(decision),
                "provider_price_impact_is_postdecision_outcome_only": True,
                "quote_mint": liquidity.get("quote_mint"),
                "liquidity_feature_status": liquidity.get("status"),
                "features": liquidity.get("features"),
            }
        )

    if parity_errors:
        raise ValueError("causal liquidity reconstruction parity failed: " + ";".join(parity_errors[:10]))

    baseline_rows = [row for row in analysis_rows if row["baseline_admitted"]]
    sniper_rows = [row for row in baseline_rows if row["sniper_selected"]]
    report = {
        "type": "market_first_liquidity_discovery_report_v0",
        "version": VERSION,
        "classification": PASS,
        "feature_version": FEATURE_VERSION,
        "inference_role": "RETROSPECTIVE_DISCOVERY_DIAGNOSTIC_ONLY",
        "automatic_edge_claim": False,
        "threshold_search_performed": False,
        "selector_changed": False,
        "sniper_v1_changed": False,
        "provider_execution_used_as_feature": False,
        "source_integrity": {
            "run_dir": str(run_dir),
            "processed_chunk_count": chunk_count,
            "route_input_episode_count": len(route_input.get("episodes") or []),
            "complete_episode_count": complete_episode_count,
            "reconstructed_complete_episode_count": len(analysis_rows),
            "exact_event_key_parity": True,
            "exact_stored_event_count_parity": True,
            "feature_snapshot_frozen_before_provider_quotes": True,
            "route_contract_hash_sha256": contract_hash,
        },
        "causal_contract": {
            "window_seconds": 5,
            "market_features_from_processed_carbon_trade_events_only": True,
            "published_at_used": False,
            "provider_quote_used_for_features": False,
            "future_outcome_used_for_features": False,
            "provider_route_results_used_only_as_postdecision_evaluation_labels": True,
        },
        "feature_definitions": feature_definitions_v0(),
        "cohorts": {
            "baseline": _cohort(baseline_rows),
            "sniper_selected": _cohort(sniper_rows),
        },
        "rows": analysis_rows,
        "interpretation": (
            "This report tests whether event-native Pump reserve state is associated with later route feasibility. "
            "Provider route status and price impact are outcomes only. No threshold is searched or promoted; any "
            "future selector must be separately preregistered before a fresh causal capture."
        ),
    }
    destination = output_path or (run_dir / "market-first-liquidity-discovery-v0.json")
    _write_json(Path(destination), report)
    report["artifact"] = str(Path(destination).resolve())
    return report


def _compact(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "classification": report.get("classification"),
        "inference_role": report.get("inference_role"),
        "source_integrity": report.get("source_integrity"),
        "causal_contract": report.get("causal_contract"),
        "baseline": (report.get("cohorts") or {}).get("baseline"),
        "sniper_selected": (report.get("cohorts") or {}).get("sniper_selected"),
        "artifact": report.get("artifact"),
        "threshold_search_performed": report.get("threshold_search_performed"),
        "selector_changed": report.get("selector_changed"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnostic-only Market-First Pump reserve liquidity discovery")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_discovery_v0(
            run_dir=args.run_dir,
            contract_path=args.contract,
            output_path=args.output,
        )
    except Exception as exc:
        print(json.dumps({"classification": "FAIL_MARKET_FIRST_LIQUIDITY_DISCOVERY_V0", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(_compact(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
