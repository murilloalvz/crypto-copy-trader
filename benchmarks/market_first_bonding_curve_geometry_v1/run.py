from __future__ import annotations

import argparse
import base64
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from src.market_first_bonding_curve_geometry_v1 import (
    FEATURE_IDS,
    SOL_QUOTE_MINT,
    VERSION as FEATURE_VERSION,
    decode_create_geometry_payload_v1,
    decode_trade_geometry_payload_v1,
    feature_definitions_v1,
    geometry_features_v1,
)


VERSION = "market_first_bonding_curve_geometry_benchmark_v1"
PASS = "PASS_MARKET_FIRST_BONDING_CURVE_GEOMETRY_V1"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


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
    value = numerator / math.sqrt(lss * rss)
    return value if math.isfinite(value) else None


def _spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    return _pearson(_average_ranks(left), _average_ranks(right))


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


def _provider_impact(decision: dict[str, Any]) -> float | None:
    quote = decision.get("entry_quote")
    if not isinstance(quote, dict):
        return None
    return _finite(quote.get("provider_price_impact_pct_points"))


def _manifest_index(path: Path) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in _jsonl(path):
        key = str(row.get("event_key") or "")
        if not key:
            continue
        prior = output.get(key)
        if prior is not None and prior != row:
            raise ValueError(f"conflicting target manifest rows for {key}")
        output[key] = row
    return output


def _canonical_index(path: Path) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in _jsonl(path):
        if row.get("type") != "carbon_canonical_event":
            continue
        key = str(row.get("event_key") or "")
        if not key:
            continue
        prior = output.get(key)
        if prior is not None and prior != row:
            raise ValueError(f"conflicting Carbon canonical rows for {key}")
        output[key] = row
    return output


def _load_geometry_rows(processed_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows_by_key: dict[str, dict[str, Any]] = {}
    input_events = 0
    pump_payload_events = 0
    duplicate_replays = 0
    parity_errors: list[str] = []
    decode_errors: list[str] = []
    chunk_count = 0

    for chunk_dir in sorted(path for path in processed_root.iterdir() if path.is_dir()):
        carbon_input = chunk_dir / "carbon-input.jsonl"
        canonical_path = chunk_dir / "carbon-canonical.jsonl"
        manifest_path = chunk_dir / "target-manifest.jsonl"
        if not carbon_input.exists():
            continue
        chunk_count += 1
        manifests = _manifest_index(manifest_path)
        canonical = _canonical_index(canonical_path)
        for input_row in _jsonl(carbon_input):
            if input_row.get("type") != "carbon_decoder_input":
                continue
            input_events += 1
            event_type = str(input_row.get("event_type") or "")
            if event_type not in {"pump_create", "pump_trade"}:
                continue
            pump_payload_events += 1
            event_key = str(input_row.get("event_key") or "")
            manifest = manifests.get(event_key)
            existing = canonical.get(event_key)
            if not event_key or manifest is None or existing is None:
                parity_errors.append(f"missing_source_context:{event_key}")
                continue
            wall_ns = manifest.get("first_received_wall_ns")
            if not isinstance(wall_ns, int) or isinstance(wall_ns, bool) or wall_ns <= 0:
                parity_errors.append(f"invalid_receive_clock:{event_key}")
                continue
            encoded = input_row.get("payload_base64")
            if not isinstance(encoded, str) or not encoded:
                decode_errors.append(f"missing_payload:{event_key}")
                continue
            try:
                payload = base64.b64decode(encoded, validate=True)
                decoded = (
                    decode_create_geometry_payload_v1(payload)
                    if event_type == "pump_create"
                    else decode_trade_geometry_payload_v1(payload)
                )
            except Exception as exc:
                decode_errors.append(f"{event_key}:{type(exc).__name__}:{exc}")
                continue
            if decoded is None:
                decode_errors.append(f"geometry_decoder_none:{event_key}")
                continue
            if existing.get("status") != "decoded":
                parity_errors.append(f"existing_carbon_decode_not_success:{event_key}")
                continue
            if str(existing.get("mint") or "") != str(decoded.get("mint") or ""):
                parity_errors.append(f"mint_parity:{event_key}")
                continue
            if int(existing.get("timestamp") or -1) != int(decoded.get("timestamp") or -2):
                parity_errors.append(f"timestamp_parity:{event_key}")
                continue
            if event_type == "pump_trade":
                side = str(existing.get("side") or "")
                if side != str(decoded.get("side") or ""):
                    parity_errors.append(f"side_parity:{event_key}")
                    continue
                decoded["quote_mint"] = existing.get("quote_mint")
            decoded_row = {
                "event_key": event_key,
                "event_type": event_type,
                "observed_wall_ns": int(wall_ns),
                **decoded,
            }
            prior = rows_by_key.get(event_key)
            if prior is not None:
                if prior != decoded_row:
                    parity_errors.append(f"conflicting_replay:{event_key}")
                else:
                    duplicate_replays += 1
                continue
            rows_by_key[event_key] = decoded_row

    if decode_errors:
        raise ValueError("geometry payload decode failed: " + ";".join(decode_errors[:10]))
    if parity_errors:
        raise ValueError("geometry source parity failed: " + ";".join(parity_errors[:10]))
    return list(rows_by_key.values()), {
        "processed_chunk_count": chunk_count,
        "carbon_input_event_count": input_events,
        "pump_geometry_payload_event_count": pump_payload_events,
        "unique_pump_geometry_event_count": len(rows_by_key),
        "duplicate_replay_count": duplicate_replays,
        "existing_carbon_identity_parity": True,
        "geometry_payload_decode_failures": 0,
    }


def _feature_summary(rows: list[dict[str, Any]], feature_id: str) -> dict[str, Any]:
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

    def stats(values: list[float]) -> dict[str, Any]:
        return {
            "count": len(values),
            "mean": _mean(values),
            "median": median(values) if values else None,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
        }

    return {
        "available_count": len(available),
        "missing_count": len(rows) - len(available),
        "entry_groups": {name: stats(values) for name, values in sorted(groups.items())},
        "spearman_with_entry_usable": (
            _spearman([x for x, _ in usable_pairs], [y for _, y in usable_pairs])
            if usable_pairs else None
        ),
        "provider_price_impact_pair_count": len(impact_pairs),
        "spearman_with_postdecision_provider_price_impact": (
            _spearman([x for x, _ in impact_pairs], [y for _, y in impact_pairs])
            if impact_pairs else None
        ),
        "provider_price_impact_role": "POSTDECISION_EVALUATION_LABEL_ONLY_NOT_FEATURE",
        "threshold_search_performed": False,
        "inference_role": "DISCOVERY_DIAGNOSTIC_ONLY",
    }


def _cohort(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "entry_group_counts": dict(sorted(Counter(str(row["entry_group"]) for row in rows).items())),
        "geometry_status_counts": dict(sorted(Counter(str(row["geometry_status"]) for row in rows).items())),
        "probe_capacity_bound_counts": {
            label: sum(1 for row in rows if (row.get("probe_capacity_bound") or {}).get(label) is True)
            for label in ("0_01_sol", "0_10_sol", "0_50_sol")
        },
        "features": {feature_id: _feature_summary(rows, feature_id) for feature_id in FEATURE_IDS},
    }


def run_geometry_v1(*, run_dir: Path, output_path: Path | None = None) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    route_input_path = run_dir / "route-input-v2.json"
    route_result_path = run_dir / "route-result-v2.json"
    sniper_path = run_dir / "sniper-comparison-v1.json"
    processed_root = run_dir / "processed-chunks"
    for path in (route_input_path, route_result_path, sniper_path):
        if not path.is_file():
            raise ValueError(f"required geometry source missing: {path}")
    if not processed_root.is_dir():
        raise ValueError(f"processed-chunks directory not found: {processed_root}")

    route_input = _read_json(route_input_path)
    route_result = _read_json(route_result_path)
    sniper = _read_json(sniper_path)
    if route_input.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError("route input did not freeze feature snapshots before provider quotes")
    contract_hash = str(route_input.get("contract_hash_sha256") or "")
    if not contract_hash or route_result.get("contract_hash_sha256") != contract_hash:
        raise ValueError("route input/result contract hash mismatch")

    geometry_rows, geometry_integrity = _load_geometry_rows(processed_root)
    creates_by_mint: dict[str, list[dict[str, Any]]] = defaultdict(list)
    trades_by_mint: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in geometry_rows:
        target = creates_by_mint if row["event_type"] == "pump_create" else trades_by_mint
        target[str(row["mint"])].append(row)
    for rows in (*creates_by_mint.values(), *trades_by_mint.values()):
        rows.sort(key=lambda row: (int(row["timestamp"]), int(row["observed_wall_ns"]), str(row["event_key"])))

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
        if cutoff_wall_ns != anchor_wall_ns + 5_000_000_000:
            parity_errors.append(f"window_clock:{episode_key}")
            continue

        create_candidates = [
            row for row in creates_by_mint.get(token_mint, [])
            if int(row["observed_wall_ns"]) == anchor_wall_ns
        ]
        if len(create_candidates) != 1:
            parity_errors.append(f"create_anchor_count:{episode_key}:{len(create_candidates)}")
            continue
        initial = create_candidates[0]
        chain_t0 = int(initial["timestamp"])
        trade_candidates = [
            row for row in trades_by_mint.get(token_mint, [])
            if anchor_wall_ns <= int(row["observed_wall_ns"]) <= cutoff_wall_ns
            and chain_t0 <= int(row["timestamp"]) <= chain_t0 + 5
        ]
        stored_event_count = (snapshot.get("features") or {}).get("event_count")
        if stored_event_count != len(trade_candidates):
            parity_errors.append(f"stored_event_count:{episode_key}:{stored_event_count}:{len(trade_candidates)}")
            continue
        if not trade_candidates:
            geometry = {
                "status": "INSUFFICIENT_EVIDENCE_NO_TRADE_STATE_AT_CUTOFF",
                "quote_mint": None,
                "features": {feature_id: None for feature_id in FEATURE_IDS},
                "probe_capacity_bound": {},
            }
        else:
            cutoff_state = max(
                trade_candidates,
                key=lambda row: (int(row["timestamp"]), int(row["observed_wall_ns"]), str(row["event_key"])),
            )
            quote_mints = {str(row.get("quote_mint") or "") for row in trade_candidates}
            if len(quote_mints) != 1:
                geometry = {
                    "status": "INSUFFICIENT_EVIDENCE_QUOTE_MINT_CONFLICT",
                    "quote_mint": None,
                    "features": {feature_id: None for feature_id in FEATURE_IDS},
                    "probe_capacity_bound": {},
                }
            else:
                geometry = geometry_features_v1(
                    initial_state=initial,
                    cutoff_state=cutoff_state,
                    quote_mint=next(iter(quote_mints)),
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
                "entry_usable": _entry_group(status) == "ENTRY_USABLE",
                "provider_price_impact_pct_points": _provider_impact(decision),
                "provider_price_impact_is_postdecision_outcome_only": True,
                "quote_mint": geometry.get("quote_mint"),
                "geometry_status": geometry.get("status"),
                "features": geometry.get("features"),
                "probe_capacity_bound": geometry.get("probe_capacity_bound"),
            }
        )

    if parity_errors:
        raise ValueError("episode geometry parity failed: " + ";".join(parity_errors[:10]))

    baseline_rows = [
        row for row in analysis_rows
        if row["baseline_admitted"] and row.get("quote_mint") == SOL_QUOTE_MINT
    ]
    sniper_rows = [row for row in baseline_rows if row["sniper_selected"]]
    report = {
        "type": "market_first_bonding_curve_geometry_report_v1",
        "version": VERSION,
        "classification": PASS,
        "feature_version": FEATURE_VERSION,
        "inference_role": "RETROSPECTIVE_DISCOVERY_DIAGNOSTIC_ONLY",
        "scope": "PUMP_DEFAULT_SOL_QUOTE_ONLY",
        "automatic_edge_claim": False,
        "threshold_search_performed": False,
        "selector_changed": False,
        "sniper_v1_changed": False,
        "provider_execution_used_as_feature": False,
        "source_integrity": {
            "run_dir": str(run_dir),
            "route_input_episode_count": len(route_input.get("episodes") or []),
            "complete_episode_count": complete_episode_count,
            "reconstructed_complete_episode_count": len(analysis_rows),
            "feature_snapshot_frozen_before_provider_quotes": True,
            "stored_event_count_parity": True,
            "route_contract_hash_sha256": contract_hash,
            **geometry_integrity,
        },
        "causal_contract": {
            "window_seconds": 5,
            "geometry_source": "preserved_carbon_input_pump_create_and_trade_payload_bytes",
            "provider_quote_used_for_features": False,
            "provider_route_results_used_only_as_postdecision_evaluation_labels": True,
            "future_return_used": False,
            "published_at_used": False,
            "probe_policy": "fixed_mechanical_SOL_amounts_declared_before_geometry_outcome_analysis_no_threshold_search",
            "probe_fee_model": "curve_only_no_protocol_or_provider_fee_emulation",
        },
        "feature_definitions": feature_definitions_v1(),
        "cohorts": {
            "baseline_sol_quote": _cohort(baseline_rows),
            "sniper_sol_quote": _cohort(sniper_rows),
        },
        "rows": analysis_rows,
        "interpretation": (
            "Pump bonding-curve geometry is reconstructed only from event payload bytes already observed by the frozen 5s cutoff. "
            "Provider route status and price impact are evaluation labels only. Fixed SOL probes characterize curve shape and are "
            "not route-contract notional estimates. No threshold or selector is searched on this sample."
        ),
    }
    destination = output_path or (run_dir / "market-first-bonding-curve-geometry-v1.json")
    _write_json(Path(destination), report)
    report["artifact"] = str(Path(destination).resolve())
    return report


def _compact(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "classification": report.get("classification"),
        "scope": report.get("scope"),
        "source_integrity": report.get("source_integrity"),
        "causal_contract": report.get("causal_contract"),
        "baseline_sol_quote": (report.get("cohorts") or {}).get("baseline_sol_quote"),
        "sniper_sol_quote": (report.get("cohorts") or {}).get("sniper_sol_quote"),
        "threshold_search_performed": report.get("threshold_search_performed"),
        "selector_changed": report.get("selector_changed"),
        "artifact": report.get("artifact"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnostic-only Pump bonding-curve geometry discovery")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_geometry_v1(run_dir=args.run_dir, output_path=args.output)
    except Exception as exc:
        print(json.dumps({"classification": "FAIL_MARKET_FIRST_BONDING_CURVE_GEOMETRY_V1", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(_compact(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
