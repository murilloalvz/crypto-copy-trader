from dataclasses import dataclass
import threading

from src import database
from src.database import connection


@dataclass(frozen=True)
class OpportunityEnrichmentAttempt:
    acquisition_run_key: str
    episode_key: str
    admitted_at: int
    status: str
    completed_at: int | None
    decision_as_of: int | None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunity_enrichment_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acquisition_run_key TEXT NOT NULL,
    episode_key TEXT NOT NULL,
    admitted_at INTEGER NOT NULL,
    status TEXT NOT NULL,
    completed_at INTEGER,
    decision_as_of INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(acquisition_run_key, episode_key)
);

CREATE INDEX IF NOT EXISTS idx_opportunity_enrichment_attempts_run_status
ON opportunity_enrichment_attempts(acquisition_run_key, status, admitted_at, id);
"""

_SCHEMA_READY_PATHS: set[str] = set()
_SCHEMA_READY_LOCK = threading.Lock()


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _database_cache_key() -> str:
    path = database.settings.database_path
    try:
        return str(path.resolve())
    except AttributeError:
        return str(path)


def ensure_opportunity_enrichment_schema() -> None:
    cache_key = _database_cache_key()
    if cache_key in _SCHEMA_READY_PATHS:
        return
    with _SCHEMA_READY_LOCK:
        if cache_key in _SCHEMA_READY_PATHS:
            return
        with connection() as conn:
            conn.executescript(_SCHEMA)
        _SCHEMA_READY_PATHS.add(cache_key)


def admit_opportunity_episode(
    *,
    acquisition_run_key: str,
    episode_key: str,
    admitted_at: int,
) -> bool:
    """Admit an episode exactly once per acquisition run.

    Raw radar continuation hits never reach this store. Repeated process delivery/restart attempts
    for the same episode are idempotent, which prevents duplicate expensive enrichment calls.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    episode = _required(episode_key, "episode_key")
    timestamp = int(admitted_at)
    if timestamp < 0:
        raise ValueError("admitted_at must be non-negative")
    ensure_opportunity_enrichment_schema()

    with connection() as conn:
        existing = conn.execute(
            """SELECT admitted_at FROM opportunity_enrichment_attempts
            WHERE acquisition_run_key=? AND episode_key=?""",
            (run_key, episode),
        ).fetchone()
        if existing is not None:
            if timestamp < int(existing["admitted_at"]):
                raise ValueError("enrichment replay cannot backdate admission")
            return False
        conn.execute(
            """INSERT INTO opportunity_enrichment_attempts(
                acquisition_run_key, episode_key, admitted_at, status
            ) VALUES (?, ?, ?, 'ADMITTED')""",
            (run_key, episode, timestamp),
        )
        return True


def complete_opportunity_enrichment(
    *,
    acquisition_run_key: str,
    episode_key: str,
    completed_at: int,
    decision_as_of: int,
) -> OpportunityEnrichmentAttempt:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    episode = _required(episode_key, "episode_key")
    completed = int(completed_at)
    decision = int(decision_as_of)
    if completed < 0 or decision < 0 or decision > completed:
        raise ValueError("invalid enrichment completion clocks")
    ensure_opportunity_enrichment_schema()

    with connection() as conn:
        row = conn.execute(
            """SELECT admitted_at, status, completed_at, decision_as_of
            FROM opportunity_enrichment_attempts
            WHERE acquisition_run_key=? AND episode_key=?""",
            (run_key, episode),
        ).fetchone()
        if row is None:
            raise ValueError("episode enrichment was not admitted")
        admitted = int(row["admitted_at"])
        if decision < admitted or completed < admitted:
            raise ValueError("completion cannot precede admission")
        if str(row["status"]) == "COMPLETED":
            if int(row["completed_at"]) != completed or int(row["decision_as_of"]) != decision:
                raise ValueError("completed enrichment is immutable")
        else:
            conn.execute(
                """UPDATE opportunity_enrichment_attempts
                SET status='COMPLETED', completed_at=?, decision_as_of=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE acquisition_run_key=? AND episode_key=?""",
                (completed, decision, run_key, episode),
            )

    result = load_opportunity_enrichment_attempt(
        acquisition_run_key=run_key,
        episode_key=episode,
    )
    if result is None:
        raise RuntimeError("enrichment attempt disappeared after completion")
    return result


def load_opportunity_enrichment_attempt(
    *,
    acquisition_run_key: str,
    episode_key: str,
) -> OpportunityEnrichmentAttempt | None:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    episode = _required(episode_key, "episode_key")
    ensure_opportunity_enrichment_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT acquisition_run_key, episode_key, admitted_at, status,
                completed_at, decision_as_of
            FROM opportunity_enrichment_attempts
            WHERE acquisition_run_key=? AND episode_key=?""",
            (run_key, episode),
        ).fetchone()
    if row is None:
        return None
    return OpportunityEnrichmentAttempt(
        acquisition_run_key=str(row["acquisition_run_key"]),
        episode_key=str(row["episode_key"]),
        admitted_at=int(row["admitted_at"]),
        status=str(row["status"]),
        completed_at=(int(row["completed_at"]) if row["completed_at"] is not None else None),
        decision_as_of=(int(row["decision_as_of"]) if row["decision_as_of"] is not None else None),
    )
