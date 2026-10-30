from dataclasses import dataclass

from src.database import connection
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema
from src.wallet_forward_runs import (
    freeze_wallet_forward_enrollment_cutoff,
    get_wallet_forward_run,
)


@dataclass(frozen=True)
class WalletForwardEnrollment:
    run_key: str
    observation_id: int
    observation_key: str
    wallet_address: str
    token_mint: str
    chain_time: int
    observed_at: int


_SCHEMA = """
CREATE TABLE IF NOT EXISTS wallet_forward_enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_key TEXT NOT NULL,
    observation_id INTEGER NOT NULL,
    observation_key TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    token_mint TEXT NOT NULL,
    chain_time INTEGER NOT NULL,
    observed_at INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_key, observation_id),
    UNIQUE(run_key, observation_key)
);

CREATE INDEX IF NOT EXISTS idx_wallet_forward_enrollments_run
ON wallet_forward_enrollments(run_key, observation_id);
"""


def ensure_wallet_forward_enrollment_schema() -> None:
    with connection() as conn:
        conn.executescript(_SCHEMA)


def freeze_wallet_forward_enrollment(
    run_key: str,
    *,
    cutoff_observation_id: int,
) -> tuple[WalletForwardEnrollment, ...]:
    """Freeze the exact BUY cohort available at the economic enrollment cutoff.

    The observation id boundary is authoritative. Calling this again with the same cutoff is
    idempotent; a divergent cutoff is rejected by the run manifest.
    """
    key = run_key.strip()
    if not key:
        raise ValueError("run_key cannot be empty")
    run = get_wallet_forward_run(key)
    if run is None:
        raise ValueError(f"wallet forward run not found: {key}")
    if run.enrollment_ends_at is None or run.follow_up_ends_at is None:
        raise ValueError("run has no enrollment/follow-up protocol")
    if cutoff_observation_id < run.baseline_observation_id:
        raise ValueError("enrollment cutoff cannot precede run baseline")

    if run.enrollment_cutoff_observation_id is not None:
        if run.enrollment_cutoff_observation_id != cutoff_observation_id:
            raise ValueError(
                "wallet forward enrollment already frozen with a different cutoff"
            )
        return load_wallet_forward_enrollments(key)

    ensure_wallet_forward_observation_schema()
    ensure_wallet_forward_enrollment_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT id, observation_key, wallet_address, token_mint, chain_time, observed_at
            FROM wallet_forward_observations
            WHERE run_key=? AND side='buy' AND id>? AND id<=?
            ORDER BY id""",
            (key, run.baseline_observation_id, cutoff_observation_id),
        ).fetchall()
        conn.executemany(
            """INSERT OR IGNORE INTO wallet_forward_enrollments(
                run_key, observation_id, observation_key, wallet_address,
                token_mint, chain_time, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    key,
                    int(row["id"]),
                    str(row["observation_key"]),
                    str(row["wallet_address"]),
                    str(row["token_mint"]),
                    int(row["chain_time"]),
                    int(row["observed_at"]),
                )
                for row in rows
            ],
        )

    freeze_wallet_forward_enrollment_cutoff(
        key,
        cutoff_observation_id=cutoff_observation_id,
    )
    return load_wallet_forward_enrollments(key)


def load_wallet_forward_enrollments(run_key: str) -> tuple[WalletForwardEnrollment, ...]:
    key = run_key.strip()
    if not key:
        raise ValueError("run_key cannot be empty")
    ensure_wallet_forward_enrollment_schema()
    with connection() as conn:
        rows = conn.execute(
            """SELECT run_key, observation_id, observation_key, wallet_address,
                token_mint, chain_time, observed_at
            FROM wallet_forward_enrollments
            WHERE run_key=?
            ORDER BY observation_id""",
            (key,),
        ).fetchall()
    return tuple(
        WalletForwardEnrollment(
            run_key=str(row["run_key"]),
            observation_id=int(row["observation_id"]),
            observation_key=str(row["observation_key"]),
            wallet_address=str(row["wallet_address"]),
            token_mint=str(row["token_mint"]),
            chain_time=int(row["chain_time"]),
            observed_at=int(row["observed_at"]),
        )
        for row in rows
    )
