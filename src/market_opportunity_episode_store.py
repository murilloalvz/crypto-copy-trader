from dataclasses import dataclass
import json
import threading

from src import database
from src.database import connection


DEFAULT_MARKET_EPISODE_WINDOW_SECONDS = 60


@dataclass(frozen=True)
class MarketOpportunityEpisode:
    episode_key: str
    acquisition_run_key: str
    token_mint: str
    first_trigger_key: str
    first_trigger_kind: str
    first_trigger_direction: str
    first_trigger_chain_time: int
    first_trigger_observed_at: int
    episode_closes_at: int
    decision_as_of: int | None


@dataclass(frozen=True)
class MarketOpportunityEpisodeTrigger:
    acquisition_run_key: str
    episode_key: str
    trigger_key: str
    token_mint: str
    trigger_kind: str
    direction: str
    chain_time: int
    observed_at: int
    method_version: str
    venue: str | None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_opportunity_episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_key TEXT NOT NULL UNIQUE,
    acquisition_run_key TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    first_trigger_key TEXT NOT NULL,
    first_trigger_kind TEXT NOT NULL,
    first_trigger_direction TEXT NOT NULL,
    first_trigger_chain_time INTEGER NOT NULL,
    first_trigger_observed_at INTEGER NOT NULL,
    episode_closes_at INTEGER NOT NULL,
    decision_as_of INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(acquisition_run_key, first_trigger_key)
);

CREATE INDEX IF NOT EXISTS idx_market_opportunity_episodes_run_token_time
ON market_opportunity_episodes(
    acquisition_run_key, token_mint, first_trigger_observed_at, id
);

CREATE TABLE IF NOT EXISTS market_opportunity_episode_triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acquisition_run_key TEXT NOT NULL,
    episode_key TEXT NOT NULL,
    trigger_key TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    trigger_kind TEXT NOT NULL,
    direction TEXT NOT NULL,
    chain_time INTEGER NOT NULL,
    observed_at INTEGER NOT NULL,
    method_version TEXT NOT NULL,
    venue TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(acquisition_run_key, trigger_key)
);

CREATE INDEX IF NOT EXISTS idx_market_opportunity_episode_triggers_episode
ON market_opportunity_episode_triggers(episode_key, observed_at, id);

CREATE TABLE IF NOT EXISTS market_trigger_replay_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acquisition_run_key TEXT NOT NULL,
    trigger_key TEXT NOT NULL,
    episode_key TEXT NOT NULL,
    stored_observed_at INTEGER NOT NULL,
    incoming_observed_at INTEGER NOT NULL,
    stored_identity_json TEXT NOT NULL,
    incoming_identity_json TEXT NOT NULL,
    canonical_action TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_market_trigger_replay_conflicts_run
ON market_trigger_replay_conflicts(acquisition_run_key, trigger_key, id);
"""

_SCHEMA_READY_PATHS: set[str] = set()
_SCHEMA_READY_LOCK = threading.Lock()


def _database_cache_key() -> str:
    path = database.settings.database_path
    try:
        return str(path.resolve())
    except AttributeError:
        return str(path)


def ensure_market_opportunity_episode_schema() -> None:
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


def _row_to_episode(row) -> MarketOpportunityEpisode:
    return MarketOpportunityEpisode(
        episode_key=str(row["episode_key"]),
        acquisition_run_key=str(row["acquisition_run_key"]),
        token_mint=str(row["token_mint"]),
        first_trigger_key=str(row["first_trigger_key"]),
        first_trigger_kind=str(row["first_trigger_kind"]),
        first_trigger_direction=str(row["first_trigger_direction"]),
        first_trigger_chain_time=int(row["first_trigger_chain_time"]),
        first_trigger_observed_at=int(row["first_trigger_observed_at"]),
        episode_closes_at=int(row["episode_closes_at"]),
        decision_as_of=(int(row["decision_as_of"]) if row["decision_as_of"] is not None else None),
    )


def _load_episode_row(conn, episode_key: str):
    return conn.execute(
        """SELECT episode_key, acquisition_run_key, token_mint,
            first_trigger_key, first_trigger_kind, first_trigger_direction,
            first_trigger_chain_time, first_trigger_observed_at,
            episode_closes_at, decision_as_of
        FROM market_opportunity_episodes WHERE episode_key=?""",
        (episode_key,),
    ).fetchone()


def _record_trigger_conflict(
    conn,
    *,
    acquisition_run_key: str,
    trigger_key: str,
    episode_key: str,
    stored_observed_at: int,
    incoming_observed_at: int,
    stored_identity: tuple,
    incoming_identity: tuple,
    canonical_action: str,
) -> None:
    conn.execute(
        """INSERT INTO market_trigger_replay_conflicts(
            acquisition_run_key, trigger_key, episode_key,
            stored_observed_at, incoming_observed_at,
            stored_identity_json, incoming_identity_json, canonical_action
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            acquisition_run_key,
            trigger_key,
            episode_key,
            int(stored_observed_at),
            int(incoming_observed_at),
            json.dumps(stored_identity, separators=(",", ":")),
            json.dumps(incoming_identity, separators=(",", ":")),
            canonical_action,
        ),
    )


def get_market_opportunity_episode(episode_key: str) -> MarketOpportunityEpisode | None:
    key = _required(episode_key, "episode_key")
    ensure_market_opportunity_episode_schema()
    with connection() as conn:
        row = _load_episode_row(conn, key)
    return _row_to_episode(row) if row is not None else None


def assign_market_opportunity_trigger(
    *,
    acquisition_run_key: str,
    trigger_key: str,
    token_mint: str,
    trigger_kind: str,
    direction: str,
    chain_time: int,
    observed_at: int,
    method_version: str,
    venue: str | None = None,
    episode_window_seconds: int = DEFAULT_MARKET_EPISODE_WINDOW_SECONDS,
) -> MarketOpportunityEpisode:
    """Persist a raw market trigger and attach it to a causal token episode.

    ``trigger_key`` identifies one raw source notification/token evaluation. A later replay of that
    same key is not new market evidence, even if recomputing the detector later would yield a
    different direction/kind after more observations became available. The first persisted trigger
    therefore stays canonical; conflicting replays are audited instead of crashing acquisition.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    raw_key = _required(trigger_key, "trigger_key")
    mint = _required(token_mint, "token_mint")
    kind = _required(trigger_kind, "trigger_kind")
    pressure = _required(direction, "direction")
    version = _required(method_version, "method_version")
    normalized_venue = None if venue is None else _required(venue, "venue")
    if chain_time < 0 or observed_at < 0:
        raise ValueError("trigger timestamps must be non-negative")
    if observed_at < chain_time:
        raise ValueError("trigger observed_at cannot precede chain_time")
    if episode_window_seconds <= 0:
        raise ValueError("episode_window_seconds must be positive")

    incoming_identity = (mint, kind, pressure, int(chain_time), version, normalized_venue)
    ensure_market_opportunity_episode_schema()
    with connection() as conn:
        existing = conn.execute(
            """SELECT episode_key, token_mint, trigger_kind, direction,
                chain_time, observed_at, method_version, venue
            FROM market_opportunity_episode_triggers
            WHERE acquisition_run_key=? AND trigger_key=?""",
            (run_key, raw_key),
        ).fetchone()
        if existing is not None:
            existing_venue = existing["venue"] if existing["venue"] is None else str(existing["venue"])
            stored_identity = (
                str(existing["token_mint"]),
                str(existing["trigger_kind"]),
                str(existing["direction"]),
                int(existing["chain_time"]),
                str(existing["method_version"]),
                existing_venue,
            )
            stored_observed_at = int(existing["observed_at"])
            episode_key = str(existing["episode_key"])
            if stored_identity != incoming_identity:
                _record_trigger_conflict(
                    conn,
                    acquisition_run_key=run_key,
                    trigger_key=raw_key,
                    episode_key=episode_key,
                    stored_observed_at=stored_observed_at,
                    incoming_observed_at=observed_at,
                    stored_identity=stored_identity,
                    incoming_identity=incoming_identity,
                    canonical_action="retain_first_persisted_trigger",
                )
            elif observed_at < stored_observed_at:
                # This should not happen in the ingress-ordered coordinators. Retaining the already
                # persisted later T0 is conservative and avoids retroactively reshaping episodes.
                _record_trigger_conflict(
                    conn,
                    acquisition_run_key=run_key,
                    trigger_key=raw_key,
                    episode_key=episode_key,
                    stored_observed_at=stored_observed_at,
                    incoming_observed_at=observed_at,
                    stored_identity=stored_identity,
                    incoming_identity=incoming_identity,
                    canonical_action="retain_first_persisted_trigger_earlier_replay",
                )
            row = _load_episode_row(conn, episode_key)
            if row is None:
                raise RuntimeError("market trigger references missing episode")
            return _row_to_episode(row)

        row = conn.execute(
            """SELECT episode_key, acquisition_run_key, token_mint,
                first_trigger_key, first_trigger_kind, first_trigger_direction,
                first_trigger_chain_time, first_trigger_observed_at,
                episode_closes_at, decision_as_of
            FROM market_opportunity_episodes
            WHERE acquisition_run_key=? AND token_mint=?
              AND first_trigger_observed_at<=?
              AND episode_closes_at>?
            ORDER BY first_trigger_observed_at DESC, id DESC
            LIMIT 1""",
            (run_key, mint, observed_at, observed_at),
        ).fetchone()

        if row is None:
            episode_key = f"market-opportunity:{run_key}:{raw_key}"
            closes_at = observed_at + episode_window_seconds
            conn.execute(
                """INSERT INTO market_opportunity_episodes(
                    episode_key, acquisition_run_key, token_mint,
                    first_trigger_key, first_trigger_kind, first_trigger_direction,
                    first_trigger_chain_time, first_trigger_observed_at, episode_closes_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (episode_key, run_key, mint, raw_key, kind, pressure, chain_time, observed_at, closes_at),
            )
            row = _load_episode_row(conn, episode_key)
            if row is None:
                raise RuntimeError("failed to persist market opportunity episode")

        episode = _row_to_episode(row)
        conn.execute(
            """INSERT INTO market_opportunity_episode_triggers(
                acquisition_run_key, episode_key, trigger_key, token_mint,
                trigger_kind, direction, chain_time, observed_at,
                method_version, venue
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_key, episode.episode_key, raw_key, mint, kind, pressure, chain_time, observed_at, version, normalized_venue),
        )
        return episode


def freeze_market_opportunity_decision_as_of(
    episode_key: str,
    *,
    decision_as_of: int,
) -> MarketOpportunityEpisode:
    if decision_as_of < 0:
        raise ValueError("decision_as_of must be non-negative")
    key = _required(episode_key, "episode_key")
    ensure_market_opportunity_episode_schema()
    with connection() as conn:
        row = _load_episode_row(conn, key)
        if row is None:
            raise ValueError(f"market opportunity episode not found: {key}")
        episode = _row_to_episode(row)
        if decision_as_of < episode.first_trigger_observed_at:
            raise ValueError("decision_as_of cannot precede first trigger observation")
        if episode.decision_as_of is not None:
            if episode.decision_as_of != decision_as_of:
                raise ValueError("decision_as_of is already frozen with a different value")
            return episode
        conn.execute(
            """UPDATE market_opportunity_episodes
            SET decision_as_of=?, updated_at=CURRENT_TIMESTAMP
            WHERE episode_key=? AND decision_as_of IS NULL""",
            (decision_as_of, key),
        )

    frozen = get_market_opportunity_episode(key)
    if frozen is None:
        raise RuntimeError("market opportunity episode disappeared after freeze")
    return frozen


def load_market_opportunity_episode_triggers(
    episode_key: str,
    *,
    as_of: int | None = None,
) -> tuple[MarketOpportunityEpisodeTrigger, ...]:
    key = _required(episode_key, "episode_key")
    if as_of is not None and as_of < 0:
        raise ValueError("as_of must be non-negative")
    ensure_market_opportunity_episode_schema()
    query = """SELECT acquisition_run_key, episode_key, trigger_key, token_mint,
        trigger_kind, direction, chain_time, observed_at, method_version, venue
        FROM market_opportunity_episode_triggers WHERE episode_key=?"""
    params: list[object] = [key]
    if as_of is not None:
        query += " AND observed_at<=?"
        params.append(as_of)
    query += " ORDER BY observed_at, id"
    with connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return tuple(
        MarketOpportunityEpisodeTrigger(
            acquisition_run_key=str(row["acquisition_run_key"]),
            episode_key=str(row["episode_key"]),
            trigger_key=str(row["trigger_key"]),
            token_mint=str(row["token_mint"]),
            trigger_kind=str(row["trigger_kind"]),
            direction=str(row["direction"]),
            chain_time=int(row["chain_time"]),
            observed_at=int(row["observed_at"]),
            method_version=str(row["method_version"]),
            venue=(str(row["venue"]) if row["venue"] is not None else None),
        )
        for row in rows
    )


def count_market_trigger_replay_conflicts(*, acquisition_run_key: str) -> int:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    ensure_market_opportunity_episode_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM market_trigger_replay_conflicts
            WHERE acquisition_run_key=?""",
            (run_key,),
        ).fetchone()
    return int(row["n"])
