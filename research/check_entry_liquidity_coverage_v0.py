"""Read-only precondition check for the Rejection Filter V0 draft (mode=ro; no provider calls).

Reports how often persisted BUY route quotes carry `liquidity_usd` and
`provider_price_impact_pct_points`, per source. Outcome-blind: no returns are read.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DB = Path(os.getenv("DATABASE_PATH", "data/copytrader.db"))


def main() -> int:
    if not DB.is_file():
        raise SystemExit(f"Database not found: {DB}")
    conn = sqlite3.connect(f"file:{DB.resolve().as_posix()}?mode=ro", uri=True, timeout=30)
    print("source | side | executable | rows | with_liquidity_usd | with_price_impact")
    for r in conn.execute(
        "SELECT source, side, executable, COUNT(*), COUNT(liquidity_usd), "
        "COUNT(provider_price_impact_pct_points) FROM causal_quote_observations "
        "GROUP BY source, side, executable ORDER BY COUNT(*) DESC LIMIT 20"
    ):
        print(" | ".join(str(v) for v in r))
    print("\nBUY quotes by |price impact| (outcome-blind; no returns read):")
    print("source | with_impact | abs<=2pp | share_abs<=2pp")
    for r in conn.execute(
        "SELECT source, COUNT(provider_price_impact_pct_points), "
        "SUM(ABS(provider_price_impact_pct_points) <= 2.0) FROM causal_quote_observations "
        "WHERE side='buy' AND executable=0 GROUP BY source ORDER BY COUNT(*) DESC LIMIT 20"
    ):
        n, ok = r[1], r[2] or 0
        print(f"{r[0]} | {n} | {ok} | {100.0 * ok / n:.1f}%" if n else f"{r[0]} | 0 | 0 | n/a")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
