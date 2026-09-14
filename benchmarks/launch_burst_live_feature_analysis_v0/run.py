from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable

from benchmarks.launch_burst_shadow_v0.run import run_shadow_v0


ANALYSIS_VERSION = "launch_burst_live_feature_analysis_v0"
PASS_CLASSIFICATION = "PASS_LAUNCH_BURST_LIVE_FEATURE_ANALYSIS_V0"
FAIL_CLASSIFICATION = "FAIL_LAUNCH_BURST_LIVE_FEATURE_ANALYSIS_V0"
EXPECTED_CAPTURE_VERSION = "launch_burst_live_capture_v2_signal_only"
EXPECTED_CAPTURE_CLASSIFICATION = "PASS_LAUNCH_BURST_LIVE_CAPTURE_V2"
DEFAULT_HORIZONS = (1, 5, 10, 30)


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


def _validate_capture(capture: dict[str, Any]) -> None:
    if capture.get("classification") != EXPECTED_CAPTURE_CLASSIFICATION:
        raise ValueError("capture must be PASS_LAUNCH_BURST_LIVE_CAPTURE_V2")
    if capture.get("version") != EXPECTED_CAPTURE_VERSION:
        raise ValueError("unsupported Launch Burst capture version")

    gates = capture.get("gates") or {}
    required_gates = (
        "operational_shadow_active",
        "duration_elapsed",
        "chunks_bounded",
        "all_chunks_consumed",
        "all_chunks_processed",
        "no_chunk_errors",
        "no_semantic_errors",
        "no_persistence_errors",
        "no_transport_errors",
        "no_reconnects",
        "no_rpc_errors",
        "no_write_errors",
        "research_plane_disabled_by_design",
        "causal_lifecycle_seen",
        "causal_trade_seen",
        "no_fatal_error",
    )
    missing = [name for name in required_gates if gates.get(name) is not True]
    if missing:
        raise ValueError("capture gates not clean: " + ",".join(missing))

    scope = capture.get("scientific_scope") or {}
    if scope.get("feature_research_only") is not True:
        raise ValueError("capture is not feature-research-only")
    if scope.get("economic_edge_evaluated") is not False:
        raise ValueError("capture unexpectedly evaluated economic edge")
    if scope.get("future_outcomes_loaded") is not False:
        raise ValueError("capture unexpectedly loaded future outcomes")
    if scope.get("market_first_research_plane_disabled") is not True:
        raise ValueError("Market-First Research Plane was not disabled")

    chunk_count = int((capture.get("acquisition") or {}).get("chunk_count") or 0)
    report_count = int(capture.get("chunk_report_count") or 0)
    if chunk_count <= 0 or report_count != chunk_count:
        raise ValueError("capture chunk accounting is incomplete")


def _compat_live_report(capture: dict[str, Any]) -> dict[str, Any]:
    acquisition_run_key = str(capture.get("acquisition_run_key") or "").strip()
    if not acquisition_run_key:
        raise ValueError("capture has no acquisition_run_key")

    artifacts = capture.get("artifacts") or {}
    processed_root = artifacts.get("processed_root")
    bootstrap_report = (capture.get("bootstrap") or {}).get("report_path")
    if not isinstance(processed_root, str) or not processed_root.strip():
        raise ValueError("capture processed_root is missing")
    if not isinstance(bootstrap_report, str) or not bootstrap_report.strip():
        raise ValueError("capture bootstrap report is missing")

    discovery_start = int(capture.get("discovery_start_wall_ns") or 0)
    discovery_close = int(capture.get("discovery_close_wall_ns") or 0)
    acquisition_end = int((capture.get("acquisition") or {}).get("ended_wall_ns") or 0)
    if discovery_start <= 0 or discovery_close <= discovery_start:
        raise ValueError("invalid capture discovery bounds")
    if acquisition_end < discovery_close:
        raise ValueError("capture did not span the declared discovery window")

    return {
        "type": "launch_burst_live_feature_analysis_v0_compat_source",
        "run": {
            "status": "CLOSED",
            "acquisition_run_key": acquisition_run_key,
        },
        "valid_live_discovery": True,
        "bootstrap_validated": True,
        "discovery_start_wall_ns": discovery_start,
        "discovery_close_wall_ns": discovery_close,
        "acquisition": {"ended_wall_ns": acquisition_end},
        "artifacts": {"processed_chunks": processed_root},
        "bootstrap": {"report_path": bootstrap_report},
    }


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
    clean: list[float] = []
    for raw in values:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        value = float(raw)
        if math.isfinite(value):
            clean.append(value)
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


def _pct(numerator: int, denominator: int) -> float | None:
    return 100.0 * numerator / denominator if denominator else None


def _feature_value(features: dict[str, Any], name: str) -> Any:
    if name.startswith("time_to_"):
        n = name.removeprefix("time_to_").removesuffix("_events_ms")
        return (features.get("time_to_n_events_ms") or {}).get(n)
    return features.get(name)


def _summarize_shadow(shadow: dict[str, Any], horizons: tuple[int, ...]) -> dict[str, Any]:
    launches = list(shadow.get("launches") or [])
    feature_names = (
        "event_count",
        "buy_count",
        "sell_count",
        "buy_sell_count_imbalance",
        "signed_flow_over_event_reserve",
        "gross_turnover_over_event_reserve",
        "unique_wallet_count",
        "unique_transaction_count",
        "first_trade_delay_ms",
        "time_to_3_events_ms",
        "time_to_5_events_ms",
        "time_to_10_events_ms",
        "reserve_delta_fraction",
    )

    output: dict[str, Any] = {}
    for stratum in ("pump_launch", "pumpswap_liquidity_launch"):
        stratum_rows = [row for row in launches if row.get("stratum") == stratum]
        horizon_rows: dict[str, Any] = {}
        for horizon in horizons:
            key = str(horizon)
            complete = [
                row
                for row in stratum_rows
                if ((row.get("horizons") or {}).get(key) or {}).get("complete") is True
            ]
            features = [
                ((row.get("horizons") or {}).get(key) or {}).get("features") or {}
                for row in complete
            ]
            nonempty = [item for item in features if int(item.get("event_count") or 0) > 0]
            horizon_rows[key] = {
                "anchor_count": len(stratum_rows),
                "complete_count": len(complete),
                "right_censored_count": len(stratum_rows) - len(complete),
                "completion_pct": _pct(len(complete), len(stratum_rows)),
                "nonempty_count": len(nonempty),
                "nonempty_pct_of_complete": _pct(len(nonempty), len(complete)),
                "features": {
                    name: _distribution(_feature_value(item, name) for item in features)
                    for name in feature_names
                },
            }
        output[stratum] = horizon_rows
    return output


def run_analysis(
    *,
    capture_report_path: Path,
    output_path: Path,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    horizons = tuple(sorted(set(int(value) for value in horizons)))
    if not horizons or any(value <= 0 for value in horizons):
        raise ValueError("horizons must contain positive integers")

    capture_report_path = Path(capture_report_path)
    output_path = Path(output_path)
    capture = _read_json(capture_report_path)
    _validate_capture(capture)

    compat_path = output_path.parent / (output_path.stem + ".compat-source.json")
    _write_json(compat_path, _compat_live_report(capture))

    shadow = run_shadow_v0(
        live_report_path=compat_path,
        horizons_seconds=horizons,
        candidate_parity_report=None,
    )
    if shadow.get("classification") != "PASS_LAUNCH_BURST_SHADOW_V0":
        raise RuntimeError("causal shadow analysis did not pass")

    summaries = _summarize_shadow(shadow, horizons)
    result = {
        "type": "launch_burst_live_feature_analysis",
        "version": ANALYSIS_VERSION,
        "classification": PASS_CLASSIFICATION,
        "capture_id": capture.get("capture_id"),
        "source_capture_classification": capture.get("classification"),
        "source_capture_report": str(capture_report_path.resolve()),
        "horizons_seconds": list(horizons),
        "source_integrity": shadow.get("source_integrity"),
        "feature_coverage": shadow.get("feature_coverage"),
        "strata": summaries,
        "launches": shadow.get("launches"),
        "research_contract": {
            "outcome_blind": True,
            "future_outcomes_loaded": False,
            "return_values_reported": False,
            "thresholds_optimized": False,
            "automatic_trade_decision": False,
            "pump_and_pumpswap_separate": True,
            "matched_unit_features_used_when_causally_available": True,
            "right_censoring_preserved": True,
        },
        "economic_coverage": shadow.get("economic_coverage"),
        "artifacts": {
            "compat_source": str(compat_path.resolve()),
            "report": str(output_path.resolve()),
        },
    }
    _write_json(output_path, result)
    return result


def _parse_horizons(raw: str) -> tuple[int, ...]:
    values = tuple(int(item.strip()) for item in raw.split(",") if item.strip())
    if not values:
        raise argparse.ArgumentTypeError("at least one horizon is required")
    if any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError("horizons must be positive")
    return values


def _compact(result: dict[str, Any]) -> dict[str, Any]:
    compact_strata: dict[str, Any] = {}
    for stratum, horizons in (result.get("strata") or {}).items():
        compact_strata[stratum] = {}
        for horizon, summary in horizons.items():
            features = summary.get("features") or {}
            compact_strata[stratum][horizon] = {
                "anchor_count": summary.get("anchor_count"),
                "complete_count": summary.get("complete_count"),
                "right_censored_count": summary.get("right_censored_count"),
                "completion_pct": summary.get("completion_pct"),
                "nonempty_count": summary.get("nonempty_count"),
                "nonempty_pct_of_complete": summary.get("nonempty_pct_of_complete"),
                "event_count_p50": (features.get("event_count") or {}).get("p50"),
                "event_count_p90": (features.get("event_count") or {}).get("p90"),
                "imbalance_p50": (features.get("buy_sell_count_imbalance") or {}).get("p50"),
                "imbalance_p90": (features.get("buy_sell_count_imbalance") or {}).get("p90"),
                "signed_flow_reserve_p50": (features.get("signed_flow_over_event_reserve") or {}).get("p50"),
                "signed_flow_reserve_p90": (features.get("signed_flow_over_event_reserve") or {}).get("p90"),
                "gross_turnover_reserve_p50": (features.get("gross_turnover_over_event_reserve") or {}).get("p50"),
                "gross_turnover_reserve_p90": (features.get("gross_turnover_over_event_reserve") or {}).get("p90"),
                "unique_wallets_p50": (features.get("unique_wallet_count") or {}).get("p50"),
                "unique_wallets_p90": (features.get("unique_wallet_count") or {}).get("p90"),
                "first_trade_delay_ms_p50": (features.get("first_trade_delay_ms") or {}).get("p50"),
                "first_trade_delay_ms_p90": (features.get("first_trade_delay_ms") or {}).get("p90"),
                "time_to_5_ms_p50": (features.get("time_to_5_events_ms") or {}).get("p50"),
                "time_to_5_ms_p90": (features.get("time_to_5_events_ms") or {}).get("p90"),
            }
    return {
        "classification": result.get("classification"),
        "capture_id": result.get("capture_id"),
        "horizons_seconds": result.get("horizons_seconds"),
        "feature_coverage": result.get("feature_coverage"),
        "strata": compact_strata,
        "research_contract": result.get("research_contract"),
        "report": (result.get("artifacts") or {}).get("report"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Outcome-blind Launch Burst live feature analysis v0")
    parser.add_argument("--capture-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--horizons", type=_parse_horizons, default=DEFAULT_HORIZONS)
    args = parser.parse_args()
    try:
        result = run_analysis(
            capture_report_path=args.capture_report,
            output_path=args.output,
            horizons=tuple(args.horizons),
        )
    except Exception as exc:
        print(json.dumps({"classification": FAIL_CLASSIFICATION, "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(_compact(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
