from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmarks.market_first_live_discovery_v0.contracts import load_bootstrap_evidence_v0


SOURCE_ADMISSIBILITY_VERSION = "launch_burst_source_admissibility_v0"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def resolve_declared(report_path: Path, declared: object) -> Path:
    if not isinstance(declared, str) or not declared.strip():
        raise ValueError("declared artifact path is missing")
    candidate = Path(declared)
    if candidate.exists():
        return candidate
    report_path = Path(report_path)
    sibling = report_path.parent / candidate.name
    if sibling.exists():
        return sibling
    for parent in report_path.parents:
        joined = parent / candidate
        if joined.exists():
            return joined
    raise ValueError(f"declared artifact path not found: {declared}")


def evaluate_burst_source(report_path: Path) -> dict[str, Any]:
    path = Path(report_path)
    report = _read_json(path)
    run = report.get("run") or {}
    acquisition = report.get("acquisition") or {}
    counters = acquisition.get("counters") or {}
    pipeline = report.get("pipeline") or {}
    artifacts = report.get("artifacts") or {}

    discovery_start = int(report.get("discovery_start_wall_ns") or 0)
    discovery_close = int(report.get("discovery_close_wall_ns") or 0)
    acquisition_end = int(acquisition.get("ended_wall_ns") or 0)
    acquired_chunks = int(acquisition.get("chunk_count") or 0)
    processed_chunks = int(pipeline.get("chunks_processed") or 0)

    processed_root: Path | None = None
    bootstrap_report: Path | None = None
    bootstrap_contract_ok = False
    resolution_errors: list[str] = []

    try:
        processed_root = resolve_declared(path, artifacts.get("processed_chunks"))
    except Exception as exc:
        resolution_errors.append(f"processed_chunks:{type(exc).__name__}:{exc}")

    try:
        bootstrap_report = resolve_declared(path, (report.get("bootstrap") or {}).get("report_path"))
        load_bootstrap_evidence_v0(bootstrap_report)
        bootstrap_contract_ok = True
    except Exception as exc:
        resolution_errors.append(f"bootstrap:{type(exc).__name__}:{exc}")

    finalized_status = str(run.get("status") or "") in {"CLOSED", "INTERRUPTED"}
    no_transport_gap = (
        int(counters.get("transport_errors") or 0) == 0
        and int(counters.get("reconnects") or 0) == 0
        and acquisition.get("stop_reason") == "duration_elapsed"
    )

    gates = {
        "market_first_live_report_shape": report.get("type") == "market_first_live_discovery",
        "source_run_finalized_not_active": finalized_status,
        "bootstrap_validated_at_acquisition": report.get("bootstrap_validated") is True,
        "bootstrap_contract_reloads": bootstrap_contract_ok,
        "valid_discovery_bounds": discovery_start > 0 and discovery_close > discovery_start,
        "acquisition_spanned_discovery_window": acquisition_end >= discovery_close > 0,
        "no_observed_transport_gap": no_transport_gap,
        "all_trace_chunks_processed": acquired_chunks > 0 and acquired_chunks == processed_chunks,
        "processed_chunk_directory_present": processed_root is not None and processed_root.is_dir(),
        "chunk_processing_semantics_healthy": not bool(pipeline.get("chunk_errors")) and not bool(pipeline.get("semantic_errors")),
        "clean_shutdown": report.get("clean_shutdown") is True,
    }
    admissible = bool(gates) and all(gates.values())

    ignored_market_first_fields = {
        "valid_live_discovery": report.get("valid_live_discovery"),
        "classification": report.get("classification"),
        "research_errors": list(pipeline.get("research_errors") or []),
        "persistence_errors": list(pipeline.get("persistence_errors") or []),
        "kernel_trade_events_ingested": pipeline.get("kernel_trade_events_ingested"),
    }

    return {
        "version": SOURCE_ADMISSIBILITY_VERSION,
        "report_path": str(path),
        "burst_source_admissible": admissible,
        "original_run_status": run.get("status"),
        "acquisition_run_key": run.get("acquisition_run_key"),
        "gates": gates,
        "failed_gates": [name for name, passed in gates.items() if not passed],
        "resolved": {
            "processed_chunks": str(processed_root) if processed_root is not None else None,
            "bootstrap_report": str(bootstrap_report) if bootstrap_report is not None else None,
        },
        "resolution_errors": resolution_errors,
        "ignored_market_first_verdict_fields": ignored_market_first_fields,
        "policy": {
            "market_first_official_pass_required": False,
            "market_first_research_handoff_health_required": False,
            "market_first_db_persistence_health_required": False,
            "finalized_source_evidence_required": True,
            "causal_bootstrap_required": True,
            "complete_chunk_processing_required": True,
            "transport_gap_free_required": True,
        },
    }
