"""Read-only TECHNICAL diagnostic of a rejection-filter holdout cohort (mode=ro, no providers).

Reports acquisition quality only: outcome statuses, provider error types, lateness of collected
quotes vs their target times, and rule-input/pairing SUPPORT counts. It reads NO return values and
computes no verdict or catastrophic rates; it does not change any frozen gate.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path
from statistics import median

DB = Path(os.getenv("DATABASE_PATH", "data/copytrader.db"))
CAP = 2.0


def pct(vals, q):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(q * len(vals)))] if vals else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-key", default="rejection-filter-v0-20260929-01-F1")
    a = ap.parse_args(argv)
    if not DB.is_file():
        raise SystemExit(f"Database not found: {DB}")
    c = sqlite3.connect(f"file:{DB.resolve().as_posix()}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    rk = a.run_key
    print(f"run_key={rk}")

    print("\n[status by horizon]")
    for r in c.execute("SELECT horizon_seconds h, status, COUNT(*) n FROM opportunity_route_research_outcomes "
                       "WHERE acquisition_run_key=? GROUP BY h, status ORDER BY h, status", (rk,)):
        print(f"  {r['h']:>5}s {r['status']:<15} {r['n']}")

    print("\n[provider error types / messages (first 110 chars)]")
    for r in c.execute("SELECT horizon_seconds h, error_type, substr(COALESCE(error_message,''),1,110) m, COUNT(*) n "
                       "FROM opportunity_route_research_outcomes WHERE acquisition_run_key=? AND status<>'AVAILABLE' "
                       "AND status<>'PENDING' GROUP BY h, error_type, m ORDER BY n DESC LIMIT 12", (rk,)):
        print(f"  {r['h']:>5}s x{r['n']:<3} {r['error_type']} | {r['m']}")

    print("\n[lateness = observed_at - target_at, AVAILABLE outcomes, seconds]")
    for h in (300, 900, 3600):
        late = [r[0] for r in c.execute(
            "SELECT observed_at - target_at FROM opportunity_route_research_outcomes "
            "WHERE acquisition_run_key=? AND horizon_seconds=? AND status='AVAILABLE' AND observed_at IS NOT NULL", (rk, h))]
        if late:
            print(f"  {h:>5}s n={len(late)} min={min(late)} median={median(late)} p95={pct(late, .95)} max={max(late)}"
                  f"  >60s: {sum(1 for x in late if x > 60)}  >300s: {sum(1 for x in late if x > 300)}")
        else:
            print(f"  {h:>5}s no AVAILABLE outcomes")

    print("\n[timing of 900s outcomes: updated_at range per status]")
    for r in c.execute("SELECT status, MIN(updated_at) lo, MAX(updated_at) hi, MIN(target_at) tlo, MAX(target_at) thi, COUNT(*) n "
                       "FROM opportunity_route_research_outcomes WHERE acquisition_run_key=? AND horizon_seconds=900 "
                       "GROUP BY status", (rk,)):
        print(f"  {r['status']:<15} n={r['n']} updated_at {r['lo']} .. {r['hi']} | target_at {r['tlo']} .. {r['thi']}")

    print("\n[rule-input coverage and pairing SUPPORT counts (no returns read)]")
    rows = c.execute(
        "SELECT d.episode_key ek, q.provider_price_impact_pct_points imp, "
        "(SELECT status FROM opportunity_route_research_outcomes o WHERE o.acquisition_run_key=d.acquisition_run_key "
        " AND o.episode_key=d.episode_key AND o.horizon_seconds=900) st900 "
        "FROM opportunity_route_research_decisions d LEFT JOIN causal_quote_observations q ON q.quote_key=d.entry_quote_key "
        "WHERE d.acquisition_run_key=?", (rk,)).fetchall()
    n = len(rows)
    known = [r for r in rows if r["imp"] is not None]
    print(f"  decisions={n} impact_known={len(known)} ({100.0 * len(known) / n:.0f}%)" if n else "  no decisions")
    for label, sel in (("REJECTED", lambda x: abs(x) > CAP), ("KEPT", lambda x: abs(x) <= CAP)):
        grp = [r for r in known if sel(r["imp"])]
        paired = [r for r in grp if r["st900"] == "AVAILABLE"]
        print(f"  {label:<9} episodes={len(grp):<3} with 900s AVAILABLE (paired)={len(paired)}")
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
