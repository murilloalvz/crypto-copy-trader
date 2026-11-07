import json
import time
from dataclasses import asdict, dataclass

from src.database import connection, rows
from src.wave_paper import SignalPersistenceOutcome
from src.wave_radar import WaveRadarPolicy, WaveRadarReport


DATA_VALIDITY_BARRIERS = {
    "price_unavailable",
    "pool_unavailable",
    "volume_windows_inconsistent",
    "holders_unavailable",
    "risk_unavailable",
}


@dataclass(frozen=True)
class FunnelSummary:
    run_id: int
    discovered: int
    data_valid: int
    candidates: int
    signals_created: int
    duplicates: int
    persistence_rejected: int
    requested_limit: int
    status: str
    source_items: int = 0
    source_invalid: int = 0
    source_duplicates: int = 0


def record_discovery_run(
    report: WaveRadarReport,
    *,
    requested_token_limit: int,
    returned_count: int,
    source_item_count: int | None = None,
    source_invalid_count: int = 0,
    source_duplicate_count: int = 0,
    policy: WaveRadarPolicy,
    outcomes: tuple[SignalPersistenceOutcome, ...] = (),
    started_at_ms: int | None = None,
    completed_at_ms: int | None = None,
) -> FunnelSummary:
    """Persist one non-invasive audit of source coverage and strategy attrition."""
    started_at_ms = (
        int(time.time() * 1_000) if started_at_ms is None else int(started_at_ms)
    )
    completed_at_ms = (
        int(time.time() * 1_000) if completed_at_ms is None else int(completed_at_ms)
    )
    outcome_by_mint = {item.token_mint: item for item in outcomes}
    data_valid_count = sum(
        not DATA_VALIDITY_BARRIERS.intersection(result.barriers)
        for result in report.results
    )
    created = sum(item.outcome == "created" for item in outcomes)
    duplicates = sum(item.outcome == "duplicate" for item in outcomes)
    persistence_rejected = sum(
        item.outcome not in {"created", "duplicate", "strategy_rejected"}
        for item in outcomes
    )
    with connection() as conn:
        cursor = conn.execute(
            """INSERT INTO wave_discovery_runs
            (started_at, completed_at, source, requested_token_limit,
             source_item_count, source_invalid_count, source_duplicate_count,
             returned_count, analyzed_count, data_valid_count,
             strategy_candidate_count, signals_created_count, duplicate_count,
             persistence_rejected_count, policy_json, status)
            VALUES (?, ?, 'solana_tracker_token_search', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'completed')""",
            (
                started_at_ms,
                completed_at_ms,
                requested_token_limit,
                returned_count if source_item_count is None else source_item_count,
                source_invalid_count,
                source_duplicate_count,
                returned_count,
                report.analyzed_count,
                data_valid_count,
                report.passed_count,
                created,
                duplicates,
                persistence_rejected,
                json.dumps(asdict(policy), sort_keys=True, separators=(",", ":")),
            ),
        )
        run_id = int(cursor.lastrowid)
        conn.executemany(
            """INSERT INTO wave_discovery_candidates
            (run_id, token_mint, symbol, wave_score, data_valid,
             strategy_passed, barriers_json, persistence_outcome, signal_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    run_id,
                    result.token.token,
                    result.token.symbol,
                    result.wave_score,
                    int(not DATA_VALIDITY_BARRIERS.intersection(result.barriers)),
                    int(result.passed),
                    json.dumps(result.barriers, separators=(",", ":")),
                    outcome_by_mint.get(result.token.token).outcome
                    if result.token.token in outcome_by_mint
                    else None,
                    outcome_by_mint.get(result.token.token).signal_id
                    if result.token.token in outcome_by_mint
                    else None,
                )
                for result in report.results
            ],
        )

    # The discovery run and candidate rows must be committed before the sidecar
    # opens its own connection, because its rows reference run_id by foreign key.
    # This sidecar is observational only: it never changes pass/fail or creates a signal.
    from src.rejection_intelligence import (
        record_rejection_decisions,
        select_rejection_followups,
    )

    record_rejection_decisions(
        report,
        run_id=run_id,
        detected_at=completed_at_ms // 1_000,
    )
    select_rejection_followups(run_id)

    normalized_source_items = (
        returned_count if source_item_count is None else source_item_count
    )
    return FunnelSummary(
        run_id,
        returned_count,
        data_valid_count,
        report.passed_count,
        created,
        duplicates,
        persistence_rejected,
        requested_token_limit,
        "completed",
        normalized_source_items,
        source_invalid_count,
        source_duplicate_count,
    )


def record_failed_discovery(
    *,
    requested_token_limit: int,
    policy: WaveRadarPolicy,
    error: str,
    started_at_ms: int | None = None,
) -> FunnelSummary:
    started_at_ms = (
        int(time.time() * 1_000) if started_at_ms is None else int(started_at_ms)
    )
    with connection() as conn:
        cursor = conn.execute(
            """INSERT INTO wave_discovery_runs
            (started_at, completed_at, source, requested_token_limit, policy_json,
             status, error)
            VALUES (?, ?, 'solana_tracker_token_search', ?, ?, 'source_failed', ?)""",
            (
                started_at_ms,
                int(time.time() * 1_000),
                requested_token_limit,
                json.dumps(asdict(policy), sort_keys=True, separators=(",", ":")),
                error,
            ),
        )
        run_id = int(cursor.lastrowid)
    return FunnelSummary(
        run_id, 0, 0, 0, 0, 0, 0, requested_token_limit, "source_failed"
    )


def rejection_counts(run_id: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in rows(
        "SELECT barriers_json FROM wave_discovery_candidates WHERE run_id=?",
        (run_id,),
    ):
        for barrier in json.loads(item["barriers_json"]):
            counts[barrier] = counts.get(barrier, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def latest_funnel_summary() -> FunnelSummary | None:
    latest = rows("SELECT * FROM wave_discovery_runs ORDER BY id DESC LIMIT 1")
    if not latest:
        return None
    item = latest[0]
    return FunnelSummary(
        item["id"],
        item["returned_count"],
        item["data_valid_count"],
        item["strategy_candidate_count"],
        item["signals_created_count"],
        item["duplicate_count"],
        item["persistence_rejected_count"],
        item["requested_token_limit"],
        item["status"],
        item["source_item_count"],
        item["source_invalid_count"],
        item["source_duplicate_count"],
    )
