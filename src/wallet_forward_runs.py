import json
from dataclasses import dataclass

from src.database import connection


RUN_STATUSES = {"ACTIVE", "COMPLETED", "ABORTED"}
QUOTE_MODES = {"none", "proxy", "assembled_candidate"}


@dataclass(frozen=True)
class WalletForwardRun:
    run_key: str
    started_at: int
    ended_at: int | None
    baseline_observation_id: int
    end_observation_id: int | None
    cohort: tuple[str, ...]
    interval_seconds: int
    quote_delays_seconds: tuple[int, ...]
    with_jupiter_quotes: bool
    copy_size_usd: float
    quote_mode: str
    status: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS wallet_forward_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_key TEXT NOT NULL UNIQUE,
    started_at INTEGER NOT NULL,
    ended_at INTEGER,
    baseline_observation_id INTEGER NOT NULL,
    end_observation_id INTEGER,
    cohort_json TEXT NOT NULL,
    interval_seconds INTEGER NOT NULL,
    quote_delays_json TEXT NOT NULL,
    with_jupiter_quotes INTEGER NOT NULL,
    copy_size_usd REAL NOT NULL,
    quote_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wallet_forward_runs_started
ON wallet_forward_runs(started_at, id);
"""


def ensure_wallet_forward_run_schema() -> None:
    with connection() as conn:
        conn.executescript(_SCHEMA)


def _normalize_cohort(cohort: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    addresses = tuple(dict.fromkeys(str(item).strip() for item in cohort if str(item).strip()))
    if not addresses:
        raise ValueError("forward run cohort cannot be empty")
    return addresses


def _normalize_delays(delays: tuple[int, ...] | list[int]) -> tuple[int, ...]:
    values = tuple(dict.fromkeys(int(item) for item in delays))
    if any(item < 0 for item in values):
        raise ValueError("quote delays must be non-negative")
    return values


def create_wallet_forward_run(
    *,
    run_key: str,
    started_at: int,
    baseline_observation_id: int,
    cohort: tuple[str, ...] | list[str],
    interval_seconds: int,
    quote_delays_seconds: tuple[int, ...] | list[int],
    with_jupiter_quotes: bool,
    copy_size_usd: float,
    quote_mode: str,
) -> WalletForwardRun:
    key = run_key.strip()
    if not key:
        raise ValueError("run_key cannot be empty")
    if started_at < 0 or baseline_observation_id < 0:
        raise ValueError("run timestamps and baseline id must be non-negative")
    if interval_seconds < 10:
        raise ValueError("interval_seconds must be >= 10")
    if copy_size_usd <= 0:
        raise ValueError("copy_size_usd must be positive")
    if quote_mode not in QUOTE_MODES:
        raise ValueError("invalid quote_mode")
    if with_jupiter_quotes and quote_mode == "none":
        raise ValueError("Jupiter-enabled run cannot use quote_mode=none")
    if not with_jupiter_quotes and quote_mode != "none":
        raise ValueError("run without Jupiter quotes must use quote_mode=none")

    addresses = _normalize_cohort(cohort)
    delays = _normalize_delays(quote_delays_seconds)
    if with_jupiter_quotes and not delays:
        raise ValueError("Jupiter-enabled run requires quote delays")

    ensure_wallet_forward_run_schema()
    with connection() as conn:
        try:
            conn.execute(
                """INSERT INTO wallet_forward_runs(
                    run_key, started_at, baseline_observation_id, cohort_json,
                    interval_seconds, quote_delays_json, with_jupiter_quotes,
                    copy_size_usd, quote_mode, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE')""",
                (
                    key,
                    started_at,
                    baseline_observation_id,
                    json.dumps(addresses),
                    interval_seconds,
                    json.dumps(delays),
                    int(with_jupiter_quotes),
                    copy_size_usd,
                    quote_mode,
                ),
            )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise ValueError(f"wallet forward run already exists: {key}") from exc
            raise
    run = get_wallet_forward_run(key)
    if run is None:  # defensive; insert above should make this impossible
        raise RuntimeError("failed to persist wallet forward run")
    return run


def finish_wallet_forward_run(
    run_key: str,
    *,
    status: str,
    ended_at: int,
    end_observation_id: int,
) -> WalletForwardRun:
    key = run_key.strip()
    if not key:
        raise ValueError("run_key cannot be empty")
    if status not in {"COMPLETED", "ABORTED"}:
        raise ValueError("finish status must be COMPLETED or ABORTED")
    if ended_at < 0 or end_observation_id < 0:
        raise ValueError("run end values must be non-negative")

    current = get_wallet_forward_run(key)
    if current is None:
        raise ValueError(f"wallet forward run not found: {key}")
    if ended_at < current.started_at:
        raise ValueError("ended_at cannot precede started_at")
    if end_observation_id < current.baseline_observation_id:
        raise ValueError("end_observation_id cannot precede baseline")

    ensure_wallet_forward_run_schema()
    with connection() as conn:
        conn.execute(
            """UPDATE wallet_forward_runs
            SET status=?, ended_at=?, end_observation_id=?, updated_at=CURRENT_TIMESTAMP
            WHERE run_key=?""",
            (status, ended_at, end_observation_id, key),
        )
    finished = get_wallet_forward_run(key)
    if finished is None:
        raise RuntimeError("wallet forward run disappeared after update")
    return finished


def get_wallet_forward_run(run_key: str) -> WalletForwardRun | None:
    key = run_key.strip()
    if not key:
        raise ValueError("run_key cannot be empty")
    ensure_wallet_forward_run_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT run_key, started_at, ended_at, baseline_observation_id,
                end_observation_id, cohort_json, interval_seconds, quote_delays_json,
                with_jupiter_quotes, copy_size_usd, quote_mode, status
            FROM wallet_forward_runs WHERE run_key=?""",
            (key,),
        ).fetchone()
    return _row_to_run(row) if row is not None else None


def latest_wallet_forward_run(*, completed_only: bool = False) -> WalletForwardRun | None:
    ensure_wallet_forward_run_schema()
    query = """SELECT run_key, started_at, ended_at, baseline_observation_id,
        end_observation_id, cohort_json, interval_seconds, quote_delays_json,
        with_jupiter_quotes, copy_size_usd, quote_mode, status
        FROM wallet_forward_runs"""
    params: tuple[object, ...] = ()
    if completed_only:
        query += " WHERE status='COMPLETED'"
    query += " ORDER BY started_at DESC, id DESC LIMIT 1"
    with connection() as conn:
        row = conn.execute(query, params).fetchone()
    return _row_to_run(row) if row is not None else None


def _row_to_run(row) -> WalletForwardRun:
    cohort = tuple(str(item) for item in json.loads(str(row["cohort_json"])))
    delays = tuple(int(item) for item in json.loads(str(row["quote_delays_json"])))
    status = str(row["status"])
    quote_mode = str(row["quote_mode"])
    if status not in RUN_STATUSES:
        raise ValueError(f"invalid persisted wallet forward run status: {status}")
    if quote_mode not in QUOTE_MODES:
        raise ValueError(f"invalid persisted wallet forward quote mode: {quote_mode}")
    return WalletForwardRun(
        run_key=str(row["run_key"]),
        started_at=int(row["started_at"]),
        ended_at=(int(row["ended_at"]) if row["ended_at"] is not None else None),
        baseline_observation_id=int(row["baseline_observation_id"]),
        end_observation_id=(
            int(row["end_observation_id"])
            if row["end_observation_id"] is not None
            else None
        ),
        cohort=cohort,
        interval_seconds=int(row["interval_seconds"]),
        quote_delays_seconds=delays,
        with_jupiter_quotes=bool(row["with_jupiter_quotes"]),
        copy_size_usd=float(row["copy_size_usd"]),
        quote_mode=quote_mode,
        status=status,
    )
