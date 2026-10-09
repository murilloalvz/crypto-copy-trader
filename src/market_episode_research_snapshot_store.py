"""Immutable persistence for causal Market-First T0 research snapshots.

The persisted canonical JSON is the exact feature/evidence payload that future outcome
analysis may join against. It is written before forward outcomes are scheduled and can
never be mutated after outcomes become available.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import threading
from typing import Any

from src import database
from src.database import connection
from src.market_episode_research_snapshot import MarketEpisodeResearchSnapshotV0


SNAPSHOT_STORE_VERSION = "market_episode_research_snapshot_store_v0"


@dataclass(frozen=True)
class MarketEpisodeResearchSnapshotRecordV0:
    snapshot_key: str
    acquisition_run_key: str
    episode_key: str
    token_mint: str
    decision_as_of: int
    snapshot_method_version: str
    payload_json: str
    payload_sha256: str

    def payload(self) -> dict[str, Any]:
        value = json.loads(self.payload_json)
        if not isinstance(value, dict):
            raise RuntimeError("persisted market episode snapshot payload is not an object")
        return value


_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_episode_research_snapshots_v0 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_key TEXT NOT NULL UNIQUE,
    acquisition_run_key TEXT NOT NULL,
    episode_key TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    decision_as_of INTEGER NOT NULL,
    snapshot_method_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(acquisition_run_key, episode_key, snapshot_method_version)
);

CREATE INDEX IF NOT EXISTS idx_market_episode_research_snapshots_v0_run_decision
ON market_episode_research_snapshots_v0(acquisition_run_key, decision_as_of, id);
"""

_SCHEMA_READY_PATHS: set[str] = set()
_SCHEMA_READY_LOCK = threading.Lock()


def _database_cache_key() -> str:
    path = database.settings.database_path
    try:
        return str(path.resolve())
    except AttributeError:
        return str(path)


def ensure_market_episode_research_snapshot_schema_v0() -> None:
    cache_key = _database_cache_key()
    if cache_key in _SCHEMA_READY_PATHS:
        return
    with _SCHEMA_READY_LOCK:
        if cache_key in _SCHEMA_READY_PATHS:
            return
        with connection() as conn:
            conn.executescript(_SCHEMA)
        _SCHEMA_READY_PATHS.add(cache_key)


def _canonical_payload(snapshot: MarketEpisodeResearchSnapshotV0) -> tuple[str, str]:
    payload_json = json.dumps(
        asdict(snapshot),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    return payload_json, digest


def _snapshot_key(snapshot: MarketEpisodeResearchSnapshotV0) -> str:
    return (
        f"market-episode-t0:v0:{snapshot.acquisition_run_key}:"
        f"{snapshot.episode_key}:{snapshot.method_version}"
    )


def _row_to_record(row) -> MarketEpisodeResearchSnapshotRecordV0:
    return MarketEpisodeResearchSnapshotRecordV0(
        snapshot_key=str(row["snapshot_key"]),
        acquisition_run_key=str(row["acquisition_run_key"]),
        episode_key=str(row["episode_key"]),
        token_mint=str(row["token_mint"]),
        decision_as_of=int(row["decision_as_of"]),
        snapshot_method_version=str(row["snapshot_method_version"]),
        payload_json=str(row["payload_json"]),
        payload_sha256=str(row["payload_sha256"]),
    )


def persist_market_episode_research_snapshot_v0(
    snapshot: MarketEpisodeResearchSnapshotV0,
) -> MarketEpisodeResearchSnapshotRecordV0:
    """Persist one exact T0 snapshot idempotently and reject any later mutation."""

    if snapshot.decision_as_of < 0:
        raise ValueError("snapshot decision_as_of must be non-negative")
    if not snapshot.acquisition_run_key.strip() or not snapshot.episode_key.strip():
        raise ValueError("snapshot run/episode identity cannot be empty")
    if not snapshot.token_mint.strip() or not snapshot.method_version.strip():
        raise ValueError("snapshot token/method identity cannot be empty")

    payload_json, digest = _canonical_payload(snapshot)
    key = _snapshot_key(snapshot)
    identity = (
        snapshot.acquisition_run_key,
        snapshot.episode_key,
        snapshot.token_mint,
        int(snapshot.decision_as_of),
        snapshot.method_version,
        payload_json,
        digest,
    )
    ensure_market_episode_research_snapshot_schema_v0()

    with connection() as conn:
        row = conn.execute(
            """SELECT snapshot_key, acquisition_run_key, episode_key, token_mint,
                decision_as_of, snapshot_method_version, payload_json, payload_sha256
            FROM market_episode_research_snapshots_v0
            WHERE acquisition_run_key=? AND episode_key=? AND snapshot_method_version=?""",
            (
                snapshot.acquisition_run_key,
                snapshot.episode_key,
                snapshot.method_version,
            ),
        ).fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO market_episode_research_snapshots_v0(
                    snapshot_key, acquisition_run_key, episode_key, token_mint,
                    decision_as_of, snapshot_method_version, payload_json, payload_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    key,
                    snapshot.acquisition_run_key,
                    snapshot.episode_key,
                    snapshot.token_mint,
                    int(snapshot.decision_as_of),
                    snapshot.method_version,
                    payload_json,
                    digest,
                ),
            )
        else:
            stored = _row_to_record(row)
            stored_identity = (
                stored.acquisition_run_key,
                stored.episode_key,
                stored.token_mint,
                stored.decision_as_of,
                stored.snapshot_method_version,
                stored.payload_json,
                stored.payload_sha256,
            )
            if stored.snapshot_key != key or stored_identity != identity:
                raise ValueError("market episode T0 snapshot is immutable and conflicts with persisted data")
            return stored

    loaded = load_market_episode_research_snapshot_record_v0(
        acquisition_run_key=snapshot.acquisition_run_key,
        episode_key=snapshot.episode_key,
        snapshot_method_version=snapshot.method_version,
    )
    if loaded is None:
        raise RuntimeError("market episode T0 snapshot disappeared after persistence")
    return loaded


def load_market_episode_research_snapshot_record_v0(
    *,
    acquisition_run_key: str,
    episode_key: str,
    snapshot_method_version: str,
) -> MarketEpisodeResearchSnapshotRecordV0 | None:
    run_key = str(acquisition_run_key).strip()
    episode = str(episode_key).strip()
    method = str(snapshot_method_version).strip()
    if not run_key or not episode or not method:
        raise ValueError("snapshot lookup identity cannot be empty")
    ensure_market_episode_research_snapshot_schema_v0()
    with connection() as conn:
        row = conn.execute(
            """SELECT snapshot_key, acquisition_run_key, episode_key, token_mint,
                decision_as_of, snapshot_method_version, payload_json, payload_sha256
            FROM market_episode_research_snapshots_v0
            WHERE acquisition_run_key=? AND episode_key=? AND snapshot_method_version=?""",
            (run_key, episode, method),
        ).fetchone()
    return _row_to_record(row) if row is not None else None
