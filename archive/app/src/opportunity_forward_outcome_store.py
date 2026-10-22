from __future__ import annotations

from dataclasses import dataclass
import threading

from src import database
from src.database import connection
from src.market_opportunity_episode_store import MarketOpportunityEpisode


FORWARD_OUTCOME_HORIZONS_SECONDS = (300, 900, 3600)
FORWARD_OUTCOME_FINAL_STATUSES = {"AVAILABLE", "UNAVAILABLE", "PROVIDER_ERROR"}


@dataclass(frozen=True)
class OpportunityForwardOutcome:
    outcome_key: str
    acquisition_run_key: str
    episode_key: str
    token_mint: str
    decision_as_of: int
    horizon_seconds: int
    target_at: int
    status: str
    observed_at: int | None
    quote_key: str | None
    error_type: str | None
    error_message: str | None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunity_forward_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    outcome_key TEXT NOT NULL UNIQUE,
    acquisition_run_key TEXT NOT NULL,
    episode_key TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    decision_as_of INTEGER NOT NULL,
    horizon_seconds INTEGER NOT NULL,
    target_at INTEGER NOT NULL,
    status TEXT NOT NULL,
    observed_at INTEGER,
    quote_key TEXT,
    error_type TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(acquisition_run_key, episode_key, horizon_seconds)
);

CREATE INDEX IF NOT EXISTS idx_opportunity_forward_outcomes_due
ON opportunity_forward_outcomes(status, target_at, acquisition_run_key, id);
"""

_SCHEMA_READY_PATHS: set[str] = set()
_SCHEMA_READY_LOCK = threading.Lock()


def _database_cache_key() -> str:
    path = database.settings.database_path
    try:
        return str(path.resolve())
    except AttributeError:
        return str(path)


def ensure_opportunity_forward_outcome_schema() -> None:
    cache_key = _database_cache_key()
    if cache_key in _SCHEMA_READY_PATHS:
        return
    with _SCHEMA_READY_LOCK:
        if cache_key in _SCHEMA_READY_PATHS:
            return
        with connection() as conn:
            conn.executescript(_SCHEMA)
        _SCHEMA_READY_PATHS.add(cache_key)


def _row_to_outcome(row) -> OpportunityForwardOutcome:
    return OpportunityForwardOutcome(
        outcome_key=str(row["outcome_key"]),
        acquisition_run_key=str(row["acquisition_run_key"]),
        episode_key=str(row["episode_key"]),
        token_mint=str(row["token_mint"]),
        decision_as_of=int(row["decision_as_of"]),
        horizon_seconds=int(row["horizon_seconds"]),
        target_at=int(row["target_at"]),
        status=str(row["status"]),
        observed_at=(int(row["observed_at"]) if row["observed_at"] is not None else None),
        quote_key=(str(row["quote_key"]) if row["quote_key"] is not None else None),
        error_type=(str(row["error_type"]) if row["error_type"] is not None else None),
        error_message=(str(row["error_message"]) if row["error_message"] is not None else None),
    )


def _outcome_key(episode: MarketOpportunityEpisode, horizon_seconds: int) -> str:
    return (
        f"forward-outcome:v1:{episode.acquisition_run_key}:{episode.episode_key}:"
        f"{int(horizon_seconds)}s"
    )


def schedule_opportunity_forward_outcomes(
    episode: MarketOpportunityEpisode,
    *,
    horizons_seconds: tuple[int, ...] = FORWARD_OUTCOME_HORIZONS_SECONDS,
) -> tuple[OpportunityForwardOutcome, ...]:
    """Persist exact +5m/+15m/+60m targets only after ``decision_as_of`` is frozen.

    Scheduling does not call a price/quote provider. The official collector can later attempt an
    executable observation at or after each target. Missing observations stay explicit; this store
    never substitutes a later candle or historical backfill.
    """

    if episode.decision_as_of is None:
        raise ValueError("cannot schedule forward outcomes before decision_as_of is frozen")
    if not episode.episode_key.strip() or not episode.token_mint.strip():
        raise ValueError("episode identity is incomplete")
    horizons = tuple(int(item) for item in horizons_seconds)
    if not horizons or any(item <= 0 for item in horizons) or len(set(horizons)) != len(horizons):
        raise ValueError("forward horizons must be unique positive seconds")

    ensure_opportunity_forward_outcome_schema()
    decision = int(episode.decision_as_of)
    with connection() as conn:
        for horizon in horizons:
            key = _outcome_key(episode, horizon)
            target = decision + horizon
            existing = conn.execute(
                """SELECT decision_as_of, target_at FROM opportunity_forward_outcomes
                WHERE acquisition_run_key=? AND episode_key=? AND horizon_seconds=?""",
                (episode.acquisition_run_key, episode.episode_key, horizon),
            ).fetchone()
            if existing is not None:
                if int(existing["decision_as_of"]) != decision or int(existing["target_at"]) != target:
                    raise ValueError("forward outcome schedule conflicts with frozen decision clock")
                continue
            conn.execute(
                """INSERT INTO opportunity_forward_outcomes(
                    outcome_key, acquisition_run_key, episode_key, token_mint,
                    decision_as_of, horizon_seconds, target_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')""",
                (
                    key,
                    episode.acquisition_run_key,
                    episode.episode_key,
                    episode.token_mint,
                    decision,
                    horizon,
                    target,
                ),
            )
    return load_opportunity_forward_outcomes(
        acquisition_run_key=episode.acquisition_run_key,
        episode_key=episode.episode_key,
    )


def complete_opportunity_forward_outcome(
    *,
    outcome_key: str,
    status: str,
    observed_at: int,
    quote_key: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> OpportunityForwardOutcome:
    key = str(outcome_key).strip()
    if not key:
        raise ValueError("outcome_key cannot be empty")
    final_status = str(status).strip()
    if final_status not in FORWARD_OUTCOME_FINAL_STATUSES:
        raise ValueError("unsupported forward outcome status")
    observed = int(observed_at)
    normalized_quote = str(quote_key).strip() if quote_key is not None else None
    if normalized_quote == "":
        normalized_quote = None
    if final_status == "AVAILABLE" and normalized_quote is None:
        raise ValueError("AVAILABLE forward outcome requires an executable quote artifact key")
    normalized_error_type = str(error_type).strip() if error_type is not None else None
    normalized_error_message = str(error_message).strip()[:1000] if error_message is not None else None

    ensure_opportunity_forward_outcome_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT status, target_at, observed_at, quote_key, error_type, error_message
            FROM opportunity_forward_outcomes WHERE outcome_key=?""",
            (key,),
        ).fetchone()
        if row is None:
            raise ValueError("forward outcome was not scheduled")
        if observed < int(row["target_at"]):
            raise ValueError("forward outcome observation cannot precede its exact target time")
        if str(row["status"]) != "PENDING":
            expected = (
                final_status,
                observed,
                normalized_quote,
                normalized_error_type,
                normalized_error_message,
            )
            actual = (
                str(row["status"]),
                int(row["observed_at"]),
                row["quote_key"],
                row["error_type"],
                row["error_message"],
            )
            if actual != expected:
                raise ValueError("completed forward outcome is immutable")
        else:
            conn.execute(
                """UPDATE opportunity_forward_outcomes
                SET status=?, observed_at=?, quote_key=?, error_type=?, error_message=?,
                    updated_at=CURRENT_TIMESTAMP WHERE outcome_key=?""",
                (
                    final_status,
                    observed,
                    normalized_quote,
                    normalized_error_type,
                    normalized_error_message,
                    key,
                ),
            )

    loaded = load_opportunity_forward_outcome(outcome_key=key)
    if loaded is None:
        raise RuntimeError("forward outcome disappeared after completion")
    return loaded


def load_opportunity_forward_outcome(*, outcome_key: str) -> OpportunityForwardOutcome | None:
    key = str(outcome_key).strip()
    if not key:
        raise ValueError("outcome_key cannot be empty")
    ensure_opportunity_forward_outcome_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT outcome_key, acquisition_run_key, episode_key, token_mint,
                decision_as_of, horizon_seconds, target_at, status, observed_at,
                quote_key, error_type, error_message
            FROM opportunity_forward_outcomes WHERE outcome_key=?""",
            (key,),
        ).fetchone()
    return _row_to_outcome(row) if row is not None else None


def load_opportunity_forward_outcomes(
    *,
    acquisition_run_key: str,
    episode_key: str | None = None,
) -> tuple[OpportunityForwardOutcome, ...]:
    run_key = str(acquisition_run_key).strip()
    if not run_key:
        raise ValueError("acquisition_run_key cannot be empty")
    ensure_opportunity_forward_outcome_schema()
    query = """SELECT outcome_key, acquisition_run_key, episode_key, token_mint,
        decision_as_of, horizon_seconds, target_at, status, observed_at,
        quote_key, error_type, error_message
        FROM opportunity_forward_outcomes WHERE acquisition_run_key=?"""
    params: list[object] = [run_key]
    if episode_key is not None:
        episode = str(episode_key).strip()
        if not episode:
            raise ValueError("episode_key cannot be empty")
        query += " AND episode_key=?"
        params.append(episode)
    query += " ORDER BY target_at, id"
    with connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return tuple(_row_to_outcome(row) for row in rows)
