import json
import time
from dataclasses import asdict, dataclass
from statistics import mean, median

from src.database import connection
from src.prices import PriceProviderError
from src.wave_radar import WaveRadarReport


DEFAULT_REJECTION_HORIZONS_MINUTES = (5, 15, 60)
DEFAULT_REJECTION_SAMPLE_PER_RUN = 12

_SCHEMA = """
CREATE TABLE IF NOT EXISTS wave_rejection_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    token_mint TEXT NOT NULL,
    symbol TEXT,
    detected_at INTEGER NOT NULL,
    entry_price_usd REAL NOT NULL,
    wave_score REAL NOT NULL,
    data_valid INTEGER NOT NULL,
    barrier_count INTEGER NOT NULL,
    barriers_json TEXT NOT NULL,
    cautions_json TEXT NOT NULL,
    score_components_json TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    selected_for_followup INTEGER NOT NULL DEFAULT 0,
    selection_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, token_mint),
    FOREIGN KEY (run_id) REFERENCES wave_discovery_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_wave_rejection_run
ON wave_rejection_decisions(run_id, selected_for_followup, data_valid);

CREATE TABLE IF NOT EXISTS wave_rejection_followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rejection_id INTEGER NOT NULL,
    horizon_minutes INTEGER NOT NULL,
    target_at INTEGER NOT NULL,
    observed_at INTEGER,
    market_price_usd REAL,
    return_pct REAL,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    error_code TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(rejection_id, horizon_minutes),
    FOREIGN KEY (rejection_id) REFERENCES wave_rejection_decisions(id)
);

CREATE INDEX IF NOT EXISTS idx_wave_rejection_followups_due
ON wave_rejection_followups(status, target_at);
"""


@dataclass(frozen=True)
class RejectionSelectionSummary:
    run_id: int
    available_count: int
    already_selected_count: int
    newly_selected_count: int
    selected_total: int


@dataclass(frozen=True)
class RejectionSettlementSummary:
    attempted: int
    completed: int
    failed: int
    deferred: int


@dataclass(frozen=True)
class RejectionHorizonSummary:
    horizon_minutes: int
    selected_count: int
    completed_count: int
    failed_count: int
    pending_count: int
    coverage_pct: float
    mean_return_pct: float | None
    median_return_pct: float | None
    positive_share_pct: float | None
    rally_20_share_pct: float | None
    crash_25_share_pct: float | None


@dataclass(frozen=True)
class RejectionBarrierHorizonSummary:
    barrier: str
    horizon_minutes: int
    selected_count: int
    completed_count: int
    failed_count: int
    pending_count: int
    coverage_pct: float
    mean_return_pct: float | None
    median_return_pct: float | None
    positive_share_pct: float | None
    rally_20_share_pct: float | None
    crash_25_share_pct: float | None


@dataclass(frozen=True)
class RejectionLabSummary:
    run_id: int
    rejection_count: int
    data_valid_count: int
    single_barrier_count: int
    selected_count: int
    horizons: tuple[RejectionHorizonSummary, ...]
    single_barrier_horizons: tuple[RejectionBarrierHorizonSummary, ...]
    rejection_counts_by_barrier: tuple[tuple[str, int], ...]


def ensure_rejection_schema() -> None:
    with connection() as conn:
        conn.executescript(_SCHEMA)


def _barriers(value: str) -> tuple[str, ...]:
    return tuple(str(item) for item in json.loads(value))


def record_rejection_decisions(
    report: WaveRadarReport,
    *,
    run_id: int,
    detected_at: int,
) -> int:
    """Persist every rejected radar decision; never changes whether a token passes."""
    if run_id <= 0:
        raise ValueError("run_id must be positive")
    if detected_at < 0:
        raise ValueError("detected_at must be non-negative")
    ensure_rejection_schema()
    with connection() as conn:
        validity = {
            str(row["token_mint"]): int(row["data_valid"])
            for row in conn.execute(
                "SELECT token_mint, data_valid FROM wave_discovery_candidates WHERE run_id=?",
                (run_id,),
            ).fetchall()
        }
        inserted = 0
        for result in report.results:
            if result.passed:
                continue
            cursor = conn.execute(
                """INSERT OR IGNORE INTO wave_rejection_decisions(
                    run_id, token_mint, symbol, detected_at, entry_price_usd,
                    wave_score, data_valid, barrier_count, barriers_json,
                    cautions_json, score_components_json, snapshot_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    result.token.token,
                    result.token.symbol,
                    detected_at,
                    float(result.token.price_usd),
                    float(result.wave_score),
                    validity.get(result.token.token, 0),
                    len(result.barriers),
                    json.dumps(result.barriers, separators=(",", ":")),
                    json.dumps(result.cautions, separators=(",", ":")),
                    json.dumps(result.score_components, sort_keys=True, separators=(",", ":")),
                    json.dumps(asdict(result.token), sort_keys=True, separators=(",", ":")),
                ),
            )
            inserted += int(cursor.rowcount > 0)
    return inserted


def select_rejection_followups(
    run_id: int,
    *,
    max_tokens: int = DEFAULT_REJECTION_SAMPLE_PER_RUN,
    horizons_minutes: tuple[int, ...] = DEFAULT_REJECTION_HORIZONS_MINUTES,
) -> RejectionSelectionSummary:
    """Select a bounded deterministic sample, preferring clean single-barrier rejects."""
    if run_id <= 0 or max_tokens <= 0:
        raise ValueError("run_id and max_tokens must be positive")
    horizons = tuple(dict.fromkeys(int(item) for item in horizons_minutes))
    if not horizons or any(item <= 0 for item in horizons):
        raise ValueError("horizons_minutes must contain positive values")
    ensure_rejection_schema()
    with connection() as conn:
        raw = conn.execute(
            """SELECT id, token_mint, wave_score, barrier_count, barriers_json,
                selected_for_followup
            FROM wave_rejection_decisions
            WHERE run_id=? AND data_valid=1 AND entry_price_usd>0
            ORDER BY wave_score DESC, token_mint""",
            (run_id,),
        ).fetchall()
    candidates = [dict(row) for row in raw]
    selected_ids = {
        int(row["id"])
        for row in candidates
        if int(row["selected_for_followup"]) == 1
    }
    already = len(selected_ids)
    slots = max(0, max_tokens - already)
    unselected = [row for row in candidates if int(row["id"]) not in selected_ids]

    # First take the best near-miss from each single barrier. This gives cleaner
    # evidence about an individual gate than a token rejected for many reasons.
    group_best: list[dict] = []
    groups: dict[str, list[dict]] = {}
    for row in unselected:
        barriers = _barriers(str(row["barriers_json"]))
        if int(row["barrier_count"]) == 1 and barriers:
            groups.setdefault(barriers[0], []).append(row)
    for group in groups.values():
        group_best.append(
            sorted(
                group,
                key=lambda r: (-float(r["wave_score"]), str(r["token_mint"])),
            )[0]
        )
    group_best.sort(key=lambda r: -float(r["wave_score"]))

    chosen: list[tuple[dict, str]] = []
    chosen_ids: set[int] = set()
    for row in group_best:
        if len(chosen) >= slots:
            break
        chosen.append((row, "single_barrier_stratum"))
        chosen_ids.add(int(row["id"]))

    remaining = [row for row in unselected if int(row["id"]) not in chosen_ids]
    remaining.sort(
        key=lambda r: (
            int(r["barrier_count"]) != 1,
            int(r["barrier_count"]),
            -float(r["wave_score"]),
            str(r["token_mint"]),
        )
    )
    for row in remaining:
        if len(chosen) >= slots:
            break
        reason = (
            "single_barrier_priority_fill"
            if int(row["barrier_count"]) == 1
            else "multi_barrier_priority_fill"
        )
        chosen.append((row, reason))

    with connection() as conn:
        for row, reason in chosen:
            conn.execute(
                """UPDATE wave_rejection_decisions
                SET selected_for_followup=1, selection_reason=? WHERE id=?""",
                (reason, int(row["id"])),
            )
        selected = conn.execute(
            """SELECT id, detected_at FROM wave_rejection_decisions
            WHERE run_id=? AND selected_for_followup=1""",
            (run_id,),
        ).fetchall()
        for row in selected:
            for horizon in horizons:
                conn.execute(
                    """INSERT OR IGNORE INTO wave_rejection_followups(
                        rejection_id, horizon_minutes, target_at
                    ) VALUES (?, ?, ?)""",
                    (
                        int(row["id"]),
                        horizon,
                        int(row["detected_at"]) + horizon * 60,
                    ),
                )
    return RejectionSelectionSummary(
        run_id,
        len(candidates),
        already,
        len(chosen),
        already + len(chosen),
    )


def settle_due_rejection_followups(
    provider,
    *,
    now: int | None = None,
    run_id: int | None = None,
    max_checks: int = 12,
    max_candle_distance_seconds: int = 300,
) -> RejectionSettlementSummary:
    if max_checks <= 0 or max_candle_distance_seconds < 0:
        raise ValueError("invalid settlement limits")
    if run_id is not None and run_id <= 0:
        raise ValueError("run_id must be positive")
    ensure_rejection_schema()
    now = int(time.time()) if now is None else int(now)
    query = """SELECT f.id, f.target_at, d.token_mint, d.entry_price_usd
        FROM wave_rejection_followups f
        JOIN wave_rejection_decisions d ON d.id=f.rejection_id
        WHERE f.status='pending' AND f.target_at<=?"""
    params: list[object] = [now]
    if run_id is not None:
        query += " AND d.run_id=?"
        params.append(run_id)
    query += " ORDER BY f.target_at, f.id LIMIT ?"
    params.append(max_checks)
    with connection() as conn:
        due = conn.execute(query, tuple(params)).fetchall()

    completed = failed = deferred = 0
    for row in due:
        followup_id = int(row["id"])
        try:
            price = float(
                provider.price_at(
                    str(row["token_mint"]),
                    int(row["target_at"]),
                    max_distance_seconds=max_candle_distance_seconds,
                )
            )
            if price <= 0:
                raise ValueError("price provider returned non-positive price")
        except PriceProviderError as exc:
            retryable = bool(getattr(exc, "retryable", False))
            with connection() as conn:
                conn.execute(
                    """UPDATE wave_rejection_followups
                    SET status=?, error=?, error_code=?, retry_count=retry_count+1,
                        updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (
                        "pending" if retryable else "failed",
                        str(exc),
                        getattr(exc, "code", type(exc).__name__),
                        followup_id,
                    ),
                )
            if retryable:
                deferred += 1
            else:
                failed += 1
            continue
        except (TypeError, ValueError) as exc:
            with connection() as conn:
                conn.execute(
                    """UPDATE wave_rejection_followups
                    SET status='failed', error=?, error_code='invalid_price',
                        retry_count=retry_count+1, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (str(exc), followup_id),
                )
            failed += 1
            continue

        entry = float(row["entry_price_usd"])
        return_pct = 100.0 * (price / entry - 1.0)
        with connection() as conn:
            conn.execute(
                """UPDATE wave_rejection_followups
                SET status='completed', observed_at=?, market_price_usd=?, return_pct=?,
                    error=NULL, error_code=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (now, price, return_pct, followup_id),
            )
        completed += 1
    return RejectionSettlementSummary(len(due), completed, failed, deferred)


def _share(values: list[float], predicate) -> float | None:
    if not values:
        return None
    return 100.0 * sum(bool(predicate(value)) for value in values) / len(values)


def _summarize_horizon_rows(
    group: list[dict],
    *,
    horizon_minutes: int,
) -> RejectionHorizonSummary:
    values = [
        float(row["return_pct"])
        for row in group
        if row["status"] == "completed" and row["return_pct"] is not None
    ]
    return RejectionHorizonSummary(
        horizon_minutes=horizon_minutes,
        selected_count=len(group),
        completed_count=sum(row["status"] == "completed" for row in group),
        failed_count=sum(row["status"] == "failed" for row in group),
        pending_count=sum(row["status"] == "pending" for row in group),
        coverage_pct=100.0 * len(values) / len(group) if group else 0.0,
        mean_return_pct=mean(values) if values else None,
        median_return_pct=median(values) if values else None,
        positive_share_pct=_share(values, lambda value: value > 0),
        rally_20_share_pct=_share(values, lambda value: value >= 20),
        crash_25_share_pct=_share(values, lambda value: value <= -25),
    )


def summarize_rejection_lab(run_id: int) -> RejectionLabSummary:
    if run_id <= 0:
        raise ValueError("run_id must be positive")
    ensure_rejection_schema()
    with connection() as conn:
        decisions = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM wave_rejection_decisions WHERE run_id=? ORDER BY id",
                (run_id,),
            ).fetchall()
        ]
        followups = [
            dict(row)
            for row in conn.execute(
                """SELECT f.*, d.barrier_count, d.barriers_json
                FROM wave_rejection_followups f
                JOIN wave_rejection_decisions d ON d.id=f.rejection_id
                WHERE d.run_id=? ORDER BY f.horizon_minutes, f.id""",
                (run_id,),
            ).fetchall()
        ]

    horizons: list[RejectionHorizonSummary] = []
    for horizon in sorted({int(row["horizon_minutes"]) for row in followups}):
        group = [
            row for row in followups if int(row["horizon_minutes"]) == horizon
        ]
        horizons.append(
            _summarize_horizon_rows(group, horizon_minutes=horizon)
        )

    isolated_groups: dict[tuple[str, int], list[dict]] = {}
    for row in followups:
        if int(row["barrier_count"]) != 1:
            continue
        barriers = _barriers(str(row["barriers_json"]))
        if not barriers:
            continue
        key = (barriers[0], int(row["horizon_minutes"]))
        isolated_groups.setdefault(key, []).append(row)

    single_barrier_horizons: list[RejectionBarrierHorizonSummary] = []
    for (barrier, horizon), group in sorted(
        isolated_groups.items(), key=lambda item: (item[0][0], item[0][1])
    ):
        base = _summarize_horizon_rows(group, horizon_minutes=horizon)
        single_barrier_horizons.append(
            RejectionBarrierHorizonSummary(
                barrier=barrier,
                horizon_minutes=base.horizon_minutes,
                selected_count=base.selected_count,
                completed_count=base.completed_count,
                failed_count=base.failed_count,
                pending_count=base.pending_count,
                coverage_pct=base.coverage_pct,
                mean_return_pct=base.mean_return_pct,
                median_return_pct=base.median_return_pct,
                positive_share_pct=base.positive_share_pct,
                rally_20_share_pct=base.rally_20_share_pct,
                crash_25_share_pct=base.crash_25_share_pct,
            )
        )

    counts: dict[str, int] = {}
    for row in decisions:
        for barrier in _barriers(str(row["barriers_json"])):
            counts[barrier] = counts.get(barrier, 0) + 1
    return RejectionLabSummary(
        run_id=run_id,
        rejection_count=len(decisions),
        data_valid_count=sum(int(row["data_valid"]) == 1 for row in decisions),
        single_barrier_count=sum(
            int(row["barrier_count"]) == 1 for row in decisions
        ),
        selected_count=sum(
            int(row["selected_for_followup"]) == 1 for row in decisions
        ),
        horizons=tuple(horizons),
        single_barrier_horizons=tuple(single_barrier_horizons),
        rejection_counts_by_barrier=tuple(
            sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ),
    )


def latest_rejection_run_id() -> int | None:
    ensure_rejection_schema()
    with connection() as conn:
        row = conn.execute(
            "SELECT run_id FROM wave_rejection_decisions ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return int(row["run_id"]) if row is not None else None
