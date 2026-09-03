from dataclasses import dataclass

from src.database import connection
from src.market_observation_store import ensure_market_observation_schema
from src.market_opportunity_radar import MarketTradeObservation


@dataclass(frozen=True)
class TransactionMarketTrade:
    acquisition_run_key: str
    event_key: str
    source_provider: str
    observation: MarketTradeObservation


def _required(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def load_market_trades_by_transaction(
    *,
    acquisition_run_key: str,
    transaction_key: str,
    as_of: int | None = None,
) -> tuple[TransactionMarketTrade, ...]:
    """Load one transaction's already-persisted market observations causally.

    This is intentionally a read-only view over the canonical market observation store. It lets
    downstream bridges reuse the identity work already performed during persistence instead of
    resolving the same PumpSwap pool a second time.
    """

    run_key = _required(acquisition_run_key, "acquisition_run_key")
    tx_key = _required(transaction_key, "transaction_key")
    if as_of is not None and as_of < 0:
        raise ValueError("as_of must be non-negative")

    ensure_market_observation_schema()
    query = """SELECT acquisition_run_key, event_key, source_provider, token_mint, side,
        chain_time, observed_at, wallet_address, notional_usd, price_usd, venue,
        transaction_key
        FROM market_trade_observations
        WHERE acquisition_run_key=? AND transaction_key=?"""
    params: list[object] = [run_key, tx_key]
    if as_of is not None:
        query += " AND observed_at<=?"
        params.append(as_of)
    query += " ORDER BY chain_time, observed_at, id"

    with connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()

    return tuple(
        TransactionMarketTrade(
            acquisition_run_key=str(row["acquisition_run_key"]),
            event_key=str(row["event_key"]),
            source_provider=str(row["source_provider"]),
            observation=MarketTradeObservation(
                token_mint=str(row["token_mint"]),
                side=str(row["side"]),
                chain_time=int(row["chain_time"]),
                observed_at=int(row["observed_at"]),
                wallet_address=(
                    str(row["wallet_address"]) if row["wallet_address"] is not None else None
                ),
                notional_usd=(
                    float(row["notional_usd"]) if row["notional_usd"] is not None else None
                ),
                price_usd=(float(row["price_usd"]) if row["price_usd"] is not None else None),
                venue=(str(row["venue"]) if row["venue"] is not None else None),
                transaction_key=(
                    str(row["transaction_key"]) if row["transaction_key"] is not None else None
                ),
            ),
        )
        for row in rows
    )
