from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
from pathlib import Path
import time

from benchmarks.integrated_market_signal_plane_v1.live_shadow import (
    PASS_CLASSIFICATION as SIGNAL_PLANE_PASS,
    run_live_shadow_v0,
)
from src.opportunity_provider_attempt_store import FINAL_PROVIDER_STATUSES
from src.signal_plane_route_research_coordinator_v0 import (
    SIGNAL_PLANE_ROUTE_RESEARCH_COORDINATOR_VERSION,
    SignalPlaneRouteResearchCoordinatorV0,
)


VERSION = "signal_plane_route_research_bridge_v0"
PASS_CLASSIFICATION = "PASS_SIGNAL_PLANE_ROUTE_RESEARCH_BRIDGE_V0"
FAIL_CLASSIFICATION = "FAIL_SIGNAL_PLANE_ROUTE_RESEARCH_BRIDGE_V0"


def _terminal_count(counters: Counter[str], prefix: str) -> int:
    return sum(
        int(counters[f"{prefix}_{status.lower()}"])
        for status in FINAL_PROVIDER_STATUSES
    )


async def run_bridge(
    *,
    run_key: str,
    bootstrap_report: Path,
    allow_v68_fresh_run_key: bool = False,
    duration_seconds: float,
    shadow_output: Path,
    report_output: Path,
    cargo: str = "cargo",
    max_episodes: int = 40,
    research_workers: int = 4,
    hazard_workers: int = 4,
    hazard_wait_timeout_seconds: int = 30,
    hazard_rpc_timeout_seconds: int = 3,
    jupiter_timeout_seconds: int = 5,
    research_notional_usd: float = 25.0,
    research_slippage_bps: int = 100,
    hazard_start_interval_ms: int = 650,
    entry_start_interval_ms: int = 1000,
    downstream_drain_timeout_seconds: float = 120.0,
) -> dict:
    base = str(run_key).strip()
    if not base:
        raise ValueError("run_key cannot be empty")
    if (
        "v68-flow60-fresh" in base.lower()
        and not allow_v68_fresh_run_key
    ):
        raise ValueError(
            "systems bridge must not consume a V68 fresh economic run key "
            "without validated promotion authorization"
        )
    if downstream_drain_timeout_seconds <= 0:
        raise ValueError("downstream_drain_timeout_seconds must be positive")

    coordinator = SignalPlaneRouteResearchCoordinatorV0(
        acquisition_run_key=base,
        max_episodes=max_episodes,
        research_workers=research_workers,
        hazard_workers=hazard_workers,
        hazard_wait_timeout_seconds=hazard_wait_timeout_seconds,
        hazard_rpc_timeout_seconds=hazard_rpc_timeout_seconds,
        jupiter_timeout_seconds=jupiter_timeout_seconds,
        research_notional_usd=research_notional_usd,
        research_slippage_bps=research_slippage_bps,
        hazard_start_interval_ms=hazard_start_interval_ms,
        entry_start_interval_ms=entry_start_interval_ms,
    )
    coordinator.start()

    downstream_drain_timed_out = False
    started = time.monotonic()
    try:
        shadow = await run_live_shadow_v0(
            bootstrap_report=bootstrap_report,
            duration_seconds=duration_seconds,
            max_log_notifications=0,
            cargo=cargo,
            output=shadow_output,
            research_plane_run_key=base,
            research_plane_admit_episode_fn=coordinator.admit_episode,
        )
        try:
            await asyncio.wait_for(
                coordinator.drain(),
                timeout=downstream_drain_timeout_seconds,
            )
        except asyncio.TimeoutError:
            downstream_drain_timed_out = True
    finally:
        await coordinator.close()

    snapshot = coordinator.snapshot()
    counters = Counter(snapshot["counters"])
    selected = int(counters["selected_for_research"])
    hazard_terminal = _terminal_count(counters, "hazard_status")
    hazard_exclusions = sum(
        int(counters[f"hazard_terminal_{status.lower()}"])
        for status in FINAL_PROVIDER_STATUSES
        if status != "AVAILABLE"
    )
    entry_terminal = _terminal_count(counters, "entry_status")
    research_terminal = hazard_exclusions + entry_terminal
    decisions = int(counters["research_decisions_frozen"])
    scheduled = int(counters["research_outcomes_scheduled"])

    checks = {
        "signal_plane_live_pass": (
            shadow.get("classification") == SIGNAL_PLANE_PASS
        ),
        "research_plane_live_enabled": bool(
            shadow.get("research_plane", {}).get("enabled")
        ),
        "research_plane_accounting_exact": bool(
            shadow.get("gates", {}).get("research_plane_accounting_exact")
        ),
        "research_plane_no_errors": bool(
            shadow.get("gates", {}).get("research_plane_no_errors")
        ),
        "episode_admission_exercised": selected > 0,
        "downstream_no_queue_overflow": (
            counters["downstream_queue_overflow"] == 0
        ),
        "downstream_no_worker_errors": (
            counters["hazard_worker_errors"] == 0
            and counters["research_worker_errors"] == 0
        ),
        "downstream_drain_complete": (
            not downstream_drain_timed_out
            and snapshot["hazard_queue_depth"] == 0
            and snapshot["research_queue_depth"] == 0
        ),
        "hazard_terminal_accounting_exact": (
            selected > 0 and hazard_terminal == selected
        ),
        "research_terminal_accounting_exact": (
            selected > 0 and research_terminal == selected
        ),
        "provider_attempts_not_reused": (
            counters["hazard_reused_attempts"] == 0
            and counters["entry_reused_attempts"] == 0
        ),
        "route_only_executable_violations_zero": (
            counters["route_only_executable_violations"] == 0
        ),
        "research_decision_clock_violations_zero": (
            counters["research_decision_clock_violations"] == 0
        ),
        "research_schedule_violations_zero": (
            counters["research_schedule_violations"] == 0
        ),
        "scheduled_outcomes_exact_when_decision_available": (
            scheduled == 3 * decisions
        ),
        "at_least_one_research_decision_frozen": decisions > 0,
    }

    classification = (
        PASS_CLASSIFICATION if all(checks.values()) else FAIL_CLASSIFICATION
    )
    report = {
        "type": "signal_plane_route_research_bridge_report",
        "version": VERSION,
        "classification": classification,
        "authorization": (
            "promoted_v68_component_no_economic_verdict"
            if allow_v68_fresh_run_key
            else "systems_bridge_only_no_v68_fresh_no_economic_verdict"
        ),
        "fresh_v68_run_key_authorized": bool(allow_v68_fresh_run_key),
        "run_key": base,
        "duration_seconds": duration_seconds,
        "elapsed_seconds": time.monotonic() - started,
        "signal_plane": {
            "classification": shadow.get("classification"),
            "version": shadow.get("version"),
            "trigger_parity": shadow.get("trigger_parity"),
            "transport": shadow.get("transport"),
            "research_plane": shadow.get("research_plane"),
            "errors": shadow.get("errors"),
        },
        "downstream": {
            "coordinator_version": (
                SIGNAL_PLANE_ROUTE_RESEARCH_COORDINATOR_VERSION
            ),
            "selected": selected,
            "hazard_terminal": hazard_terminal,
            "hazard_exclusions": hazard_exclusions,
            "entry_terminal": entry_terminal,
            "research_terminal": research_terminal,
            "research_decisions_frozen": decisions,
            "research_outcomes_scheduled": scheduled,
            "drain_timed_out": downstream_drain_timed_out,
            "snapshot": snapshot,
        },
        "checks": checks,
        "scientific_thresholds_modified": False,
        "economic_hypothesis_modified": False,
        "interpretation": (
            "PASS proves the new Signal Plane can feed ordered durable Research "
            "Plane evidence into the frozen hazard/Jupiter/route-decision boundary "
            "with exact accounting. It does not evaluate route outcomes or V68 edge."
            if classification == PASS_CLASSIFICATION
            else "Bridge promotion remains blocked; no economic inference is allowed."
        ),
    }
    report_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Systems-only V5 Signal Plane -> Research Plane -> hazard/Jupiter "
            "route-decision bridge. Never use a V68 fresh key."
        )
    )
    parser.add_argument("--run-key", required=True)
    parser.add_argument("--bootstrap-report", required=True, type=Path)
    parser.add_argument("--duration-seconds", type=float, default=120.0)
    parser.add_argument("--cargo", default="cargo")
    parser.add_argument("--max-episodes", type=int, default=40)
    parser.add_argument("--research-workers", type=int, default=4)
    parser.add_argument("--hazard-workers", type=int, default=4)
    parser.add_argument("--hazard-wait-timeout-seconds", type=int, default=30)
    parser.add_argument("--hazard-rpc-timeout-seconds", type=int, default=3)
    parser.add_argument("--jupiter-timeout-seconds", type=int, default=5)
    parser.add_argument("--research-notional-usd", type=float, default=25.0)
    parser.add_argument("--research-slippage-bps", type=int, default=100)
    parser.add_argument("--hazard-start-interval-ms", type=int, default=650)
    parser.add_argument("--entry-start-interval-ms", type=int, default=1000)
    parser.add_argument(
        "--downstream-drain-timeout-seconds",
        type=float,
        default=120.0,
    )
    parser.add_argument(
        "--shadow-out",
        type=Path,
        default=Path(
            "artifacts/signal_plane_route_research_bridge_v0/shadow.json"
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(
            "artifacts/signal_plane_route_research_bridge_v0/report.json"
        ),
    )
    args = parser.parse_args()

    report = asyncio.run(
        run_bridge(
            run_key=args.run_key,
            bootstrap_report=args.bootstrap_report,
            duration_seconds=args.duration_seconds,
            shadow_output=args.shadow_out,
            report_output=args.out,
            cargo=args.cargo,
            max_episodes=args.max_episodes,
            research_workers=args.research_workers,
            hazard_workers=args.hazard_workers,
            hazard_wait_timeout_seconds=args.hazard_wait_timeout_seconds,
            hazard_rpc_timeout_seconds=args.hazard_rpc_timeout_seconds,
            jupiter_timeout_seconds=args.jupiter_timeout_seconds,
            research_notional_usd=args.research_notional_usd,
            research_slippage_bps=args.research_slippage_bps,
            hazard_start_interval_ms=args.hazard_start_interval_ms,
            entry_start_interval_ms=args.entry_start_interval_ms,
            downstream_drain_timeout_seconds=(
                args.downstream_drain_timeout_seconds
            ),
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0 if report["classification"] == PASS_CLASSIFICATION else 1


if __name__ == "__main__":
    raise SystemExit(main())
