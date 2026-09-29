"""Read-only diagnostic: why is the V55 price path empty? (opens SQLite with mode=ro).

PAPER / RESEARCH / READ-ONLY, no provider calls, no evaluation of any experiment.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from research.export_v55_cohort_v0 import V55_RUN_KEYS

DB = Path(os.getenv("DATABASE_PATH", "data/copytrader.db"))
PATH_JSON = Path(__file__).with_name("v55_price_path.json")


def main() -> int:
    if not DB.is_file():
        raise SystemExit(f"Database not found: {DB}")
    conn = sqlite3.connect(f"file:{DB.resolve().as_posix()}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    print(f"db={DB} size_mb={DB.stat().st_size / 1e6:.0f}")

    if PATH_JSON.is_file():
        eps = json.loads(PATH_JSON.read_text(encoding="utf-8")).get("episodes", [])
        print(f"path_json episodes={len(eps)} "
              f"with_ref={sum(1 for e in eps if e.get('ref_trade_price_usd'))} "
              f"with_buckets={sum(1 for e in eps if e.get('buckets'))} "
              f"n_trades_after>0={sum(1 for e in eps if e.get('n_trades_after'))}")
    else:
        print("path_json: not found (run export_v55_price_path_v0 first)")

    for run in V55_RUN_KEYS:
        n = conn.execute(
            "SELECT COUNT(*) c, COUNT(price_usd) p, MIN(observed_at) lo, MAX(observed_at) hi "
            "FROM market_trade_observations WHERE acquisition_run_key=?", (run,)).fetchone()
        print(f"trades[{run}] rows={n['c']} with_price={n['p']} observed_at=[{n['lo']}..{n['hi']}]")
        d = conn.execute(
            "SELECT COUNT(*) c, MIN(research_decision_as_of) lo, MAX(research_decision_as_of) hi "
            "FROM opportunity_route_research_decisions WHERE acquisition_run_key=?", (run,)).fetchone()
        print(f"decisions[{run}] rows={d['c']} decision_as_of=[{d['lo']}..{d['hi']}]")
        e = conn.execute(
            "SELECT COUNT(*) c FROM market_opportunity_episodes WHERE acquisition_run_key=?", (run,)).fetchone()
        print(f"episodes[{run}] rows={e['c']}")

    print("\nTop run keys with trades (first 8):")
    for r in conn.execute(
            "SELECT acquisition_run_key k, COUNT(*) c FROM market_trade_observations "
            "GROUP BY acquisition_run_key ORDER BY c DESC LIMIT 8"):
        print(f"  {r['c']:>10}  {r['k']}")

    print("\nFirst 3 decisions: trades for the token under the V55 run key (any time) / after decision:")
    for run in V55_RUN_KEYS:
        for d in conn.execute(
                "SELECT episode_key, token_mint, research_decision_as_of a "
                "FROM opportunity_route_research_decisions WHERE acquisition_run_key=? "
                "ORDER BY research_decision_as_of LIMIT 3", (run,)):
            t = conn.execute(
                "SELECT COUNT(*) c, COUNT(price_usd) p, "
                "SUM(observed_at>?) after, SUM(observed_at<=?) before "
                "FROM market_trade_observations WHERE acquisition_run_key=? AND token_mint=?",
                (d["a"], d["a"], run, d["token_mint"])).fetchone()
            print(f"  {run[-1]} {d['episode_key'][-12:]} trades={t['c']} priced={t['p']} "
                  f"before={t['before']} after={t['after']}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
