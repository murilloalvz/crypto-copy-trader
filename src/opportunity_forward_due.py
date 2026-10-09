from __future__ import annotations

from src.database import connection
from src.opportunity_forward_outcome_store import (
    OpportunityForwardOutcome,
    ensure_opportunity_forward_outcome_schema,
)


def load_due_opportunity_forward_outcomes(
    *,
    as_of: int,
    acquisition_run_key: str | None = None,
    limit: int = 100,
) -> tuple[OpportunityForwardOutcome, ...]:
    """Return exact-target PENDING outcomes that are already due, without mutating them."""

    cutoff = int(as_of)
    if cutoff < 0:
        raise ValueError("as_of must be non-negative")
    if limit <= 0:
        raise ValueError("limit must be positive")
    run_key = None
    if acquisition_run_key is not None:
        run_key = str(acquisition_run_key).strip()
        if not run_key:
            raise ValueError("acquisition_run_key cannot be empty")

    ensure_opportunity_forward_outcome_schema()
    query = """SELECT outcome_key, acquisition_run_key, episode_key, token_mint,
        decision_as_of, horizon_seconds, target_at, status, observed_at,
        quote_key, error_type, error_message
        FROM opportunity_forward_outcomes
        WHERE status='PENDING' AND target_at<=?"""
    params: list[object] = [cutoff]
    if run_key is not None:
        query += " AND acquisition_run_key=?"
        params.append(run_key)
    query += " ORDER BY target_at, id LIMIT ?"
    params.append(int(limit))

    with connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()

    return tuple(
        OpportunityForwardOutcome(
            outcome_key=str(row["outcome_key"]),
            acquisition_run_key=str(row["acquisition_run_key"]),
            episode_key=str(row["episode_key"]),
            token_mint=str(row["token_mint"]),
            decision_as_of=int(row["decision_as_of"]),
            horizon_seconds=int(row["horizon_seconds"]),
            target_at=int(row["target_at"]),
            status=str(row["status"]),
            observed_at=(int(row["observed_at"]) if row["observed_at"] is not None else None),
            quote_key=(str(row["quote_key"]) if row["quote_key"] is not None else None),
            error_type=(str(row["error_type"]) if row["error_type"] is not None else None),
            error_message=(str(row["error_message"]) if row["error_message"] is not None else None),
        )
        for row in rows
    )
