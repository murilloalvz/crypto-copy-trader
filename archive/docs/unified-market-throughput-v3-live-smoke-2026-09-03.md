# Unified Market Throughput v3 — Live Smoke Result — 2026-09-03

Run: `unified-market-smoke-20260903-03`

Mode: **PAPER / RESEARCH / READ ONLY**.

## Result

**THROUGHPUT FAIL / SEMANTIC FIXES PASS**

The v3 smoke validated several important correctness properties but failed the capacity gate frozen before the run.

## Observed metrics

- elapsed: 120.0s; deadline overrun: 0.0s;
- received: Pump 2,181 / PumpSwap 2,484 = 4,665 total;
- enqueued: all received notifications;
- dropped: 0;
- persistence completed: Pump 1,270 / PumpSwap 2,482;
- radar processed: Pump 1,270 / PumpSwap 2,468;
- total radar coverage at deadline: **80.1%**;
- worker errors: 0;
- Pump backlog: 910;
- PumpSwap backlog: 0 ingress / 2 inflight / 14 reorder;
- Pump queue wait: p50 33.2s / p95 52.6s / max 58.6s;
- PumpSwap persistence queue wait: p50 0.57s / p95 26.1s / max 30.3s;
- PumpSwap radar end-to-end: p50 1.50s / p95 29.0s / max 31.0s;
- persisted trades: Pump 1,367 / PumpSwap 2,804;
- unresolved PumpSwap trades: 39;
- reference-asset episodes: **0**;
- raw radar hits: Pump 626 / PumpSwap 394;
- unique episodes: 77;
- opened by source: Pump 19 / PumpSwap 58;
- enrichment admitted: 77;
- bundle totals: flow30 896 / wallets 754;
- PumpSwap network hydrations: 300 / 300 successful;
- real RPC failures: 0;
- hydration budget skips: 41.

## Frozen gate evaluation

PASS:

- no traceback / worker errors;
- zero dropped notifications;
- reference assets never became opportunity episodes;
- both venues persisted observations;
- admitted bundles were populated.

FAIL:

- radar coverage 80.1% < required 95%;
- backlog >5%;
- Pump p95 queue wait 52.6s > required 2s;
- PumpSwap radar p95 29.0s > required 5s;
- hydration budget skips 41 > required 0.

## Diagnosis

The dominant bottleneck is the Pump path. v3 used one sequential worker that performed raw persistence and radar evaluation together. Pump therefore accumulated 910 notifications and tens of seconds of queue age while PumpSwap's concurrent identity pipeline nearly kept up.

The Pump persistence implementation also wrote lifecycle/trade rows through repeated store calls, each with its own schema/connection/transaction overhead.

PumpSwap's total hydration cap of 300 was also exhausted. This smoke had zero real RPC failures; the 41 unresolved/budget-skipped cases are an operational budget issue, not provider failure evidence.

## Decision

- Do not tune radar thresholds.
- Do not add Jupiter yet.
- Replace Pump sequential persist+radar with batched persistence plus bounded concurrent persistence workers and an ingress-order radar coordinator.
- Preserve the same causal `as_of` semantics and websocket ingress ordering.
- Re-run a bounded 120s throughput smoke as v4.
- The long-run PumpSwap hydration policy remains a separate pre-12h capacity gate; raising the short-smoke ceiling is not proof that a fixed total budget is suitable for 12h.
