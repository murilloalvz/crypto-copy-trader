# H_ORGANICITY_CONCENTRATION_DECAY_V0 — Fresh Confirmation V1 — Preregistration — 2026-09-25

Mode: PAPER / MARKET-FIRST / PROSPECTIVE CONFIRMATION / NO LIVE MONEY

## Prior state

The preregistered discovery evaluation returned `ITERATE` on the 2026-09-25 Launch Burst capture.

The exact frozen selector remains:

`mf_top_wallet_gross_share_delta_pct_points_late_minus_early <= 0.0`

No threshold movement, direction flip, subgroup rescue or feature combination is permitted.

## Fresh source requirement

Exactly one new 900-second Launch Burst route-shadow capture is authorized after this preregistration.

It must preserve:

- the frozen Launch Burst route contract;
- the existing 5-second causal decision window;
- fixed +60 second route-shadow primary outcome;
- US$25 notional;
- existing fees/slippage/price-impact semantics;
- causal feature snapshots frozen before provider quotes;
- exact reconstruction parity.

A transport-only provider amendment is permitted if it changes no selector, market feature, economic
contract, benchmark or outcome rule.

The consumed discovery capture
`launch_burst_prospective_route_live_v4-1790305374-3b6738bb33`
must not be reused.

## Support gate

The fresh candidate must satisfy the already-frozen discovery policy support gate:

- candidate route-usable n >= 10;
- signal frequency >= 20% of the feature-available baseline.

If support fails:

`INCONCLUSIVE_CONCENTRATION_DECAY_CONFIRMATION_SUPPORT`

No automatic second fresh capture is authorized.

## KEEP gates

With sufficient support, every already-frozen absolute KEEP condition must pass:

1. candidate mean net return > 0;
2. candidate profit factor > 1;
3. candidate mean-without-best-trade return > 0;
4. candidate median net return > feature-available baseline median;
5. candidate p10 net return >= feature-available baseline p10.

If all pass:

`KEEP_CONCENTRATION_DECAY_SELECTION_EDGE_CANDIDATE`

KEEP is not mature edge. It authorizes only an independently preregistered replication.

## KILL rule

With sufficient support, if any KEEP gate fails:

`KILL_CONCENTRATION_DECAY_SELECTION_EDGE_CANDIDATE`

The discovery evaluator may internally label a relatively coherent but absolutely negative fresh
sample as ITERATE. Confirmation V1 deliberately does not permit a second ITERATE: sufficient support
without all absolute KEEP gates is KILL.

## Forbidden after fresh starts

- threshold search;
- moving the 0 pp boundary;
- direction flip;
- subgroup rescue;
- adding another filter based on fresh outcomes;
- substituting another outcome horizon;
- automatic extra 900-second capture;
- calling relative improvement edge;
- live-money execution.
