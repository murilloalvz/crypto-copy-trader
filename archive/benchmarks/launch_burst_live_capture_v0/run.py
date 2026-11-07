from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import time
import uuid
from typing import Any

from benchmarks.helius_standard_wss_shadow_v0.collect import collect_shadow
from benchmarks.market_first_live_discovery_v0.contracts import (
    load_bootstrap_evidence_v0,
    validate_bootstrap_before_discovery_start_v0,
)
from benchmarks.market_first_live_discovery_v0.pipeline import (
    LiveDiscoveryPipelineStateV0,
    process_trace_chunk_v0,
    seed_bootstrap_identities_v0,
)


CAPTURE_VERSION = "launch_burst_live_capture_v0"
DEFAULT_DURATION_SECONDS = 900
DEFAULT_ARTIFACTS_ROOT = Path("artifacts") / CAPTURE_VERSION


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _capture_id() -> str:
    return f"{CAPTURE_VERSION}-{int(time.time())}-{uuid.uuid4().hex[:10]}"


def _classification_gates(*, footer: dict[str, Any], state: LiveDiscoveryPipelineStateV0, chunk_report: dict[str, Any]) -> dict[str, bool]:
    counters = footer.get("counters") or {}
    return {
        "operational_shadow_active": footer.get("valid_operational_shadow") is True,
        "duration_elapsed": footer.get("stop_reason") == "duration_elapsed",
        "no_transport_errors": int(counters.get("transport_errors") or 0) == 0,
        "no_reconnects": int(counters.get("reconnects") or 0) == 0,
        "no_rpc_errors": int(counters.get("rpc_errors") or 0) == 0,
        "no_write_errors": int(counters.get("write_errors") or 0) == 0,
        "chunk_processed": chunk_report.get("status") in {"PROCESSED", "NO_TARGET_EVENTS"},
        "no_chunk_errors": not state.chunk_errors,
        "no_semantic_errors": not state.semantic_errors,
        "no_persistence_errors": not state.persistence_errors,
        "no_research_errors": not state.research_errors,
        "causal_lifecycle_seen": state.lifecycle_events_ingested > 0,
        "causal_trade_seen": state.market_trade_adapted_events > 0,
    }


async def _run_capture_async(
    *,
    api_key: str,
    bootstrap_report: Path,
    artifacts_root: Path,
    duration_seconds: int,
    cargo: str,
) -> dict[str, Any]:
    if duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    evidence = load_bootstrap_evidence_v0(bootstrap_report)
    capture_id = _capture_id()
    run_dir = Path(artifacts_root) / capture_id
    raw_dir = run_dir / "raw"
    processed_root = run_dir / "processed"
    raw_dir.mkdir(parents=True, exist_ok=False)
    processed_root.mkdir(parents=True, exist_ok=True)
    raw_trace = raw_dir / "trace.jsonl"
    report_path = run_dir / "report.json"

    discovery_start_wall_ns = time.time_ns()
    validate_bootstrap_before_discovery_start_v0(
        evidence,
        discovery_start_wall_ns=discovery_start_wall_ns,
    )
    discovery_close_wall_ns = discovery_start_wall_ns + int(duration_seconds) * 1_000_000_000

    footer = await collect_shadow(
        api_key=api_key,
        out_path=raw_trace,
        duration_seconds=float(duration_seconds),
        max_log_notifications=0,
        max_reconnects=5,
        ack_timeout_seconds=20.0,
        reconnect_delay_seconds=2.0,
    )

    state = LiveDiscoveryPipelineStateV0()
    seed_bootstrap_identities_v0(state, evidence.identities)
    chunk_report = process_trace_chunk_v0(
        state=state,
        api_key=api_key,
        cargo=cargo,
        acquisition_run_key=capture_id,
        raw_trace_path=raw_trace,
        processed_root=processed_root,
        discovery_start_wall_ns=discovery_start_wall_ns,
        discovery_close_wall_ns=discovery_close_wall_ns,
        compress_evidence=True,
    )
    gates = _classification_gates(footer=footer, state=state, chunk_report=chunk_report)
    passed = all(gates.values())
    report = {
        "type": "launch_burst_live_capture",
        "version": CAPTURE_VERSION,
        "capture_id": capture_id,
        "acquisition_run_key": capture_id,
        "duration_seconds": int(duration_seconds),
        "discovery_start_wall_ns": discovery_start_wall_ns,
        "discovery_close_wall_ns": discovery_close_wall_ns,
        "bootstrap": {
            "report_path": str(evidence.report_path.resolve()),
            "run_id": evidence.run_id,
            "decoded_identity_count": evidence.decoded_identity_count,
        },
        "acquisition": footer,
        "pipeline": state.summary(),
        "chunk_report": chunk_report,
        "artifacts": {
            "run_dir": str(run_dir.resolve()),
            "processed_root": str(processed_root.resolve()),
            "report": str(report_path.resolve()),
        },
        "gates": gates,
        "classification": (
            "PASS_LAUNCH_BURST_LIVE_CAPTURE_V0"
            if passed
            else "FAIL_LAUNCH_BURST_LIVE_CAPTURE_V0"
        ),
        "scientific_scope": {
            "feature_research_only": True,
            "economic_edge_evaluated": False,
            "future_outcomes_loaded": False,
            "chain_complete_coverage_claimed": False,
            "received_wall_ns_preserved_in_processed_manifest": True,
            "matched_unit_reconstructable_from_processed_evidence": True,
        },
    }
    _write_json(report_path, report)
    return report


def run_capture(*, api_key: str, bootstrap_report: Path, artifacts_root: Path, duration_seconds: int, cargo: str = "cargo") -> dict[str, Any]:
    return asyncio.run(
        _run_capture_async(
            api_key=api_key,
            bootstrap_report=bootstrap_report,
            artifacts_root=artifacts_root,
            duration_seconds=duration_seconds,
            cargo=cargo,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Dedicated short Launch Burst live capture v0")
    parser.add_argument("--bootstrap-report", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, default=DEFAULT_DURATION_SECONDS)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--cargo", default="cargo")
    args = parser.parse_args()
    api_key = os.environ.get("HELIUS_API_KEY", "").strip()
    if not api_key:
        print("HELIUS_API_KEY is required in the environment", flush=True)
        return 2
    try:
        report = run_capture(
            api_key=api_key,
            bootstrap_report=args.bootstrap_report,
            artifacts_root=args.artifacts_root,
            duration_seconds=args.duration_seconds,
            cargo=args.cargo,
        )
    except Exception as exc:
        print(f"Launch Burst live capture failed: {type(exc).__name__}: {exc}", flush=True)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    return 0 if report["classification"] == "PASS_LAUNCH_BURST_LIVE_CAPTURE_V0" else 2


if __name__ == "__main__":
    raise SystemExit(main())
