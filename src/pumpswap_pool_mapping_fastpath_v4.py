from __future__ import annotations

from dataclasses import dataclass
import threading

from src.database import connection
import src.pumpswap_pool_store as store


@dataclass(frozen=True)
class PumpSwapPoolMappingFastPathSnapshotV4:
    insert_attempts: int
    collision_reads: int
    earliest_observed_updates: int
    identity_conflicts: int
    canonical_replacements: int


_STATS_LOCK = threading.Lock()
_STATS = {
    "insert_attempts": 0,
    "collision_reads": 0,
    "earliest_observed_updates": 0,
    "identity_conflicts": 0,
    "canonical_replacements": 0,
}


def reset_pumpswap_pool_mapping_fastpath_metrics_v4() -> None:
    with _STATS_LOCK:
        for key in _STATS:
            _STATS[key] = 0


def pumpswap_pool_mapping_fastpath_snapshot_v4() -> PumpSwapPoolMappingFastPathSnapshotV4:
    with _STATS_LOCK:
        return PumpSwapPoolMappingFastPathSnapshotV4(**dict(_STATS))


def _add_stat(key: str, amount: int = 1) -> None:
    with _STATS_LOCK:
        _STATS[key] += int(amount)


def record_pumpswap_pool_mapping_fast_v4(
    *,
    acquisition_run_key: str,
    pool_address: str,
    base_mint: str,
    quote_mint: str,
    observed_at: int,
    source_provider: str,
) -> bool:
    """Persist one pool mapping with insert-first collision handling.

    This is semantically equivalent to ``record_pumpswap_pool_mapping`` but optimizes the dominant
    fresh-run path. A run normally has no row yet for a newly learned pool, so v3's pre-insert SELECT
    adds a second SQLite statement to almost every durable identity write. V4 attempts the UNIQUE
    insert first and performs the replay/conflict SELECT only when SQLite reports a collision.

    Earliest-observation canonicalization, lexical equal-time tie-breaks, conflict audit rows and the
    run/pool UNIQUE constraint remain unchanged.
    """

    run_key = store._required(acquisition_run_key, "acquisition_run_key")
    pool = store._required(pool_address, "pool_address")
    base = store._required(base_mint, "base_mint")
    quote = store._required(quote_mint, "quote_mint")
    provider = store._required(source_provider, "source_provider")
    learned_at = int(observed_at)
    if learned_at < 0:
        raise ValueError("observed_at must be non-negative")
    store.ensure_pumpswap_pool_schema()

    incoming_identity = (base, quote)
    _add_stat("insert_attempts")
    with connection() as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO pumpswap_pool_mappings(
                acquisition_run_key, pool_address, base_mint, quote_mint,
                observed_at, source_provider
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (run_key, pool, base, quote, learned_at, provider),
        )
        if cursor.rowcount == 1:
            return True

        _add_stat("collision_reads")
        existing = conn.execute(
            """SELECT base_mint, quote_mint, observed_at, source_provider
            FROM pumpswap_pool_mappings
            WHERE acquisition_run_key=? AND pool_address=?""",
            (run_key, pool),
        ).fetchone()
        if existing is None:
            raise RuntimeError("PumpSwap pool INSERT OR IGNORE lost canonical row")

        stored_identity = (str(existing["base_mint"]), str(existing["quote_mint"]))
        stored_observed_at = int(existing["observed_at"])
        stored_provider = str(existing["source_provider"])

        if stored_identity == incoming_identity:
            if learned_at < stored_observed_at:
                conn.execute(
                    """UPDATE pumpswap_pool_mappings
                    SET observed_at=?, source_provider=?
                    WHERE acquisition_run_key=? AND pool_address=?""",
                    (learned_at, provider, run_key, pool),
                )
                _add_stat("earliest_observed_updates")
            return False

        _add_stat("identity_conflicts")
        incoming_wins = (
            learned_at < stored_observed_at
            or (
                learned_at == stored_observed_at
                and store._identity_key(*incoming_identity) < store._identity_key(*stored_identity)
            )
        )
        action = "replace_with_canonical_mapping" if incoming_wins else "retain_canonical_mapping"
        store._record_conflict(
            conn,
            acquisition_run_key=run_key,
            pool_address=pool,
            stored_observed_at=stored_observed_at,
            incoming_observed_at=learned_at,
            stored_identity=stored_identity,
            incoming_identity=incoming_identity,
            stored_source_provider=stored_provider,
            incoming_source_provider=provider,
            canonical_action=action,
        )
        if incoming_wins:
            conn.execute(
                """UPDATE pumpswap_pool_mappings
                SET base_mint=?, quote_mint=?, observed_at=?, source_provider=?
                WHERE acquisition_run_key=? AND pool_address=?""",
                (base, quote, learned_at, provider, run_key, pool),
            )
            _add_stat("canonical_replacements")
        return False
