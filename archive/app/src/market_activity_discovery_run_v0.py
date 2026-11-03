"""Immutable run registry for the preregistered Market Activity Dynamics discovery V0.

The admission window is frozen at six continuous wall-clock hours from run start. This
module stores only operational/scientific run identity and stop state; it stores no
market outcome, return, score, recommendation, or economic label.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading

from src import database
from src.database import connection


MARKET_ACTIVITY_DISCOVERY_RUN_VERSION = "market_activity_discovery_run_v0"
MARKET_ACTIVITY_DISCOVERY_ADMISSION_DURATION_SECONDS = 6 * 60 * 60
RUN_STATUSES = frozenset({"OPEN", "CLOSED", "INTERRUPTED"})


@dataclass(frozen=True)
class MarketActivityDiscoveryRunV0:
    acquisition_run_key: str
    cohort_key: str
    method_version: str
    started_at: int
    admission_closes_at: int
    status: str
    closed_at: int | None
    interruption_reason: str | None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_activity_discovery_runs_v0 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acquisition_run_key TEXT NOT NULL UNIQUE,
    cohort_key TEXT NOT NULL UNIQUE,
    method_version TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    admission_closes_at INTEGER NOT NULL,
    status TEXT NOT NULL,
    closed_at INTEGER,
    interruption_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_SCHEMA_READY_PATHS: set[str] = set()
_SCHEMA_READY_LOCK = threading.Lock()


def _database_cache_key() -> str:
    path = database.settings.database_path
    try:
        return str(path.resolve())
    except AttributeError:
        return str(path)


def ensure_market_activity_discovery_run_schema_v0() -> None:
    cache_key = _database_cache_key()
    if cache_key in _SCHEMA_READY_PATHS:
        return
    with _SCHEMA_READY_LOCK:
        if cache_key in _SCHEMA_READY_PATHS:
            return
        with connection() as conn:
            conn.executescript(_SCHEMA)
        _SCHEMA_READY_PATHS.add(cache_key)


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _row_to_run(row) -> MarketActivityDiscoveryRunV0:
    status = str(row["status"])
    if status not in RUN_STATUSES:
        raise RuntimeError("persisted market activity discovery run status is invalid")
    return MarketActivityDiscoveryRunV0(
        acquisition_run_key=str(row["acquisition_run_key"]),
        cohort_key=str(row["cohort_key"]),
        method_version=str(row["method_version"]),
        started_at=int(row["started_at"]),
        admission_closes_at=int(row["admission_closes_at"]),
        status=status,
        closed_at=(int(row["closed_at"]) if row["closed_at"] is not None else None),
        interruption_reason=(
            str(row["interruption_reason"]) if row["interruption_reason"] is not None else None
        ),
    )


def create_market_activity_discovery_run_v0(
    *,
    acquisition_run_key: str,
    cohort_key: str,
    started_at: int,
) -> MarketActivityDiscoveryRunV0:
    """Create the exact six-hour admission window idempotently.

    Reusing either run key or cohort key with a different identity fails closed. The
    duration cannot be caller-tuned because it is part of the preregistered protocol.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    cohort = _required(cohort_key, "cohort_key")
    start = int(started_at)
    if start < 0:
        raise ValueError("started_at must be non-negative")
    closes = start + MARKET_ACTIVITY_DISCOVERY_ADMISSION_DURATION_SECONDS

    ensure_market_activity_discovery_run_schema_v0()
    with connection() as conn:
        by_run = conn.execute(
            """SELECT acquisition_run_key, cohort_key, method_version, started_at,
                admission_closes_at, status, closed_at, interruption_reason
            FROM market_activity_discovery_runs_v0 WHERE acquisition_run_key=?""",
            (run_key,),
        ).fetchone()
        by_cohort = conn.execute(
            """SELECT acquisition_run_key, cohort_key, method_version, started_at,
                admission_closes_at, status, closed_at, interruption_reason
            FROM market_activity_discovery_runs_v0 WHERE cohort_key=?""",
            (cohort,),
        ).fetchone()

        existing_rows = [row for row in (by_run, by_cohort) if row is not None]
        if existing_rows:
            first = _row_to_run(existing_rows[0])
            expected = (
                run_key,
                cohort,
                MARKET_ACTIVITY_DISCOVERY_RUN_VERSION,
                start,
                closes,
            )
            actual = (
                first.acquisition_run_key,
                first.cohort_key,
                first.method_version,
                first.started_at,
                first.admission_closes_at,
            )
            if actual != expected:
                raise ValueError("market activity discovery run identity is immutable")
            if any(_row_to_run(row) != first for row in existing_rows[1:]):
                raise ValueError("run/cohort keys resolve to conflicting persisted runs")
            return first

        conn.execute(
            """INSERT INTO market_activity_discovery_runs_v0(
                acquisition_run_key, cohort_key, method_version, started_at,
                admission_closes_at, status
            ) VALUES (?, ?, ?, ?, ?, 'OPEN')""",
            (
                run_key,
                cohort,
                MARKET_ACTIVITY_DISCOVERY_RUN_VERSION,
                start,
                closes,
            ),
        )

    loaded = load_market_activity_discovery_run_v0(acquisition_run_key=run_key)
    if loaded is None:
        raise RuntimeError("market activity discovery run disappeared after persistence")
    return loaded


def load_market_activity_discovery_run_v0(
    *,
    acquisition_run_key: str,
) -> MarketActivityDiscoveryRunV0 | None:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    ensure_market_activity_discovery_run_schema_v0()
    with connection() as conn:
        row = conn.execute(
            """SELECT acquisition_run_key, cohort_key, method_version, started_at,
                admission_closes_at, status, closed_at, interruption_reason
            FROM market_activity_discovery_runs_v0 WHERE acquisition_run_key=?""",
            (run_key,),
        ).fetchone()
    return _row_to_run(row) if row is not None else None


def assert_market_activity_discovery_admission_open_v0(
    run: MarketActivityDiscoveryRunV0,
    *,
    considered_at: int,
) -> None:
    """Fail before scientific admission when the fixed run window is not open."""

    considered = int(considered_at)
    if considered < 0:
        raise ValueError("considered_at must be non-negative")
    if run.method_version != MARKET_ACTIVITY_DISCOVERY_RUN_VERSION:
        raise ValueError("run method_version is not the preregistered discovery V0")
    if run.status != "OPEN":
        raise ValueError("market activity discovery run is not open for admissions")
    if considered < run.started_at:
        raise ValueError("considered_at cannot precede discovery run start")
    if considered >= run.admission_closes_at:
        raise ValueError("considered_at is outside the preregistered six-hour admission window")


def close_market_activity_discovery_run_v0(
    *,
    acquisition_run_key: str,
    observed_at: int,
) -> MarketActivityDiscoveryRunV0:
    """Close normally only after the preregistered admission deadline has elapsed."""

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    observed = int(observed_at)
    if observed < 0:
        raise ValueError("observed_at must be non-negative")
    ensure_market_activity_discovery_run_schema_v0()
    with connection() as conn:
        row = conn.execute(
            """SELECT acquisition_run_key, cohort_key, method_version, started_at,
                admission_closes_at, status, closed_at, interruption_reason
            FROM market_activity_discovery_runs_v0 WHERE acquisition_run_key=?""",
            (run_key,),
        ).fetchone()
        if row is None:
            raise ValueError("market activity discovery run not found")
        run = _row_to_run(row)
        if run.status == "CLOSED":
            return run
        if run.status == "INTERRUPTED":
            raise ValueError("interrupted discovery run cannot be promoted to CLOSED")
        if observed < run.admission_closes_at:
            raise ValueError("normal close is forbidden before preregistered admission deadline")
        conn.execute(
            """UPDATE market_activity_discovery_runs_v0
            SET status='CLOSED', closed_at=?, updated_at=CURRENT_TIMESTAMP
            WHERE acquisition_run_key=?""",
            (observed, run_key),
        )

    loaded = load_market_activity_discovery_run_v0(acquisition_run_key=run_key)
    if loaded is None:
        raise RuntimeError("market activity discovery run disappeared after close")
    return loaded


def interrupt_market_activity_discovery_run_v0(
    *,
    acquisition_run_key: str,
    observed_at: int,
    reason: str,
) -> MarketActivityDiscoveryRunV0:
    """Record an operational interruption without pretending the run completed."""

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    observed = int(observed_at)
    if observed < 0:
        raise ValueError("observed_at must be non-negative")
    normalized_reason = _required(reason, "reason")[:1000]
    ensure_market_activity_discovery_run_schema_v0()
    with connection() as conn:
        row = conn.execute(
            """SELECT acquisition_run_key, cohort_key, method_version, started_at,
                admission_closes_at, status, closed_at, interruption_reason
            FROM market_activity_discovery_runs_v0 WHERE acquisition_run_key=?""",
            (run_key,),
        ).fetchone()
        if row is None:
            raise ValueError("market activity discovery run not found")
        run = _row_to_run(row)
        if observed < run.started_at:
            raise ValueError("interruption cannot precede discovery run start")
        if run.status == "CLOSED":
            raise ValueError("closed discovery run cannot be reclassified as interrupted")
        if run.status == "INTERRUPTED":
            if run.closed_at != observed or run.interruption_reason != normalized_reason:
                raise ValueError("interrupted discovery run state is immutable")
            return run
        conn.execute(
            """UPDATE market_activity_discovery_runs_v0
            SET status='INTERRUPTED', closed_at=?, interruption_reason=?,
                updated_at=CURRENT_TIMESTAMP WHERE acquisition_run_key=?""",
            (observed, normalized_reason, run_key),
        )

    loaded = load_market_activity_discovery_run_v0(acquisition_run_key=run_key)
    if loaded is None:
        raise RuntimeError("market activity discovery run disappeared after interruption")
    return loaded
