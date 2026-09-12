from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Sequence

from benchmarks.market_first_live_discovery_v0.contracts import PASS_CLASSIFICATION as LIVE_PASS
from benchmarks.market_first_postrun_readiness_v0 import (
    FAIL_CLASSIFICATION,
    POSTRUN_READINESS_VERSION,
    READY_CLASSIFICATION,
    WAITING_CLASSIFICATION,
)
from src.config import settings
from src.opportunity_forward_outcome_store import (
    FORWARD_OUTCOME_FINAL_STATUSES,
    FORWARD_OUTCOME_HORIZONS_SECONDS,
)


KNOWN_OUTCOME_STATUSES = frozenset({"PENDING", *FORWARD_OUTCOME_FINAL_STATUSES})


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("live report must contain a JSON object")
    return payload


def _open_read_only_database(path: Path) -> sqlite3.Connection:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"database not found: {resolved}")
    conn = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _load_outcomes_read_only(*, database_path: Path, acquisition_run_key: str) -> list[dict[str, Any]]:
    with _open_read_only_database(database_path) as conn:
        table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='opportunity_forward_outcomes'"
        ).fetchone()
        if table is None:
            raise RuntimeError("opportunity_forward_outcomes table is missing")
        rows = conn.execute(
            """SELECT outcome_key, acquisition_run_key, episode_key, token_mint,
                decision_as_of, horizon_seconds, target_at, status, observed_at,
                quote_key, error_type, error_message, created_at,
                CAST(strftime('%s', created_at) AS INTEGER) AS scheduled_at
            FROM opportunity_forward_outcomes
            WHERE acquisition_run_key=?
            ORDER BY episode_key, horizon_seconds""",
            (acquisition_run_key,),
        ).fetchall()
    return [dict(row) for row in rows]


def _rate(count: int, total: int) -> float | None:
    return (float(count) / float(total)) if total > 0 else None


def _trade_summary(pipeline: dict[str, Any]) -> dict[str, Any]:
    statuses = {
        str(key): int(value)
        for key, value in (pipeline.get("market_trade_statuses") or {}).items()
    }
    total = sum(statuses.values())
    adapted = int(statuses.get("ADAPTED", 0))
    missing = int(statuses.get("MISSING_CONTEXT", 0))
    invalid = total - adapted - missing
    return {
        "status_counts": dict(sorted(statuses.items())),
        "total": total,
        "adapted": adapted,
        "missing_context": missing,
        "invalid_or_other": invalid,
        "adapted_rate": _rate(adapted, total),
        "missing_context_rate": _rate(missing, total),
        "invalid_or_other_rate": _rate(invalid, total),
        "protocol_split_available": False,
    }


def _validate_outcomes(
    *,
    outcomes: list[dict[str, Any]],
    analyzable_t0_count: int,
    observed_at: int,
) -> tuple[dict[str, Any], dict[str, bool]]:
    expected_horizons = tuple(int(item) for item in FORWARD_OUTCOME_HORIZONS_SECONDS)
    expected_set = set(expected_horizons)
    expected_count = int(analyzable_t0_count) * len(expected_horizons)
    by_episode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    status_counts: Counter[str] = Counter()
    per_horizon: dict[int, Counter[str]] = {horizon: Counter() for horizon in expected_horizons}
    per_horizon_late_schedule: Counter[int] = Counter()
    exact_target_clocks = True
    known_statuses = True
    terminal_semantics_valid = True
    schedules_causally_eligible = True
    pending_count = 0
    pending_due_count = 0
    pending_not_yet_due_count = 0
    late_schedule_count = 0
    schedule_delay_from_t0_seconds: list[int] = []

    for row in outcomes:
        episode_key = str(row["episode_key"])
        by_episode[episode_key].append(row)
        horizon = int(row["horizon_seconds"])
        status = str(row["status"])
        decision_as_of = int(row["decision_as_of"])
        target_at = int(row["target_at"])
        observed = row["observed_at"]
        quote_key = row["quote_key"]
        scheduled_raw = row.get("scheduled_at")
        scheduled_at = int(scheduled_raw) if scheduled_raw is not None else None
        status_counts[status] += 1
        if horizon in per_horizon:
            per_horizon[horizon][status] += 1
        if horizon not in expected_set or target_at != decision_as_of + horizon:
            exact_target_clocks = False

        # A prospective target must exist no later than its own target clock. If the
        # Research Plane only schedules +5m/+15m/+60m after those clocks have already
        # passed, a later provider observation cannot be treated as the preregistered
        # forward horizon without historical backfill or silent horizon drift.
        if scheduled_at is None:
            schedules_causally_eligible = False
        else:
            schedule_delay_from_t0_seconds.append(scheduled_at - decision_as_of)
            if scheduled_at > target_at:
                schedules_causally_eligible = False
                late_schedule_count += 1
                per_horizon_late_schedule[horizon] += 1

        if status not in KNOWN_OUTCOME_STATUSES:
            known_statuses = False
            terminal_semantics_valid = False
            continue
        if status == "PENDING":
            pending_count += 1
            if target_at <= observed_at:
                pending_due_count += 1
            else:
                pending_not_yet_due_count += 1
            if observed is not None or quote_key is not None:
                terminal_semantics_valid = False
        else:
            if observed is None or int(observed) < target_at:
                terminal_semantics_valid = False
            if status == "AVAILABLE" and not str(quote_key or "").strip():
                terminal_semantics_valid = False

    exact_horizon_cardinality = len(outcomes) == expected_count
    if len(by_episode) != int(analyzable_t0_count):
        exact_horizon_cardinality = False
    for rows in by_episode.values():
        horizons = [int(row["horizon_seconds"]) for row in rows]
        if len(horizons) != len(expected_horizons) or set(horizons) != expected_set:
            exact_horizon_cardinality = False

    summary = {
        "expected_horizons_seconds": list(expected_horizons),
        "analyzable_t0_count": int(analyzable_t0_count),
        "expected_outcome_count": expected_count,
        "persisted_outcome_count": len(outcomes),
        "episode_count_with_outcomes": len(by_episode),
        "status_counts": dict(sorted(status_counts.items())),
        "pending_count": pending_count,
        "pending_due_count": pending_due_count,
        "pending_not_yet_due_count": pending_not_yet_due_count,
        "terminal_count": len(outcomes) - pending_count,
        "late_schedule_count": late_schedule_count,
        "schedule_before_or_at_target_count": len(outcomes) - late_schedule_count,
        "max_schedule_delay_from_t0_seconds": (
            max(schedule_delay_from_t0_seconds) if schedule_delay_from_t0_seconds else None
        ),
        "per_horizon": {
            str(horizon): {
                "expected": int(analyzable_t0_count),
                "observed": sum(per_horizon[horizon].values()),
                "status_counts": dict(sorted(per_horizon[horizon].items())),
                "late_schedule_count": int(per_horizon_late_schedule[horizon]),
            }
            for horizon in expected_horizons
        },
    }
    gates = {
        "exact_forward_outcome_cardinality": exact_horizon_cardinality,
        "exact_forward_target_clocks": exact_target_clocks,
        "forward_outcomes_scheduled_no_later_than_target": schedules_causally_eligible,
        "known_forward_outcome_statuses": known_statuses,
        "forward_outcome_terminal_semantics_valid": terminal_semantics_valid,
    }
    return summary, gates


def build_postrun_readiness_v0(
    *,
    live_report_path: Path,
    database_path: Path | None = None,
    observed_at: int | None = None,
) -> dict[str, Any]:
    live_path = Path(live_report_path)
    live = _load_json(live_path)
    identity = live.get("identity") or {}
    run = live.get("run") or {}
    audit = live.get("audit") or {}
    pipeline = live.get("pipeline") or {}
    acquisition = live.get("acquisition") or {}
    run_key = str(identity.get("acquisition_run_key") or "").strip()
    if not run_key:
        raise ValueError("live report acquisition_run_key is missing")
    audit_run_key = str(audit.get("acquisition_run_key") or "").strip()
    db_path = Path(database_path) if database_path is not None else Path(settings.database_path)
    now = int(time.time()) if observed_at is None else int(observed_at)
    outcomes = _load_outcomes_read_only(database_path=db_path, acquisition_run_key=run_key)
    analyzable_t0_count = int(audit.get("analyzable_t0_count") or 0)
    outcome_summary, outcome_gates = _validate_outcomes(
        outcomes=outcomes,
        analyzable_t0_count=analyzable_t0_count,
        observed_at=now,
    )

    no_pipeline_errors = not any(
        pipeline.get(name)
        for name in ("chunk_errors", "persistence_errors", "research_errors", "semantic_errors")
    )
    live_gates = live.get("gates") or {}
    gates = {
        "live_discovery_pass": (
            live.get("classification") == LIVE_PASS and live.get("valid_live_discovery") is True
        ),
        "live_run_closed_normally": run.get("status") == "CLOSED",
        "live_gates_all_pass": bool(live_gates) and all(bool(value) for value in live_gates.values()),
        "pre_economic_integrity_audit_ready": audit.get("integrity_ready_for_close_or_analysis") is True,
        "run_identity_matches_audit": bool(audit_run_key) and audit_run_key == run_key,
        "pipeline_integrity_errors_absent": no_pipeline_errors,
        "economic_edge_not_already_evaluated": live.get("economic_edge_evaluated") is False,
        "coverage_claim_remains_operational_only": (
            live.get("coverage_classification") == "operational_only_not_chain_complete"
            and live.get("chain_complete_coverage_claimed") is False
        ),
        **outcome_gates,
    }
    integrity_ok = bool(gates) and all(gates.values())
    pending = int(outcome_summary["pending_count"])
    if not integrity_ok:
        classification = FAIL_CLASSIFICATION
    elif pending > 0:
        classification = WAITING_CLASSIFICATION
    else:
        classification = READY_CLASSIFICATION

    report = {
        "type": "market_first_postrun_readiness",
        "version": POSTRUN_READINESS_VERSION,
        "classification": classification,
        "safe_to_start_economic_analysis": classification == READY_CLASSIFICATION,
        "economic_edge_evaluated": False,
        "observed_at": now,
        "source_live_report": str(live_path),
        "database_path": str(db_path),
        "acquisition_run_key": run_key,
        "live": {
            "classification": live.get("classification"),
            "valid_live_discovery": live.get("valid_live_discovery"),
            "run_status": run.get("status"),
            "coverage_classification": live.get("coverage_classification"),
            "chunk_count": acquisition.get("chunk_count"),
            "chunks_processed": pipeline.get("chunks_processed"),
            "cohort_denominator": audit.get("cohort_denominator"),
            "analyzable_t0_count": analyzable_t0_count,
            "disposition_counts": audit.get("disposition_counts") or [],
        },
        "trade_coverage": _trade_summary(pipeline),
        "forward_outcomes": outcome_summary,
        "gates": gates,
    }
    return report


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    Path(path).write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=POSTRUN_READINESS_VERSION,
        description="Read-only, provider-free post-run gate before any Market-First economic analysis.",
    )
    parser.add_argument("--live-report", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    out = args.out or (args.live_report.parent / "postrun-readiness.json")
    try:
        report = build_postrun_readiness_v0(
            live_report_path=args.live_report,
            database_path=args.database,
        )
    except Exception as exc:
        report = {
            "type": "market_first_postrun_readiness",
            "version": POSTRUN_READINESS_VERSION,
            "classification": FAIL_CLASSIFICATION,
            "safe_to_start_economic_analysis": False,
            "economic_edge_evaluated": False,
            "source_live_report": str(args.live_report),
            "fatal_error": f"{type(exc).__name__}:{exc}",
        }
    out.parent.mkdir(parents=True, exist_ok=True)
    _write_json(out, report)
    print(json.dumps(report, sort_keys=True, indent=2), flush=True)
    classification = report.get("classification")
    if classification == READY_CLASSIFICATION:
        return 0
    if classification == WAITING_CLASSIFICATION:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())