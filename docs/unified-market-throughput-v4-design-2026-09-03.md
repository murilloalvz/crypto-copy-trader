# Unified Market Throughput v4 — Design Freeze — 2026-09-03

Mode: **PAPER / RESEARCH / READ ONLY**.

## Purpose

v4 exists only to remove the capacity bottleneck found in the v3 live smoke while preserving causal radar semantics. It does not change market-radar thresholds, episode deduplication, enrichment rules, or any economic decision logic.

## Architecture

```text
Pump websocket
-> dedicated Pump ingress queue
-> N bounded Pump persistence workers
-> one SQLite transaction per Pump notification
-> completed queue
-> ingress-order Pump radar coordinator

PumpSwap websocket
-> dedicated PumpSwap ingress queue
-> bounded concurrent PumpSwap persistence/resolution workers
-> completed queue
-> ingress-order PumpSwap radar coordinator

Both
-> shared market store
-> shared Opportunity Episode store
-> exactly-once local episode bundle
```

Pump persistence completion may occur out of order, but radar evaluation is released only in original websocket ingress order. Radar loaders still apply `observed_at <= as_of`, so observations persisted early by a later notification remain causally invisible to an earlier T0.

## Pump batch persistence

`src/pump_batch_persistence.py` persists all eligible TradeEvents and CreateEvents from one Pump notification inside one SQLite transaction.

Semantics match the existing store:

- exact later replay is idempotent;
- first `observed_at` remains authoritative;
- backdating is rejected;
- conflicting immutable event payload is rejected;
- only positive `sol_amount` TradeEvents enter the current Pump v1 normalized market surface.

## Pump radar split

`src/pump_radar_bridge_v4.py` evaluates only after persistence has completed. It does not re-persist the raw notification.

This split permits concurrent persistence without changing which ingress notification is allowed to evaluate first.

## Short-smoke capacity configuration

Runner: `unified_market_throughput_smoke_v4.py`.

Initial bounded live configuration:

- duration: 120s;
- Pump workers: 4;
- PumpSwap workers: 8;
- max concurrent PumpSwap resolutions: 6;
- queue size: 5,000 per ingress source;
- PumpSwap short-smoke hydration ceiling: 1,000.

The 1,000 hydration ceiling is deliberately only a **short-smoke non-binding ceiling**. It is not a production/12h policy and must not be copied into the long-run protocol without a separate rate/cost/backpressure design.

## Frozen v4 live PASS gate

The v4 120s smoke is an operational PASS only if all of the following hold:

1. no traceback / worker errors;
2. zero dropped notifications;
3. `reference_asset_episodes == 0`;
4. both Pump and PumpSwap persist observations;
5. total radar coverage at deadline >=95%;
6. total remaining backlog <=5% of enqueued notifications;
7. Pump radar end-to-end p95 <=5s;
8. PumpSwap radar end-to-end p95 <=5s;
9. `budget_skips == 0` in the short smoke;
10. admitted bundles are not systematically empty.

These thresholds are engineering/capture gates only. They are frozen before the live run and cannot be relaxed because of the observed result.

## After v4 PASS

A v4 PASS permits the project to proceed to episode-scoped economic enrichment (starting with Jupiter executable quote capture). It does **not** permit a 12h run yet.

Before the first 12h run the project still needs an explicit long-horizon PumpSwap hydration/rate/cost policy and a true E2E smoke with required provider failure/missingness semantics.
