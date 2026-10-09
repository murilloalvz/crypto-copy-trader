from __future__ import annotations

from dataclasses import dataclass
import json
import threading

from src import database
from src.database import connection


FINAL_PROVIDER_STATUSES = {
    "AVAILABLE",
    "UNAVAILABLE",
    "CONFIG_MISSING",
    "PROVIDER_ERROR",
    "METADATA_ERROR",
    "NORMALIZATION_ERROR",
}


@dataclass(frozen=True)
class OpportunityProviderAttempt:
    attempt_key: str
    acquisition_run_key: str
    episode_key: str
    provider: str
    purpose: str
    started_at: int
    status: str
    completed_at: int | None
    artifact_key: str | None
    error_type: str | None
    error_message: str | None
    details: dict


_SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunity_provider_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_key TEXT NOT NULL UNIQUE,
    acquisition_run_key TEXT NOT NULL,
    episode_key TEXT NOT NULL,
    provider TEXT NOT NULL,
    purpose TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    status TEXT NOT NULL,
    completed_at INTEGER,
    artifact_key TEXT,
    error_type TEXT,
    error_message TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(acquisition_run_key, episode_key, provider, purpose)
);

CREATE INDEX IF NOT EXISTS idx_opportunity_provider_attempts_run_status
ON opportunity_provider_attempts(acquisition_run_key, provider, purpose, status, started_at, id);
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


def ensure_opportunity_provider_attempt_schema() -> None:
    cache_key = _database_cache_key()
    if cache_key in _SCHEMA_READY_PATHS:
        return
    with _SCHEMA_READY_LOCK:
        if cache_key in _SCHEMA_READY_PATHS:
            return
        with connection() as conn:
            conn.executescript(_SCHEMA)
        _SCHEMA_READY_PATHS.add(cache_key)


def _row_to_attempt(row) -> OpportunityProviderAttempt:
    try:
        details = json.loads(str(row["details_json"] or "{}"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("provider attempt contains invalid details_json") from exc
    if not isinstance(details, dict):
        raise RuntimeError("provider attempt details_json must decode to an object")
    return OpportunityProviderAttempt(
        attempt_key=str(row["attempt_key"]),
        acquisition_run_key=str(row["acquisition_run_key"]),
        episode_key=str(row["episode_key"]),
        provider=str(row["provider"]),
        purpose=str(row["purpose"]),
        started_at=int(row["started_at"]),
        status=str(row["status"]),
        completed_at=(int(row["completed_at"]) if row["completed_at"] is not None else None),
        artifact_key=(str(row["artifact_key"]) if row["artifact_key"] is not None else None),
        error_type=(str(row["error_type"]) if row["error_type"] is not None else None),
        error_message=(
            str(row["error_message"]) if row["error_message"] is not None else None
        ),
        details=details,
    )


def begin_provider_attempt(
    *,
    attempt_key: str,
    acquisition_run_key: str,
    episode_key: str,
    provider: str,
    purpose: str,
    started_at: int,
) -> bool:
    """Persist STARTED before provider I/O and return True only for the first admission.

    Replays/restarts cannot silently issue the same expensive provider call twice. A process crash
    leaves a visible STARTED row that must be reconciled explicitly instead of being treated as
    provider absence.
    """

    key = _required(attempt_key, "attempt_key")
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    episode = _required(episode_key, "episode_key")
    provider_name = _required(provider, "provider")
    purpose_name = _required(purpose, "purpose")
    started = int(started_at)
    if started < 0:
        raise ValueError("started_at must be non-negative")
    ensure_opportunity_provider_attempt_schema()

    with connection() as conn:
        existing = conn.execute(
            """SELECT attempt_key, started_at
            FROM opportunity_provider_attempts
            WHERE acquisition_run_key=? AND episode_key=? AND provider=? AND purpose=?""",
            (run_key, episode, provider_name, purpose_name),
        ).fetchone()
        if existing is not None:
            if str(existing["attempt_key"]) != key:
                raise ValueError("provider attempt identity conflicts with existing episode attempt")
            if started < int(existing["started_at"]):
                raise ValueError("provider attempt replay cannot backdate started_at")
            return False
        conn.execute(
            """INSERT INTO opportunity_provider_attempts(
                attempt_key, acquisition_run_key, episode_key, provider, purpose,
                started_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, 'STARTED')""",
            (key, run_key, episode, provider_name, purpose_name, started),
        )
    return True


def complete_provider_attempt(
    *,
    attempt_key: str,
    status: str,
    completed_at: int,
    artifact_key: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    details: dict | None = None,
) -> OpportunityProviderAttempt:
    key = _required(attempt_key, "attempt_key")
    final_status = _required(status, "status")
    if final_status not in FINAL_PROVIDER_STATUSES:
        raise ValueError("unsupported final provider status")
    completed = int(completed_at)
    if completed < 0:
        raise ValueError("completed_at must be non-negative")
    normalized_artifact = None if artifact_key is None else _required(artifact_key, "artifact_key")
    normalized_error_type = None if error_type is None else _required(error_type, "error_type")
    normalized_error_message = (
        None if error_message is None else str(error_message).strip()[:1000] or None
    )
    details_json = json.dumps(details or {}, sort_keys=True, separators=(",", ":"))
    ensure_opportunity_provider_attempt_schema()

    with connection() as conn:
        row = conn.execute(
            """SELECT started_at, status, completed_at, artifact_key,
                error_type, error_message, details_json
            FROM opportunity_provider_attempts WHERE attempt_key=?""",
            (key,),
        ).fetchone()
        if row is None:
            raise ValueError("provider attempt was not started")
        started = int(row["started_at"])
        if completed < started:
            raise ValueError("provider completion cannot precede start")
        existing_status = str(row["status"])
        if existing_status != "STARTED":
            expected = (
                final_status,
                completed,
                normalized_artifact,
                normalized_error_type,
                normalized_error_message,
                details_json,
            )
            actual = (
                existing_status,
                int(row["completed_at"]),
                row["artifact_key"],
                row["error_type"],
                row["error_message"],
                str(row["details_json"]),
            )
            if actual != expected:
                raise ValueError("completed provider attempt is immutable")
        else:
            conn.execute(
                """UPDATE opportunity_provider_attempts
                SET status=?, completed_at=?, artifact_key=?, error_type=?, error_message=?,
                    details_json=?, updated_at=CURRENT_TIMESTAMP
                WHERE attempt_key=?""",
                (
                    final_status,
                    completed,
                    normalized_artifact,
                    normalized_error_type,
                    normalized_error_message,
                    details_json,
                    key,
                ),
            )

    result = load_provider_attempt(attempt_key=key)
    if result is None:
        raise RuntimeError("provider attempt disappeared after completion")
    return result


def load_provider_attempt(*, attempt_key: str) -> OpportunityProviderAttempt | None:
    key = _required(attempt_key, "attempt_key")
    ensure_opportunity_provider_attempt_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT attempt_key, acquisition_run_key, episode_key, provider, purpose,
                started_at, status, completed_at, artifact_key, error_type, error_message,
                details_json
            FROM opportunity_provider_attempts WHERE attempt_key=?""",
            (key,),
        ).fetchone()
    return _row_to_attempt(row) if row is not None else None


def list_provider_attempts(
    *,
    acquisition_run_key: str,
    provider: str | None = None,
    purpose: str | None = None,
) -> tuple[OpportunityProviderAttempt, ...]:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    clauses = ["acquisition_run_key=?"]
    params: list[object] = [run_key]
    if provider is not None:
        clauses.append("provider=?")
        params.append(_required(provider, "provider"))
    if purpose is not None:
        clauses.append("purpose=?")
        params.append(_required(purpose, "purpose"))
    ensure_opportunity_provider_attempt_schema()
    query = """SELECT attempt_key, acquisition_run_key, episode_key, provider, purpose,
        started_at, status, completed_at, artifact_key, error_type, error_message,
        details_json
        FROM opportunity_provider_attempts WHERE """ + " AND ".join(clauses)
    query += " ORDER BY started_at, id"
    with connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return tuple(_row_to_attempt(row) for row in rows)
