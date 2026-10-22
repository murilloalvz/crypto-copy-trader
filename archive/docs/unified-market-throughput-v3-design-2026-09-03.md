# Unified Market Throughput v3 — Design Freeze — 2026-09-03

Status: IMPLEMENTED / CI + LIVE SMOKE GATE PENDING
Mode: PAPER / RESEARCH / READ ONLY

## Why v3 exists

Unified smoke v2 fixed the causal bundle clock, but exposed a capacity failure: Pump and PumpSwap shared one consumer, so PumpSwap pool resolution blocked the whole market loop. The requested 120s run received 2,480 notifications but only processed 480 before the deadline, with the queue saturated at 2,000 items.

This is an operational/capture problem, not evidence about trading edge. Radar thresholds remain frozen.

## Asset-role semantics

PumpSwap Buy/Sell events are base-asset relative. Market observations must represent the opportunity asset, not blindly the pool base mint.

V1 reference assets are intentionally narrow:

- WSOL: `So11111111111111111111111111111111111111112`
- USDC: `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`

Rules:

1. exactly one pool side must be a v1 reference asset;
2. the other side becomes `opportunity_mint`;
3. if the opportunity is the base asset, Buy/Sell side is preserved;
4. if the opportunity is the quote asset, Buy/Sell is inverted;
5. two-reference or two-unknown pairs are explicit `role_filtered`, never guessed;
6. reference assets must never open opportunity episodes.

Raw immutable `pool -> base_mint/quote_mint` identity stays in the PumpSwap pool store.

## Throughput architecture

```text
Pump websocket
  -> Pump queue
  -> single ordered Pump persist+radar worker

PumpSwap websocket
  -> PumpSwap ingress queue
  -> N bounded persistence/resolution workers
  -> completed persistence queue
  -> ingress-order radar coordinator

Both radar paths
  -> shared Opportunity Episode store
  -> exactly-once local episode bundle
```

Pump remains single-worker because its native decode/persist path is cheap and source ordering is already adequate. PumpSwap identity I/O is the expensive stage and is parallelized.

## PumpSwap causal ordering

Pool resolution/persistence may complete out of order, but radar/episode assignment may not.

Each successfully enqueued PumpSwap notification receives a monotonically increasing ingress sequence. Persistence workers may finish in any order. The radar coordinator buffers completed items and evaluates only the next expected sequence.

Later observations can already exist in SQLite when an earlier sequence is evaluated; this is safe because all radar loaders apply the earlier `as_of` and therefore hide observations whose `observed_at` is later.

## Single-flight resolution

`ConcurrentReusablePumpSwapPoolResolver` adds:

- one async lock per pool;
- bounded global concurrent resolution semaphore;
- historical/current-run/cache reuse inherited from the reusable resolver;
- `singleflight_waits` telemetry.

This prevents multiple simultaneous trades for one unknown pool from causing duplicate network hydration.

## Bounded live smoke

Runner: `unified_market_throughput_smoke_v3.py`

Default/frozen smoke shape:

- duration: 120s;
- commitment: confirmed;
- PumpSwap persistence workers: 8;
- max concurrent pool resolutions: 6;
- queue size per source: 5,000;
- max network hydrations: 300;
- RPC timeout: 3s;
- no Jupiter;
- no hazard provider;
- no order signing/submission;
- no threshold tuning.

## Telemetry required

The v3 summary must expose:

- received / enqueued / dropped by source;
- persistence completed by source;
- radar processed by source;
- total radar coverage;
- source queue high-water;
- Pump backlog;
- PumpSwap ingress / in-flight / reorder backlog;
- queue wait p50/p95/max;
- persisted trades;
- role-filtered and unresolved PumpSwap trades;
- raw hits / unique episodes / source openings;
- reference-asset episode count;
- local bundle flow/wallet totals;
- cache/current-run/historical pool reuse;
- single-flight waits;
- network hydrations / successes / real RPC failures / budget skips.

## Pre-frozen PASS gate

A 120s v3 smoke is a throughput PASS only if all are true:

1. no traceback / worker errors;
2. `dropped == 0` for both sources;
3. `reference_asset_episodes == 0`;
4. Pump and PumpSwap both persist observations;
5. total `radar_coverage_pct >= 95%` at the acquisition deadline;
6. total remaining backlog <= 5% of total enqueued notifications;
7. Pump queue-wait p95 <= 2s;
8. PumpSwap radar end-to-end wait p95 <= 5s;
9. hydration budget is not exhausted (`budget_skips == 0`);
10. if episodes are admitted, their local bundles are not systematically empty (`bundle_flow30_total > 0` and `bundle_wallets_total > 0`).

These are operational capture criteria, not economic strategy thresholds.

If one capacity criterion fails, do not tune the radar. Fix acquisition/backpressure first.

## After PASS

Only after v3 capacity passes:

1. Jupiter execution quote only for newly admitted episodes;
2. minimal causal hazard provider with explicit missing/failure state;
3. historical wallet outcomes already resolved before T0;
4. freeze final `decision_as_of` after required provider attempts;
5. short true economic E2E smoke;
6. protocol freeze;
7. first 12h acquisition.

No shadow/live trading is authorized by this gate.
