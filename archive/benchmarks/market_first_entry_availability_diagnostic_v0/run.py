from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import median
from typing import Any


VERSION = "market_first_entry_availability_diagnostic_v0"
PASS = "PASS_MARKET_FIRST_ENTRY_AVAILABILITY_DIAGNOSTIC_V0"


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


def _status_family(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value:
        return "COLLECTION_ENTRY_STATUS_MISSING"
    if value == "AVAILABLE_ASSEMBLED":
        return "AVAILABLE_ASSEMBLED"
    if value == "ROUTE_ONLY_UNEXPECTED":
        return "ROUTE_ONLY_UNEXPECTED"
    if value == "ENTRY_WINDOW_MISSED_BY_PROCESSING":
        return "ENTRY_WINDOW_MISSED_BY_PROCESSING"
    if not value.startswith("ERROR:"):
        return "OTHER_COLLECTION_STATUS"

    parts = value.split(":", 2)
    error_class = parts[1] if len(parts) > 1 else "UNKNOWN"
    detail = parts[2].lower() if len(parts) > 2 else ""
    if error_class == "SolanaRPCError":
        return "SOLANA_RPC_ERROR_BEFORE_PROVIDER_ROUTE"
    if error_class == "JupiterOrderError":
        if "429" in detail or "rate limit" in detail or "too many request" in detail:
            return "JUPITER_RATE_LIMIT"
        if "timeout" in detail or "timed out" in detail:
            return "JUPITER_TIMEOUT"
        if (
            "no route" in detail
            or "route not found" in detail
            or "could not find route" in detail
            or "not tradable" in detail
            or "not found" in detail
        ):
            return "JUPITER_NO_ROUTE_OR_NOT_TRADABLE"
        return "JUPITER_ORDER_ERROR_OTHER"
    if error_class in {"ValueError", "TypeError"}:
        return f"LOCAL_NORMALIZATION_{error_class.upper()}"
    return f"OTHER_ERROR_CLASS:{error_class}"


def _timing_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "min": None, "max": None}
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "median": median(values),
        "min": min(values),
        "max": max(values),
    }


def _cohort(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_entry_group: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        by_entry_group[str(row["entry_group"])][str(row["collection_status_family"])] += 1
    return {
        "count": len(rows),
        "route_entry_group_counts": dict(sorted(Counter(str(row["entry_group"]) for row in rows).items())),
        "collection_status_family_counts": dict(sorted(Counter(str(row["collection_status_family"]) for row in rows).items())),
        "collection_status_by_route_entry_group": {
            group: dict(sorted(counter.items())) for group, counter in sorted(by_entry_group.items())
        },
        "provider_calls_started_true": sum(1 for row in rows if row.get("provider_calls_started") is True),
        "provider_calls_started_false": sum(1 for row in rows if row.get("provider_calls_started") is False),
        "provider_start_delay_after_cutoff_ms": _timing_stats([
            float(row["provider_start_delay_after_cutoff_ms"])
            for row in rows
            if row.get("provider_start_delay_after_cutoff_ms") is not None
        ]),
        "provider_start_delay_after_ready_ms": _timing_stats([
            float(row["provider_start_delay_after_ready_ms"])
            for row in rows
            if row.get("provider_start_delay_after_ready_ms") is not None
        ]),
    }


def run_diagnostic_v0(*, run_dir: Path, output_path: Path | None = None) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    route_input_path = run_dir / "route-input-v2.json"
    route_result_path = run_dir / "route-result-v2.json"
    sniper_path = run_dir / "sniper-comparison-v1.json"
    for path in (route_input_path, route_result_path, sniper_path):
        if not path.is_file():
            raise ValueError(f"required availability source missing: {path}")

    route_input = _read_json(route_input_path)
    route_result = _read_json(route_result_path)
    sniper = _read_json(sniper_path)
    if route_input.get("feature_snapshot_frozen_before_provider_quotes") is not True:
        raise ValueError("route input did not freeze snapshots before provider quotes")
    contract_hash = str(route_input.get("contract_hash_sha256") or "")
    if not contract_hash or route_result.get("contract_hash_sha256") != contract_hash:
        raise ValueError("route input/result contract hash mismatch")

    episodes = {
        str(row.get("episode_key") or ""): row
        for row in route_input.get("episodes") or []
        if isinstance(row, dict)
    }
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
    if set(decisions) - set(episodes):
        raise ValueError("route result contains decisions absent from route input")

    rows: list[dict[str, Any]] = []
    for episode_key, decision in decisions.items():
        episode = episodes[episode_key]
        snapshot = episode.get("feature_snapshot") or {}
        collection = episode.get("collection") or {}
        if not isinstance(collection, dict):
            collection = {}
        status = str(decision.get("status") or "UNKNOWN")
        cutoff_ns = snapshot.get("decision_cutoff_wall_ns")
        provider_start_ns = collection.get("entry_provider_started_wall_ns")
        entry_ready_at = collection.get("entry_ready_at")
        delay_after_cutoff_ms = None
        delay_after_ready_ms = None
        if (
            isinstance(cutoff_ns, int) and not isinstance(cutoff_ns, bool)
            and isinstance(provider_start_ns, int) and not isinstance(provider_start_ns, bool)
        ):
            delay_after_cutoff_ms = (provider_start_ns - cutoff_ns) / 1_000_000.0
        if (
            isinstance(provider_start_ns, int) and not isinstance(provider_start_ns, bool)
            and isinstance(entry_ready_at, int) and not isinstance(entry_ready_at, bool)
        ):
            delay_after_ready_ms = provider_start_ns / 1_000_000.0 - entry_ready_at * 1_000.0
        entry_status = collection.get("entry_status")
        rows.append(
            {
                "episode_key": episode_key,
                "token_mint": episode.get("token_mint"),
                "baseline_admitted": decision.get("admitted") is True,
                "sniper_selected": episode_key in selected_keys,
                "route_status": status,
                "entry_group": _entry_group(status),
                "collection_entry_status": entry_status,
                "collection_status_family": _status_family(entry_status),
                "provider_calls_started": collection.get("provider_calls_started"),
                "provider_start_delay_after_cutoff_ms": delay_after_cutoff_ms,
                "provider_start_delay_after_ready_ms": delay_after_ready_ms,
            }
        )

    baseline = [row for row in rows if row["baseline_admitted"]]
    sniper_rows = [row for row in baseline if row["sniper_selected"]]
    unavailable_baseline = [row for row in baseline if row["entry_group"] == "ENTRY_UNAVAILABLE"]
    unavailable_sniper = [row for row in sniper_rows if row["entry_group"] == "ENTRY_UNAVAILABLE"]
    report = {
        "type": "market_first_entry_availability_diagnostic_report_v0",
        "version": VERSION,
        "classification": PASS,
        "inference_role": "SYSTEMS_EXECUTION_ROOT_CAUSE_DIAGNOSTIC_ONLY",
        "selector_changed": False,
        "sniper_v1_changed": False,
        "economic_contract_changed": False,
        "provider_collection_metadata_used_as_selector_feature": False,
        "source_integrity": {
            "run_dir": str(run_dir),
            "route_input_episode_count": len(episodes),
            "route_result_decision_count": len(decisions),
            "decision_episode_key_subset_exact": True,
            "feature_snapshot_frozen_before_provider_quotes": True,
            "route_contract_hash_sha256": contract_hash,
        },
        "cohorts": {
            "baseline": _cohort(baseline),
            "sniper_selected": _cohort(sniper_rows),
            "baseline_entry_unavailable": _cohort(unavailable_baseline),
            "sniper_entry_unavailable": _cohort(unavailable_sniper),
        },
        "rows": rows,
        "interpretation": (
            "This report decomposes route-paper entry unavailability using collection-time provider/RPC/process metadata. "
            "Those fields are execution diagnostics only and are forbidden as causal Market-First selector evidence."
        ),
    }
    destination = output_path or (run_dir / "market-first-entry-availability-diagnostic-v0.json")
    _write_json(Path(destination), report)
    report["artifact"] = str(Path(destination).resolve())
    return report


def _compact(report: dict[str, Any]) -> dict[str, Any]:
    cohorts = report.get("cohorts") or {}
    return {
        "classification": report.get("classification"),
        "source_integrity": report.get("source_integrity"),
        "baseline": cohorts.get("baseline"),
        "sniper_selected": cohorts.get("sniper_selected"),
        "baseline_entry_unavailable": cohorts.get("baseline_entry_unavailable"),
        "sniper_entry_unavailable": cohorts.get("sniper_entry_unavailable"),
        "artifact": report.get("artifact"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Decompose Launch Burst ENTRY_UNAVAILABLE causes")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    try:
        report = run_diagnostic_v0(run_dir=args.run_dir, output_path=args.output)
    except Exception as exc:
        print(json.dumps({"classification": "FAIL_MARKET_FIRST_ENTRY_AVAILABILITY_DIAGNOSTIC_V0", "error": f"{type(exc).__name__}:{exc}"}, indent=2))
        return 2
    print(json.dumps(_compact(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
