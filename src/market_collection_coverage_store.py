"""Explicit collector-coverage evidence for Market-First research.

This store persists only intervals that an acquisition component explicitly asserts
were continuously observed.  It never infers coverage from neighboring trades, a run
start/end timestamp, successful RPC calls, or the absence of errors.

The stored interval is half-open in market/chain time: [start_chain_time,
end_chain_time).  `available_at` records when the system could causally rely on that
coverage assertion.  Consumers must filter by available_at <= decision_as_of.

This table is research-plane persistence; it must not enter the hot signal path.
"""

from __future__ import annotations

from dataclasses import dataclass
import json

from src.database import connection


MARKET_COLLECTION_COVERAGE_STORE_VERSION = "market_collection_coverage_store_v0"


@dataclass(frozen=True)
class StoredMarketCoverageInterval:
    acquisition_run_key: str
    evidence_key: str
    source_provider: str
    source_scope: str
    token_mint: str | None
    start_chain_time: int
    end_chain_time: int
    available_at: int
    coverage_kind: str


_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_collection_coverage_intervals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acquisition_run_key TEXT NOT NULL,
    evidence_key TEXT NOT NULL,
    source_provider TEXT NOT NULL,
    source_scope TEXT NOT NULL,
    token_mint TEXT,
    start_chain_time INTEGER NOT NULL,
    end_chain_time INTEGER NOT NULL,
    available_at INTEGER NOT NULL,
    coverage_kind TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(acquisition_run_key, evidence_key)
);

CREATE INDEX IF NOT EXISTS idx_market_collection_coverage_run_mint_time
ON market_collection_coverage_intervals(
    acquisition_run_key, token_mint, start_chain_time, end_chain_time, available_at
);

CREATE TABLE IF NOT EXISTS market_collection_coverage_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    acquisition_run_key TEXT NOT NULL,
    evidence_key TEXT NOT NULL,
    stored_identity_json TEXT NOT NULL,
    incoming_identity_json TEXT NOT NULL,
    canonical_action TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_market_collection_coverage_conflicts_run
ON market_collection_coverage_conflicts(acquisition_run_key, evidence_key, id);
"""

_ALLOWED_COVERAGE_KINDS = frozenset({"continuous_observed"})


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def ensure_market_collection_coverage_schema() -> None:
    with connection() as conn:
        conn.executescript(_SCHEMA)


def _validate_interval(
    *,
    source_scope: str,
    token_mint: str | None,
    start_chain_time: int,
    end_chain_time: int,
    available_at: int,
    coverage_kind: str,
) -> tuple[str, str | None, str]:
    scope = _required(source_scope, "source_scope")
    mint = None if token_mint is None else _required(token_mint, "token_mint")
    kind = _required(coverage_kind, "coverage_kind")
    if kind not in _ALLOWED_COVERAGE_KINDS:
        raise ValueError(f"unsupported coverage_kind: {kind}")
    if start_chain_time < 0 or end_chain_time <= start_chain_time:
        raise ValueError("coverage interval must have non-negative start and positive width")
    if available_at < 0:
        raise ValueError("available_at must be non-negative")
    # A coverage assertion cannot causally exist before the market interval has ended.
    if available_at < end_chain_time:
        raise ValueError("available_at cannot precede end_chain_time")
    return scope, mint, kind


def record_market_collection_coverage(
    *,
    acquisition_run_key: str,
    evidence_key: str,
    source_provider: str,
    source_scope: str,
    start_chain_time: int,
    end_chain_time: int,
    available_at: int,
    token_mint: str | None = None,
    coverage_kind: str = "continuous_observed",
) -> bool:
    """Persist one explicit coverage assertion.

    Returns True for a newly persisted interval and False for an idempotent replay.
    If the same evidence key is replayed with a different identity, the first persisted
    assertion remains canonical and the conflict is audited.  Coverage is never widened
    or rewritten by replay.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    key = _required(evidence_key, "evidence_key")
    provider = _required(source_provider, "source_provider")
    scope, mint, kind = _validate_interval(
        source_scope=source_scope,
        token_mint=token_mint,
        start_chain_time=start_chain_time,
        end_chain_time=end_chain_time,
        available_at=available_at,
        coverage_kind=coverage_kind,
    )
    identity = (
        provider,
        scope,
        mint,
        int(start_chain_time),
        int(end_chain_time),
        int(available_at),
        kind,
    )

    ensure_market_collection_coverage_schema()
    with connection() as conn:
        existing = conn.execute(
            """SELECT source_provider, source_scope, token_mint,
                start_chain_time, end_chain_time, available_at, coverage_kind
            FROM market_collection_coverage_intervals
            WHERE acquisition_run_key=? AND evidence_key=?""",
            (run_key, key),
        ).fetchone()
        if existing is not None:
            stored = (
                str(existing["source_provider"]),
                str(existing["source_scope"]),
                str(existing["token_mint"]) if existing["token_mint"] is not None else None,
                int(existing["start_chain_time"]),
                int(existing["end_chain_time"]),
                int(existing["available_at"]),
                str(existing["coverage_kind"]),
            )
            if stored != identity:
                already = conn.execute(
                    """SELECT 1 FROM market_collection_coverage_conflicts
                    WHERE acquisition_run_key=? AND evidence_key=?
                      AND stored_identity_json=? AND incoming_identity_json=?
                    LIMIT 1""",
                    (
                        run_key,
                        key,
                        json.dumps(stored, separators=(",", ":")),
                        json.dumps(identity, separators=(",", ":")),
                    ),
                ).fetchone()
                if already is None:
                    conn.execute(
                        """INSERT INTO market_collection_coverage_conflicts(
                            acquisition_run_key, evidence_key,
                            stored_identity_json, incoming_identity_json, canonical_action
                        ) VALUES (?, ?, ?, ?, ?)""",
                        (
                            run_key,
                            key,
                            json.dumps(stored, separators=(",", ":")),
                            json.dumps(identity, separators=(",", ":")),
                            "retain_first_persisted_coverage_assertion",
                        ),
                    )
            return False

        conn.execute(
            """INSERT INTO market_collection_coverage_intervals(
                acquisition_run_key, evidence_key, source_provider, source_scope,
                token_mint, start_chain_time, end_chain_time, available_at, coverage_kind
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_key,
                key,
                provider,
                scope,
                mint,
                int(start_chain_time),
                int(end_chain_time),
                int(available_at),
                kind,
            ),
        )
    return True


def load_market_collection_coverage(
    *,
    acquisition_run_key: str,
    source_scope: str,
    as_of: int,
    token_mint: str | None = None,
    chain_time_after: int | None = None,
    chain_time_before: int | None = None,
) -> tuple[StoredMarketCoverageInterval, ...]:
    """Load only causally available explicit coverage assertions.

    If token_mint is supplied, both mint-specific intervals and global intervals
    (`token_mint IS NULL`) are returned.  If token_mint is omitted, all intervals in the
    requested source scope are returned.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    scope = _required(source_scope, "source_scope")
    mint = None if token_mint is None else _required(token_mint, "token_mint")
    if as_of < 0:
        raise ValueError("as_of must be non-negative")
    if chain_time_after is not None and chain_time_after < 0:
        raise ValueError("chain_time_after must be non-negative")
    if chain_time_before is not None and chain_time_before < 0:
        raise ValueError("chain_time_before must be non-negative")
    if (
        chain_time_after is not None
        and chain_time_before is not None
        and chain_time_before <= chain_time_after
    ):
        raise ValueError("chain_time_before must be greater than chain_time_after")

    ensure_market_collection_coverage_schema()
    query = """SELECT acquisition_run_key, evidence_key, source_provider, source_scope,
        token_mint, start_chain_time, end_chain_time, available_at, coverage_kind
        FROM market_collection_coverage_intervals
        WHERE acquisition_run_key=? AND source_scope=? AND available_at<=?"""
    params: list[object] = [run_key, scope, int(as_of)]
    if mint is not None:
        query += " AND (token_mint IS NULL OR token_mint=?)"
        params.append(mint)
    if chain_time_after is not None:
        query += " AND end_chain_time>?"
        params.append(int(chain_time_after))
    if chain_time_before is not None:
        query += " AND start_chain_time<?"
        params.append(int(chain_time_before))
    query += " ORDER BY start_chain_time, end_chain_time, id"

    with connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return tuple(
        StoredMarketCoverageInterval(
            acquisition_run_key=str(row["acquisition_run_key"]),
            evidence_key=str(row["evidence_key"]),
            source_provider=str(row["source_provider"]),
            source_scope=str(row["source_scope"]),
            token_mint=(str(row["token_mint"]) if row["token_mint"] is not None else None),
            start_chain_time=int(row["start_chain_time"]),
            end_chain_time=int(row["end_chain_time"]),
            available_at=int(row["available_at"]),
            coverage_kind=str(row["coverage_kind"]),
        )
        for row in rows
    )


def count_market_collection_coverage_conflicts(*, acquisition_run_key: str) -> int:
    run_key = _required(acquisition_run_key, "acquisition_run_key")
    ensure_market_collection_coverage_schema()
    with connection() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM market_collection_coverage_conflicts
            WHERE acquisition_run_key=?""",
            (run_key,),
        ).fetchone()
    return int(row["n"])
