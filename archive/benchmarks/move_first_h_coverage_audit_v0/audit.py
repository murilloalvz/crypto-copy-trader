"""Passo 0 (MOVE-FIRST-H-DISC-V0) -- read-only daily price/volume coverage audit.

Reports ONLY coverage/completeness for PumpSwap-graduated pools already observed by this
repository's own causal capture. No return, no price direction, no backtest -- this never reads
outcome data, only presence/absence of price_usd/notional_usd per day. Does not open a
PRE-REGISTRADA line and does not spend an attempt (registry rule 5: systems/diagnostic work is
not an economic verdict). No network calls.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

VERSION = "move_first_h_coverage_audit_v0"


def _day(observed_at: int) -> str:
    return datetime.fromtimestamp(observed_at, tz=timezone.utc).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class CoverageAuditV0:
    graduated_pools: int
    pools_observed_graduating_in_window: int
    capture_window_start: str | None
    capture_window_end: str | None
    pumpswap_trade_rows: int
    pumpswap_trade_rows_with_price: int
    pumpswap_trade_rows_with_volume: int
    pools_with_any_day_price_and_volume: int
    pools_with_continuous_daily_series: int
    pct_continuous_of_graduated: float | None
    per_pool_day_counts: dict[str, int]


def audit_coverage_v0(conn: sqlite3.Connection) -> CoverageAuditV0:
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT token_mint FROM market_lifecycle_observations WHERE venue='pumpswap'")
    graduated = [row[0] for row in cur.fetchall()]

    cur.execute(
        """SELECT COUNT(*) FROM (
            SELECT token_mint FROM market_lifecycle_observations GROUP BY token_mint
            HAVING COUNT(DISTINCT venue) > 1
        )"""
    )
    observed_graduating = int(cur.fetchone()[0])

    cur.execute("SELECT MIN(observed_at), MAX(observed_at) FROM market_trade_observations")
    window_start_raw, window_end_raw = cur.fetchone()
    window_start = _day(window_start_raw) if window_start_raw is not None else None
    window_end = _day(window_end_raw) if window_end_raw is not None else None

    cur.execute("SELECT COUNT(*) FROM market_trade_observations WHERE venue='pumpswap'")
    pumpswap_rows = int(cur.fetchone()[0])
    cur.execute(
        "SELECT COUNT(*) FROM market_trade_observations WHERE venue='pumpswap' AND price_usd IS NOT NULL"
    )
    pumpswap_rows_with_price = int(cur.fetchone()[0])
    cur.execute(
        "SELECT COUNT(*) FROM market_trade_observations WHERE venue='pumpswap' AND notional_usd IS NOT NULL"
    )
    pumpswap_rows_with_volume = int(cur.fetchone()[0])

    per_pool_days_with_both: dict[str, int] = {}
    pools_with_any_day = 0
    continuous = 0
    for mint in graduated:
        cur.execute(
            "SELECT observed_at, price_usd, notional_usd FROM market_trade_observations "
            "WHERE token_mint=? AND venue='pumpswap'",
            (mint,),
        )
        days_with_price: set[str] = set()
        days_with_volume: set[str] = set()
        for observed_at, price_usd, notional_usd in cur.fetchall():
            day = _day(int(observed_at))
            if price_usd is not None:
                days_with_price.add(day)
            if notional_usd is not None:
                days_with_volume.add(day)
        days_with_both = sorted(days_with_price & days_with_volume)
        per_pool_days_with_both[mint] = len(days_with_both)
        if days_with_both:
            pools_with_any_day += 1
            start = datetime.strptime(days_with_both[0], "%Y-%m-%d")
            end = datetime.strptime(days_with_both[-1], "%Y-%m-%d")
            expected = (end - start).days + 1
            if expected == len(days_with_both):
                continuous += 1

    n = len(graduated)
    return CoverageAuditV0(
        graduated_pools=n,
        pools_observed_graduating_in_window=observed_graduating,
        capture_window_start=window_start,
        capture_window_end=window_end,
        pumpswap_trade_rows=pumpswap_rows,
        pumpswap_trade_rows_with_price=pumpswap_rows_with_price,
        pumpswap_trade_rows_with_volume=pumpswap_rows_with_volume,
        pools_with_any_day_price_and_volume=pools_with_any_day,
        pools_with_continuous_daily_series=continuous,
        pct_continuous_of_graduated=(100.0 * continuous / n) if n else None,
        per_pool_day_counts=per_pool_days_with_both,
    )


def _print_report(report: CoverageAuditV0) -> None:
    print(f"janela de captura observada: {report.capture_window_start} .. {report.capture_window_end}")
    print(f"pools graduados (>=1 trade lifecycle venue=pumpswap): {report.graduated_pools}")
    print(f"pools com graduação observada na própria janela (pump E pumpswap): {report.pools_observed_graduating_in_window}")
    print(
        f"linhas de trade pumpswap: {report.pumpswap_trade_rows} "
        f"(com price_usd: {report.pumpswap_trade_rows_with_price}, "
        f"com notional_usd: {report.pumpswap_trade_rows_with_volume})"
    )
    print(f"pools com pelo menos 1 dia com preço E volume: {report.pools_with_any_day_price_and_volume}")
    print(f"pools com série diária contínua (preço+volume): {report.pools_with_continuous_daily_series}")
    print(f"% contínuo sobre graduados: {report.pct_continuous_of_graduated}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-path", default="data/copytrader.db")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        print("self-check OK")
        return

    conn = sqlite3.connect(args.database_path)
    try:
        report = audit_coverage_v0(conn)
    finally:
        conn.close()
    _print_report(report)


def _self_check() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE market_lifecycle_observations (token_mint TEXT, venue TEXT);
        CREATE TABLE market_trade_observations (
            token_mint TEXT, venue TEXT, observed_at INTEGER, price_usd REAL, notional_usd REAL
        );
        """
    )
    base = 1_700_000_000  # arbitrary fixed epoch second, aligned to a day boundary below
    base -= base % 86400
    with conn:
        # POOL_FULL: graduated, 2 continuous days with price+volume
        conn.execute("INSERT INTO market_lifecycle_observations VALUES ('POOL_FULL','pump')")
        conn.execute("INSERT INTO market_lifecycle_observations VALUES ('POOL_FULL','pumpswap')")
        conn.execute(
            "INSERT INTO market_trade_observations VALUES ('POOL_FULL','pumpswap',?,1.0,10.0)",
            (base,),
        )
        conn.execute(
            "INSERT INTO market_trade_observations VALUES ('POOL_FULL','pumpswap',?,1.1,11.0)",
            (base + 86400,),
        )
        # POOL_GAP: graduated, day 0 and day 2 with price+volume, day 1 missing -> not continuous
        conn.execute("INSERT INTO market_lifecycle_observations VALUES ('POOL_GAP','pumpswap')")
        conn.execute(
            "INSERT INTO market_trade_observations VALUES ('POOL_GAP','pumpswap',?,1.0,10.0)",
            (base,),
        )
        conn.execute(
            "INSERT INTO market_trade_observations VALUES ('POOL_GAP','pumpswap',?,1.2,12.0)",
            (base + 2 * 86400,),
        )
        # POOL_NO_PRICE: graduated, trades exist but price_usd is NULL (the real-world case found
        # in this sandbox's local data -- ingestion never fills price_usd for pumpswap trades)
        conn.execute("INSERT INTO market_lifecycle_observations VALUES ('POOL_NO_PRICE','pumpswap')")
        conn.execute(
            "INSERT INTO market_trade_observations VALUES ('POOL_NO_PRICE','pumpswap',?,NULL,NULL)",
            (base,),
        )

    report = audit_coverage_v0(conn)
    assert report.graduated_pools == 3, report.graduated_pools
    assert report.pools_observed_graduating_in_window == 1, report.pools_observed_graduating_in_window
    assert report.per_pool_day_counts["POOL_FULL"] == 2
    assert report.per_pool_day_counts["POOL_GAP"] == 2
    assert report.per_pool_day_counts["POOL_NO_PRICE"] == 0
    assert report.pools_with_any_day_price_and_volume == 2
    assert report.pools_with_continuous_daily_series == 1  # only POOL_FULL
    conn.close()


if __name__ == "__main__":
    main()
