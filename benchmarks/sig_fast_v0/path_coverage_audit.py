"""SIG-FAST V0 -- price-path coverage audit (F1c of the 2026-10-08 work order).

Read-only, systems-only diagnostic. Reports, per token, how many already-captured
trades have the raw on-chain fields needed to derive a price (base/quote amounts,
and separately pool reserves), the duration of the captured price path, and the
largest observed gap between consecutive trades. Reports COUNTS ONLY -- never a
price value, a return, or any other outcome-bearing number. Running this script
does not read any economic outcome and does not spend a hypothesis attempt
(registry rule 5: a systems/coverage check is not an economic test).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import database
from src.market_observation_store import ensure_market_observation_schema, record_market_trade
from src.market_opportunity_radar import MarketTradeObservation

VERSION = "sig_fast_price_path_coverage_audit_v0"

DEFAULT_DATABASE = Path("data/copytrader.db")


@dataclass(frozen=True)
class TokenPathCoverage:
    token_mint: str
    n_trades: int
    n_price_from_amounts: int
    n_price_from_reserves: int
    pct_missing_price_from_amounts: float
    path_duration_seconds: int
    max_gap_seconds: int


def _token_mints_for_run(
    conn: sqlite3.Connection, acquisition_run_key: str, *, min_trades: int, limit: int
) -> list[str]:
    rows = conn.execute(
        """SELECT token_mint, COUNT(*) AS n
        FROM market_trade_observations
        WHERE acquisition_run_key = ?
        GROUP BY token_mint
        HAVING n >= ?
        ORDER BY n DESC
        LIMIT ?""",
        (acquisition_run_key, min_trades, limit),
    ).fetchall()
    return [str(row[0]) for row in rows]


def audit_token(
    conn: sqlite3.Connection, acquisition_run_key: str, token_mint: str
) -> TokenPathCoverage:
    agg = conn.execute(
        """SELECT
            COUNT(*) AS n_trades,
            SUM(CASE WHEN base_amount_raw IS NOT NULL AND base_amount_raw > 0
                      AND quote_amount_raw IS NOT NULL THEN 1 ELSE 0 END) AS n_price_from_amounts,
            SUM(CASE WHEN base_reserves_raw IS NOT NULL AND base_reserves_raw > 0
                      AND quote_reserves_raw IS NOT NULL THEN 1 ELSE 0 END) AS n_price_from_reserves,
            MIN(chain_time) AS first_chain_time,
            MAX(chain_time) AS last_chain_time
        FROM market_trade_observations
        WHERE acquisition_run_key = ? AND token_mint = ?""",
        (acquisition_run_key, token_mint),
    ).fetchone()

    n_trades = int(agg[0] or 0)
    n_price_from_amounts = int(agg[1] or 0)
    n_price_from_reserves = int(agg[2] or 0)
    first_chain_time = agg[3]
    last_chain_time = agg[4]

    if n_trades == 0:
        return TokenPathCoverage(
            token_mint=token_mint,
            n_trades=0,
            n_price_from_amounts=0,
            n_price_from_reserves=0,
            pct_missing_price_from_amounts=100.0,
            path_duration_seconds=0,
            max_gap_seconds=0,
        )

    ordered_times = [
        int(row[0])
        for row in conn.execute(
            """SELECT chain_time FROM market_trade_observations
            WHERE acquisition_run_key = ? AND token_mint = ?
            ORDER BY chain_time""",
            (acquisition_run_key, token_mint),
        ).fetchall()
    ]
    max_gap = 0
    for earlier, later in zip(ordered_times, ordered_times[1:]):
        max_gap = max(max_gap, later - earlier)

    pct_missing = 100.0 * (1.0 - (n_price_from_amounts / n_trades))

    return TokenPathCoverage(
        token_mint=token_mint,
        n_trades=n_trades,
        n_price_from_amounts=n_price_from_amounts,
        n_price_from_reserves=n_price_from_reserves,
        pct_missing_price_from_amounts=round(pct_missing, 2),
        path_duration_seconds=int(last_chain_time) - int(first_chain_time),
        max_gap_seconds=max_gap,
    )


def audit_run(
    conn: sqlite3.Connection,
    acquisition_run_key: str,
    *,
    min_trades: int = 1,
    limit: int = 50,
) -> list[TokenPathCoverage]:
    if min_trades < 1:
        raise ValueError("min_trades must be positive")
    if limit < 1:
        raise ValueError("limit must be positive")
    token_mints = _token_mints_for_run(
        conn, acquisition_run_key, min_trades=min_trades, limit=limit
    )
    return [audit_token(conn, acquisition_run_key, mint) for mint in token_mints]


def database_connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _self_check() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "self_check.db"
        with patch.object(database, "settings", SimpleNamespace(database_path=db_path)):
            ensure_market_observation_schema()
            for index, (chain_time, base_amt, quote_amt, base_res, quote_res) in enumerate(
                [
                    (1_000, 50_000_000, 2_000_000_000, 1_073_000_000_000_000, 30_000_000_000),
                    (1_010, 40_000_000, 1_600_000_000, 1_033_000_000_000_000, 31_600_000_000),
                    (1_100, 10_000_000, 500_000_000, None, None),
                ]
            ):
                record_market_trade(
                    acquisition_run_key="self-check-run",
                    event_key=f"token-a:{index}",
                    source_provider="self_check",
                    observation=MarketTradeObservation(
                        token_mint="TOKEN_A",
                        side="buy",
                        chain_time=chain_time,
                        observed_at=chain_time,
                        venue="pump_bonding_curve",
                        base_amount_raw=base_amt,
                        quote_amount_raw=quote_amt,
                        base_reserves_raw=base_res,
                        quote_reserves_raw=quote_res,
                    ),
                )
            # Token B: 1 trade, nothing derivable (pre-F1b capture, raw fields NULL).
            record_market_trade(
                acquisition_run_key="self-check-run",
                event_key="token-b:0",
                source_provider="self_check",
                observation=MarketTradeObservation(
                    token_mint="TOKEN_B",
                    side="buy",
                    chain_time=5_000,
                    observed_at=5_000,
                    venue="pumpswap",
                ),
            )

            with database_connection(db_path) as conn:
                results = audit_run(conn, "self-check-run", min_trades=1, limit=10)

    by_mint = {item.token_mint: item for item in results}
    token_a = by_mint["TOKEN_A"]
    assert token_a.n_trades == 3, token_a
    assert token_a.n_price_from_amounts == 3, token_a
    assert token_a.n_price_from_reserves == 2, token_a
    assert token_a.pct_missing_price_from_amounts == 0.0, token_a
    assert token_a.path_duration_seconds == 100, token_a
    assert token_a.max_gap_seconds == 90, token_a

    token_b = by_mint["TOKEN_B"]
    assert token_b.n_trades == 1, token_b
    assert token_b.n_price_from_amounts == 0, token_b
    assert token_b.pct_missing_price_from_amounts == 100.0, token_b
    assert token_b.path_duration_seconds == 0, token_b
    assert token_b.max_gap_seconds == 0, token_b

    print("self-check OK:", json.dumps([asdict(r) for r in results], sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SIG-FAST V0 price-path coverage audit: per-token counts of trades "
            "with a derivable price, never outcome/return values."
        )
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--acquisition-run-key", type=str, default=None)
    parser.add_argument("--min-trades", type=int, default=1)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return 0

    if not args.acquisition_run_key:
        parser.error("--acquisition-run-key is required outside --self-check")

    with patch.object(database, "settings", SimpleNamespace(database_path=args.database)):
        ensure_market_observation_schema()
        with database_connection(args.database) as conn:
            results = audit_run(
                conn,
                args.acquisition_run_key,
                min_trades=args.min_trades,
                limit=args.limit,
            )

    payload = {
        "version": VERSION,
        "database": str(args.database),
        "acquisition_run_key": args.acquisition_run_key,
        "classification": "SYSTEMS_COVERAGE_ONLY_NOT_AN_ECONOMIC_TEST",
        "tokens": [asdict(item) for item in results],
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
