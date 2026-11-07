# Unified Market Latency — v5e Result and v6 Pump Microbatch Design

Date: 2026-09-03  
Mode: **PAPER / RESEARCH / READ ONLY**

## v5e classification

Run: `unified-market-smoke-20260903-05e`  
Duration: 120s  
Configuration: Pump workers 8, PumpSwap workers 24, PumpSwap resolution concurrency 18, hydration ceiling 1500, queue 5000.

The run reached a complete SUMMARY and all replay-integrity counters were zero.

Observed:

- received: 4,256 = Pump 1,878 + PumpSwap 2,378;
- dropped: 0;
- worker errors: 0;
- radar processed: 4,129;
- radar coverage: **97.0%**;
- deadline backlog: 127 = Pump ingress 21 + Pump inflight 1 + Pump reorder 105;
- deadline backlog / received: **2.98%**;
- reference-asset episodes: 0;
- admitted enrichments: 62;
- bundle flow30 total: 908;
- bundle wallets total: 787;
- Pump radar p95: **24.504s**;
- PumpSwap radar p95: **4.854s**;
- PumpSwap budget skips: 0;
- RPC failures: 0;
- replay conflicts: 0 across Pump adapter, shared market store, trigger store and PumpSwap pool mapping.

Frozen v5 gate result:

1. no worker errors / traceback — PASS;
2. zero drops — PASS;
3. reference_asset_episodes == 0 — PASS;
4. radar coverage >=95% — PASS (97.0%);
5. deadline backlog <=5% — PASS (2.98%);
6. Pump radar p95 <=5s — **FAIL (24.504s)**;
7. PumpSwap radar p95 <=5s — PASS (4.854s);
8. budget skips == 0 — PASS;
9. admitted bundles not systematically empty — PASS.

Classification: **INTEGRITY PASS / COVERAGE PASS / PUMPSWAP LATENCY PASS / PUMP LATENCY FAIL**.

This is not an economic result and says nothing about profitability.

## Diagnosis

The Pump failure is upstream of radar evaluation.

Pump telemetry:

- persistence queue p50 4.100s;
- persistence queue p95 23.901s;
- radar end-to-end p50 6.556s;
- radar end-to-end p95 24.504s;
- persistence completed 1,856 / 1,878 received;
- radar processed 1,751 / 1,878 received;
- Pump reorder backlog 105;
- queue high-water 291.

The near equality between persistence queue p95 and radar end-to-end p95 indicates that the dominant delay is waiting to enter Pump persistence, not detector computation.

The current Pump path uses eight concurrent workers, but every notification opens a separate SQLite write transaction. SQLite serializes writers, so adding writers can increase lock scheduling/transaction overhead without increasing true write throughput. Out-of-order persistence completion also feeds the strict ingress-order radar coordinator, which explains the 105-item reorder backlog.

Therefore v6 does **not** increase Pump worker count. It changes the write scheduling model.

## v6 architecture

Pump v6:

```text
Pump websocket
-> FIFO ingress queue
-> one ordered microbatch writer
-> one SQLite transaction for N notifications
-> completed queue in original ingress order
-> ingress-order radar coordinator
```

PumpSwap remains unchanged from the v5e configuration:

```text
PumpSwap websocket
-> concurrent pool resolution/persistence
-> completed queue
-> ingress-order radar coordinator
```

### Invariants

- no detector thresholds change;
- no strategy/scoring change;
- no execution/risk provider call;
- websocket ingress sequence remains the Pump causal ordering surface;
- microbatch input and output order are identical;
- each notification retains its own `observed_at`, signature, transaction identity and event keys;
- existing earliest-observed replay semantics are reused unchanged;
- one unexpected persistence error rolls back the whole microbatch and remains fail-fast;
- no extra flow observations are created by batching.

## Frozen v6 short-smoke configuration

Before any live v6 result, freeze:

- duration: 120s;
- commitment: confirmed;
- Pump writer: one ordered SQLite microbatch writer;
- Pump microbatch size ceiling: **32 notifications**;
- Pump maximum batch dwell: **25ms**;
- PumpSwap workers: 24;
- PumpSwap max concurrent resolutions: 18;
- max hydrations: 1500;
- RPC timeout: 3s;
- queue size: 5000.

The 25ms dwell is a bounded transaction-amortization delay, far below the 5s latency gate. When backlog exists, the writer drains immediately up to 32 notifications rather than waiting for the dwell timer.

## Frozen v6 PASS gate

PASS only if all conditions hold:

1. no traceback / worker errors;
2. zero dropped notifications;
3. `reference_asset_episodes == 0`;
4. radar coverage >=95%;
5. total deadline backlog <=5% of received;
6. Pump radar end-to-end p95 <=5s;
7. PumpSwap radar end-to-end p95 <=5s;
8. PumpSwap budget skips == 0;
9. admitted bundles are not systematically empty;
10. replay-conflict telemetry is inspected; any non-zero conflict must be explained before a long acquisition.

Conflict telemetry is not automatically a latency FAIL, but unexplained conflicts block the 12h acquisition.

## Decision after v6

If v6 passes, the latency gate is closed and the project can proceed to episode-scoped economic enrichment: Jupiter executable quote proxy, minimal hazard provider, historical wallet outcomes available before T0, then final decision_as_of freeze and a short true economic E2E smoke.

If Pump still fails, do not increase SQLite writer concurrency. Profile transaction time versus radar read/enrichment time and consider a dedicated append-only ingestion database / WAL-oriented writer or a staged in-memory causal window with durable asynchronous persistence, but only with explicit crash/recovery and causal invariants.

No 12h acquisition, shadow execution or live trading is authorized by this document.
