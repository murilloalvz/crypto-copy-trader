# Market Opportunity Radar v1.1 — Live Smoke Result

Date: 2026-09-03

Mode: **PAPER / RESEARCH / READ ONLY**

Run key: `market-radar-smoke-20260903-01`

Duration: 120.0s

Commitment: `confirmed`

## Result

The live Pump -> radar -> opportunity episode path completed successfully on the user's local Windows machine.

Observed totals:

- notifications: 1,999;
- decoded Pump trades: 2,003;
- lifecycle events: 22;
- SOL-eligible trade events: 1,948;
- persisted eligible trade events: 1,948;
- filtered non-SOL-prefix events: 55;
- duplicate/replayed eligible events: 0;
- evaluated tokens: 145;
- raw radar hits: 423;
- unique hit tokens: 23;
- unique opportunity episodes: 27;
- raw trigger kinds: 101 `fresh_market_burst`, 322 `activity_acceleration`;
- raw directions: 197 `upward_pressure`, 151 `mixed_pressure`, 75 `downward_pressure`.

## What this validates

Operationally validated:

`Pump live stream -> causal persistence -> lifecycle/trade windows -> transaction-aware radar -> opportunity episode assignment`

The live stream produced enough token/wallet activity that market-wide acquisition is no longer constrained by the tiny economic sample seen in Wallet Forward v2.

The transaction-aware guard also operated on real traffic: the radar tracked transaction breadth separately from event count, so multiple Pump events inside one signature do not automatically become multiple independent transactions.

## Important accounting interpretation

`423 raw radar hits` is **not** the same thing as `423 independent opportunities`.

The episode store collapsed those hits into only `27` 60-second token episodes.

Using the smoke totals, at least 396 / 423 raw hits (~93.6%) were continuations of already-open episode state rather than first observed opportunity episodes within the process.

Therefore expensive enrichment must be episode-scoped, not raw-hit-scoped.

The console telemetry was amended after this smoke so future runs print only first sighting of each episode while preserving every qualifying raw trigger in SQLite.

## What this does not validate

This smoke does **not** establish:

- profitability;
- predictive edge;
- executable fill quality;
- Jupiter route quality for these episodes;
- token-risk quality;
- wallet-history incremental value;
- PumpSwap coverage;
- appropriate final production thresholds.

No detector threshold was retuned from this smoke.

## Why thresholds remain frozen for now

The smoke shows high event volume, but a single two-minute window is insufficient evidence for changing the acquisition detector.

Retuning immediately could suppress useful early opportunities merely to reduce operational load.

The next step is to improve accounting and bound enrichment cost independently of economic labels, then run another short smoke that reports episode-open composition directly.

## Next gate

Before any 12h acquisition:

1. validate episode-open telemetry on another short fresh run;
2. keep raw trigger persistence separate from expensive enrichment admission;
3. implement/validate PumpSwap as a distinct adapter;
4. design bounded, outcome-blind enrichment scheduling for Jupiter / wallet intelligence / risk / regime;
5. run a short end-to-end evidence smoke;
6. only then consider the first preregistered long acquisition window.

Passing this smoke validates detector/episode plumbing only. It is not evidence of edge.