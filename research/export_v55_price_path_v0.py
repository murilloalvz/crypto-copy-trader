"""Read-only export of the V55 cohort's post-entry market price path (5s buckets).

PAPER / RESEARCH / READ-ONLY, descriptive only. Route-only/market-path return != realized P&L.
Does not evaluate or re-open V48/V55/V68/Participant Quality; no provider/network call.

Path basis: persisted `market_trade_observations` prices for the episode token under the same
acquisition_run_key. This is a MARKET-TRADE price series, not a Jupiter route quote, so it has no
price impact/fees and differs from the route-only returns. Only trades whose `observed_at` is in
(decision_as_of, decision_as_of + 3600s] are used (causal: seen after the decision). The reference
price is the last trade seen at or before decision_as_of; if none exists the episode gets no
reference and its path is left empty (missingness explicit, no backfill).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src import database
from src.market_observation_store import load_market_trades
from src.opportunity_route_research_store import load_route_research_decision
from research.export_v55_cohort_v0 import V55_RUN_KEYS, _require_database
from src.opportunity_route_research_store import load_route_research_outcomes

HORIZON_SECONDS = 3600
BUCKET_SECONDS = 5
DEFAULT_OUT = Path(__file__).with_name("v55_price_path.json")


def build_path(trades, decision_as_of: int) -> dict:
    """trades: iterable of StoredMarketTrade. Returns reference price and 5s buckets."""
    priced = [
        t.observation
        for t in trades
        if t.observation.price_usd is not None and t.observation.price_usd > 0
    ]
    priced.sort(key=lambda o: (o.observed_at, o.chain_time))
    before = [o for o in priced if o.observed_at <= decision_as_of]
    ref = before[-1].price_usd if before else None
    buckets: dict[int, list[float]] = {}
    for o in priced:
        offset = o.observed_at - decision_as_of
        if offset <= 0 or offset > HORIZON_SECONDS:
            continue
        key = (offset - 1) // BUCKET_SECONDS * BUCKET_SECONDS + BUCKET_SECONDS  # bucket end
        b = buckets.setdefault(key, [o.price_usd, o.price_usd, o.price_usd])  # low, high, last
        b[0] = min(b[0], o.price_usd)
        b[1] = max(b[1], o.price_usd)
        b[2] = o.price_usd
    return {
        "ref_trade_price_usd": ref,
        "n_trades_after": sum(1 for o in priced if 0 < o.observed_at - decision_as_of <= HORIZON_SECONDS),
        "last_offset_s": max(buckets) if buckets else None,
        "buckets": [[k, *buckets[k]] for k in sorted(buckets)],  # [end_offset_s, low, high, last]
    }


def export(out: Path) -> int:
    _require_database()
    episodes = []
    for run_key in V55_RUN_KEYS:
        seen = {}
        for outcome in load_route_research_outcomes(acquisition_run_key=run_key):
            seen[outcome.episode_key] = outcome
        for episode_key, outcome in sorted(seen.items()):
            decision = load_route_research_decision(
                acquisition_run_key=run_key, episode_key=episode_key
            )
            if decision is None:
                raise SystemExit(f"Fail-closed: missing decision for {episode_key}")
            trades = load_market_trades(
                acquisition_run_key=run_key, token_mint=decision.token_mint
            )
            path = build_path(trades, decision.research_decision_as_of)
            episodes.append(
                {
                    "episode_key": episode_key,
                    "cohort": run_key.rsplit("-", 1)[-1],
                    "decision_as_of": decision.research_decision_as_of,
                    **path,
                }
            )
    if not episodes:
        raise SystemExit(f"No episodes for {V55_RUN_KEYS}")
    payload = {
        "run_keys": list(V55_RUN_KEYS),
        "bucket_seconds": BUCKET_SECONDS,
        "horizon_seconds": HORIZON_SECONDS,
        "basis": "market_trade_observations price_usd; NOT route-quote; no impact/fees",
        "episodes": episodes,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    with_ref = sum(1 for e in episodes if e["ref_trade_price_usd"] is not None)
    with_path = sum(1 for e in episodes if e["buckets"])
    full = sum(1 for e in episodes if (e["last_offset_s"] or 0) >= HORIZON_SECONDS - 60)
    print(f"episodes={len(episodes)} with_reference_price={with_ref} with_any_path={with_path}")
    print(f"path_reaches_>=3540s={full}")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return export(parser.parse_args(argv).out)


if __name__ == "__main__":
    raise SystemExit(main())
