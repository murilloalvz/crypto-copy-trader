"""Immutable denominator registry for Market Activity Dynamics discovery.

Every Market-First episode considered by a preregistered discovery run remains in the
cohort denominator even when its frozen T0 snapshot, Activity Dynamics evidence, or later
forward outcome is missing. This module stores no outcome or economic label.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import threading

from src import database
from src.database import connection
from src.market_activity_dynamics_v0 import MARKET_ACTIVITY_DYNAMICS_VERSION
from src.market_episode_research_snapshot_store import MarketEpisodeResearchSnapshotRecordV0
from src.market_opportunity_episode_store import MarketOpportunityEpisode


MARKET_ACTIVITY_DISCOVERY_COHORT_VERSION = "market_activity_discovery_cohort_v0"
COHORT_DISPOSITIONS = frozenset(
    {
        "ANALYZABLE_T0",
        "ACTIVITY_DYNAMICS_MISSING",
        "T0_SNAPSHOT_MISSING",
        "T0_NOT_FROZEN",
    }
)


@dataclass(frozen=True)
class MarketActivityDiscoveryCohortMemberV0:
    member_key: str
    method_version: str
    cohort_key: str
    acquisition_run_key: str
    episode_key: str
    token_mint: str
    first_trigger_observed_at: int
    decision_as_of: int | None
    first_considered_at: int
    disposition: str
    primary_analysis_eligible: bool
    snapshot_key: str | None
    snapshot_payload_sha256: str | None
    snapshot_method_version: str | None
    activity_dynamics_method_version: str | None
    reason_codes: tuple[str, ...]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_activity_discovery_cohort_v0 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_key TEXT NOT NULL UNIQUE,
    method_version TEXT NOT NULL,
    cohort_key TEXT NOT NULL,
    acquisition_run_key TEXT NOT NULL,
    episode_key TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    first_trigger_observed_at INTEGER NOT NULL,
    decision_as_of INTEGER,
    first_considered_at INTEGER NOT NULL,
    disposition TEXT NOT NULL,
    primary_analysis_eligible INTEGER NOT NULL,
    snapshot_key TEXT,
    snapshot_payload_sha256 TEXT,
    snapshot_method_version TEXT,
    activity_dynamics_method_version TEXT,
    reason_codes_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(cohort_key, acquisition_run_key, episode_key)
);

CREATE INDEX IF NOT EXISTS idx_market_activity_discovery_cohort_v0_run_disposition
ON market_activity_discovery_cohort_v0(
    cohort_key, acquisition_run_key, disposition, first_considered_at, id
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


def ensure_market_activity_discovery_cohort_schema_v0() -> None:
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


def _member_key(cohort_key: str, episode: MarketOpportunityEpisode) -> str:
    return (
        f"market-activity-discovery:v0:{cohort_key}:"
        f"{episode.acquisition_run_key}:{episode.episode_key}"
    )


def _row_to_member(row) -> MarketActivityDiscoveryCohortMemberV0:
    reasons = json.loads(str(row["reason_codes_json"]))
    if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
        raise RuntimeError("persisted discovery cohort reason_codes_json is invalid")
    return MarketActivityDiscoveryCohortMemberV0(
        member_key=str(row["member_key"]),
        method_version=str(row["method_version"]),
        cohort_key=str(row["cohort_key"]),
        acquisition_run_key=str(row["acquisition_run_key"]),
        episode_key=str(row["episode_key"]),
        token_mint=str(row["token_mint"]),
        first_trigger_observed_at=int(row["first_trigger_observed_at"]),
        decision_as_of=(int(row["decision_as_of"]) if row["decision_as_of"] is not None else None),
        first_considered_at=int(row["first_considered_at"]),
        disposition=str(row["disposition"]),
        primary_analysis_eligible=bool(int(row["primary_analysis_eligible"])),
        snapshot_key=(str(row["snapshot_key"]) if row["snapshot_key"] is not None else None),
        snapshot_payload_sha256=(
            str(row["snapshot_payload_sha256"])
            if row["snapshot_payload_sha256"] is not None
            else None
        ),
        snapshot_method_version=(
            str(row["snapshot_method_version"])
            if row["snapshot_method_version"] is not None
            else None
        ),
        activity_dynamics_method_version=(
            str(row["activity_dynamics_method_version"])
            if row["activity_dynamics_method_version"] is not None
            else None
        ),
        reason_codes=tuple(reasons),
    )


def _derive_disposition(
    *,
    episode: MarketOpportunityEpisode,
    snapshot_record: MarketEpisodeResearchSnapshotRecordV0 | None,
) -> tuple[str, tuple[str, ...], str | None]:
    if episode.decision_as_of is None:
        if snapshot_record is not None:
            raise ValueError("snapshot cannot be supplied for an episode without frozen decision_as_of")
        return "T0_NOT_FROZEN", ("decision_as_of_not_frozen_at_first_registration",), None

    if snapshot_record is None:
        return "T0_SNAPSHOT_MISSING", ("immutable_t0_snapshot_missing_at_first_registration",), None

    if snapshot_record.acquisition_run_key != episode.acquisition_run_key:
        raise ValueError("snapshot acquisition_run_key must match episode")
    if snapshot_record.episode_key != episode.episode_key:
        raise ValueError("snapshot episode_key must match episode")
    if snapshot_record.token_mint != episode.token_mint:
        raise ValueError("snapshot token_mint must match episode")
    if snapshot_record.decision_as_of != int(episode.decision_as_of):
        raise ValueError("snapshot decision_as_of must match frozen episode")

    payload = snapshot_record.payload()
    activity = payload.get("activity_dynamics")
    if activity is None:
        return (
            "ACTIVITY_DYNAMICS_MISSING",
            ("activity_dynamics_missing_from_immutable_t0",),
            None,
        )
    if not isinstance(activity, dict):
        raise ValueError("persisted activity_dynamics payload must be an object or null")
    method = str(activity.get("method_version") or "").strip()
    if method != MARKET_ACTIVITY_DYNAMICS_VERSION:
        raise ValueError("persisted activity_dynamics method_version is not the preregistered V0")
    if str(activity.get("token_mint") or "") != episode.token_mint:
        raise ValueError("persisted activity_dynamics token_mint must match episode")
    if int(activity.get("as_of", -1)) != int(episode.decision_as_of):
        raise ValueError("persisted activity_dynamics as_of must match frozen episode decision_as_of")
    return "ANALYZABLE_T0", (), method


def register_market_activity_discovery_member_v0(
    *,
    cohort_key: str,
    episode: MarketOpportunityEpisode,
    considered_at: int,
    snapshot_record: MarketEpisodeResearchSnapshotRecordV0 | None = None,
) -> MarketActivityDiscoveryCohortMemberV0:
    """Persist the first pre-outcome cohort disposition for one considered episode.

    The first disposition is immutable. A later retry may reproduce the same scientific identity,
    but it cannot upgrade a missing T0/activity record after future information has become available.
    """

    cohort = _required(cohort_key, "cohort_key")
    if not episode.acquisition_run_key.strip() or not episode.episode_key.strip() or not episode.token_mint.strip():
        raise ValueError("episode identity is incomplete")
    considered = int(considered_at)
    if considered < 0:
        raise ValueError("considered_at must be non-negative")
    if considered < int(episode.first_trigger_observed_at):
        raise ValueError("considered_at cannot precede first trigger observation")
    if episode.decision_as_of is not None and considered < int(episode.decision_as_of):
        raise ValueError("considered_at cannot precede frozen decision_as_of")

    disposition, reasons, activity_method = _derive_disposition(
        episode=episode,
        snapshot_record=snapshot_record,
    )
    if disposition not in COHORT_DISPOSITIONS:
        raise RuntimeError("derived unsupported cohort disposition")
    eligible = disposition == "ANALYZABLE_T0"
    key = _member_key(cohort, episode)

    snapshot_key = snapshot_record.snapshot_key if snapshot_record is not None else None
    snapshot_sha = snapshot_record.payload_sha256 if snapshot_record is not None else None
    snapshot_method = snapshot_record.snapshot_method_version if snapshot_record is not None else None
    identity = (
        MARKET_ACTIVITY_DISCOVERY_COHORT_VERSION,
        cohort,
        episode.acquisition_run_key,
        episode.episode_key,
        episode.token_mint,
        int(episode.first_trigger_observed_at),
        (int(episode.decision_as_of) if episode.decision_as_of is not None else None),
        disposition,
        eligible,
        snapshot_key,
        snapshot_sha,
        snapshot_method,
        activity_method,
        tuple(reasons),
    )

    ensure_market_activity_discovery_cohort_schema_v0()
    with connection() as conn:
        row = conn.execute(
            """SELECT member_key, method_version, cohort_key, acquisition_run_key, episode_key,
                token_mint, first_trigger_observed_at, decision_as_of, first_considered_at,
                disposition, primary_analysis_eligible, snapshot_key, snapshot_payload_sha256,
                snapshot_method_version, activity_dynamics_method_version, reason_codes_json
            FROM market_activity_discovery_cohort_v0
            WHERE cohort_key=? AND acquisition_run_key=? AND episode_key=?""",
            (cohort, episode.acquisition_run_key, episode.episode_key),
        ).fetchone()
        if row is not None:
            stored = _row_to_member(row)
            stored_identity = (
                stored.method_version,
                stored.cohort_key,
                stored.acquisition_run_key,
                stored.episode_key,
                stored.token_mint,
                stored.first_trigger_observed_at,
                stored.decision_as_of,
                stored.disposition,
                stored.primary_analysis_eligible,
                stored.snapshot_key,
                stored.snapshot_payload_sha256,
                stored.snapshot_method_version,
                stored.activity_dynamics_method_version,
                stored.reason_codes,
            )
            if stored.member_key != key or stored_identity != identity:
                raise ValueError("market activity discovery cohort disposition is immutable")
            return stored

        conn.execute(
            """INSERT INTO market_activity_discovery_cohort_v0(
                member_key, method_version, cohort_key, acquisition_run_key, episode_key,
                token_mint, first_trigger_observed_at, decision_as_of, first_considered_at,
                disposition, primary_analysis_eligible, snapshot_key, snapshot_payload_sha256,
                snapshot_method_version, activity_dynamics_method_version, reason_codes_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                key,
                MARKET_ACTIVITY_DISCOVERY_COHORT_VERSION,
                cohort,
                episode.acquisition_run_key,
                episode.episode_key,
                episode.token_mint,
                int(episode.first_trigger_observed_at),
                (int(episode.decision_as_of) if episode.decision_as_of is not None else None),
                considered,
                disposition,
                1 if eligible else 0,
                snapshot_key,
                snapshot_sha,
                snapshot_method,
                activity_method,
                json.dumps(list(reasons), separators=(",", ":")),
            ),
        )

    loaded = load_market_activity_discovery_members_v0(
        cohort_key=cohort,
        acquisition_run_key=episode.acquisition_run_key,
        episode_key=episode.episode_key,
    )
    if len(loaded) != 1:
        raise RuntimeError("discovery cohort member disappeared after persistence")
    return loaded[0]


def load_market_activity_discovery_members_v0(
    *,
    cohort_key: str,
    acquisition_run_key: str,
    episode_key: str | None = None,
) -> tuple[MarketActivityDiscoveryCohortMemberV0, ...]:
    cohort = _required(cohort_key, "cohort_key")
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    ensure_market_activity_discovery_cohort_schema_v0()
    query = """SELECT member_key, method_version, cohort_key, acquisition_run_key, episode_key,
        token_mint, first_trigger_observed_at, decision_as_of, first_considered_at,
        disposition, primary_analysis_eligible, snapshot_key, snapshot_payload_sha256,
        snapshot_method_version, activity_dynamics_method_version, reason_codes_json
        FROM market_activity_discovery_cohort_v0
        WHERE cohort_key=? AND acquisition_run_key=?"""
    params: list[object] = [cohort, run_key]
    if episode_key is not None:
        episode = _required(episode_key, "episode_key")
        query += " AND episode_key=?"
        params.append(episode)
    query += " ORDER BY first_considered_at, id"
    with connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return tuple(_row_to_member(row) for row in rows)
