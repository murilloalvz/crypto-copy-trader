from dataclasses import dataclass

from src.database import connection
from src.wallet_forward_observations import ensure_wallet_forward_observation_schema
from src.wallet_quote_watch import ensure_quote_attempt_schema


@dataclass(frozen=True)
class SuccessfulBuyQuoteLineage:
    source_event_key: str
    quote_key: str
    target_at: int
    entry_observed_at: int


def load_same_run_successful_buy_quote_lineage(
    sell_event_key: str,
) -> tuple[SuccessfulBuyQuoteLineage, ...]:
    """Return prior successful BUY quotes from the SELL event's exact forward run.

    A later forward run may observe the same wallet/token pair again. Reusing BUY quotes
    from an older run would not change that run's frozen economic denominator, but it can
    create cross-run SELL probes, consume provider capacity, and make operational logs look
    as if the current run had an entry it never enrolled. The persisted observation run_key
    is therefore a hard lineage boundary.

    Unscoped/legacy observations are intentionally not given SELL lineage. That is safer
    than guessing which historical BUY they belong to.
    """

    key = sell_event_key.strip()
    if not key:
        raise ValueError("sell_event_key cannot be empty")

    ensure_wallet_forward_observation_schema()
    ensure_quote_attempt_schema()
    with connection() as conn:
        sell = conn.execute(
            """SELECT run_key, wallet_address, token_mint, observed_at
            FROM wallet_forward_observations
            WHERE observation_key=?
            LIMIT 1""",
            (key,),
        ).fetchone()
        if sell is None:
            raise ValueError(f"sell observation not found: {key}")
        run_key = sell["run_key"]
        if run_key is None or not str(run_key).strip():
            return ()

        rows = conn.execute(
            """SELECT a.source_event_key, a.quote_key, a.target_at,
                entry.observed_at AS entry_observed_at
            FROM causal_quote_attempts a
            JOIN wallet_forward_observations entry
              ON entry.observation_key=a.source_event_key
            WHERE a.side='buy'
              AND a.status='success'
              AND a.quote_key IS NOT NULL
              AND entry.run_key=?
              AND entry.wallet_address=?
              AND entry.token_mint=?
              AND entry.observed_at<=?
            ORDER BY a.target_at, a.id""",
            (
                str(run_key),
                str(sell["wallet_address"]),
                str(sell["token_mint"]),
                int(sell["observed_at"]),
            ),
        ).fetchall()

    return tuple(
        SuccessfulBuyQuoteLineage(
            source_event_key=str(row["source_event_key"]),
            quote_key=str(row["quote_key"]),
            target_at=int(row["target_at"]),
            entry_observed_at=int(row["entry_observed_at"]),
        )
        for row in rows
    )
