# PumpSwap Preventive Latency Hardening — Tailfix v3

Date: 2026-09-08

Mode: **PAPER / RESEARCH / READ ONLY**

This document freezes the systems-only Tailfix v3 architecture and promotion policy. It does not change or evaluate the v68 economic hypothesis.

## Why v3 exists

The attempted v68 acquisition did not reach forward economic collection because the frozen systems gate failed on PumpSwap tail latency. Therefore the correct interpretation remains **no economic verdict**.

The recurring systems pattern was not throughput loss: coverage could remain high with zero drops/backlog while a small number of slow causal predecessors amplified into large tail latency through reservation ordering and per-asset dependencies. Tailfix v1 removed unnecessary cross-source global commit serialization for unrelated tokens. Tailfix v2 bounded RPC transport ownership and released hydration decisions without hidden transport oversubscription. A later high-load acquisition still showed thin/failed latency headroom, especially around normalization, reservation-to-submit and hot-asset dependency queues.

Tailfix v3 is designed to stop discovering these classes only after the official 5s gate breaks.

## Frozen scientific boundary

Tailfix v3 is **systems scheduling and observability only**.

Unchanged:

- Solana market-opportunity detector and all detector thresholds;
- v68 feature, bins, direction, horizon, support rules and PASS/FAIL economics;
- route notional, slippage and forward horizons;
- provider pacing;
- first-persisted trigger semantics;
- replay and `as_of` rules;
- reservation asset-superset requirement;
- per-asset FIFO;
- same-token cross-source serialization;
- hydration budget and RPC transport ceiling;
- official Pump/PumpSwap p95 threshold of **5.0 seconds**.

No forward economic collector may be started because of a Tailfix v3 systems run itself.

## Contamination audit

Compared with canonical research head:

`94017d7d96231a5bcd05a6d2a69d8d2ee90e231c`

The Tailfix v3 branch is additive apart from `src/sqlite_write_admission.py`, which changes only in-process SQLite writer admission priority/telemetry. The frozen detector, original v68 feature builder and original v68 runner are not modified by the systems branch.

The added `route_research_prospective_flow60_buy_share_holdout_v68_tailfix_v2.py` is a systems-wiring wrapper only; it does not redefine the v68 economic protocol. Tailfix v3 validation remains systems-only and must pass before any fresh v68 acquisition is considered.

## Architecture

### 1. Demand-only bounded resolver remains authoritative

Tailfix v3 retains the accepted v54 demand-only admission rule and Tailfix v2 shared bounded RPC transport. Speculative ingress work does not acquire resolver capacity ahead of authoritative normalization demand.

### 2. Async durable pool-identity stages

Pool identity resolution still follows the causal contract:

`causal cache -> current run store -> historical store -> bounded network hydration -> durable mapping -> canonical reload -> publish identity`

Synchronous SQLite stages are moved off the asyncio event loop with thread offload:

- current mapping lookup;
- historical mapping lookup;
- durable mapping write;
- canonical reload.

The same-pool single-flight lock is intentionally held until a newly learned/historical identity is durably written and canonically reloaded. V3 does **not** publish an in-memory identity before durability.

This removes event-loop blocking without weakening causal identity ownership.

Required invariant:

`event_loop_store_calls == 0`

Required accounting invariant:

`durable_mapping_writes == historical_store_hits + network_resolutions`

### 3. SQLite writer admission priority

SQLite/WAL still has one physical writer.

Admission priority is now:

`RESOLUTION > CAUSAL > AUDIT`

`RESOLUTION` is reserved for pool-identity durability that blocks normalization. It does not create another writer and does not increase network concurrency. This prevents a small identity write from sitting behind unrelated lower-criticality causal/audit work while an unresolved ingress sequence amplifies into a global normalization barrier.

Audit retains bounded starvation protection; writer ownership remains serialized.

### 4. Cross-source token commit lanes

Tailfix v1 same-token locking remains authoritative.

The lane implementation supports bounded worker counts and tests prove that distinct tokens can overlap while same-token work cannot overlap across Pump/PumpSwap. Tailfix v3 currently keeps the executed profile conservative at:

- Pump commit workers: 1
- PumpSwap commit workers: 1

Reason: the inherited upstream path still has one PumpSwap finalizer consumer. Increasing only the downstream executor would advertise capacity that the upstream topology cannot actually feed. Multi-finalizer promotion is deferred until live telemetry proves the ready/finalize stage is the limiting clock and the upstream consumer is changed with per-asset/FIFO safety proven.

### 5. Stage-by-stage latency decomposition

Tailfix v3 exposes p95/headroom for causal clocks rather than treating `normalization` as one opaque number. Relevant measurements include:

- current store lookup;
- historical store lookup;
- network account wait;
- durable mapping write;
- canonical reload;
- pool lock hold;
- self ingress-to-normalization;
- global prefix normalization barrier;
- reservation-to-submit;
- submit-to-dependency-ready;
- stateful ready queue;
- demoted ready queue;
- Pump/PumpSwap commit lane queue wait;
- token lock wait.

Stages are **not summed** because parts of the pipeline overlap.

## Preventive headroom policy

Official scientific systems threshold remains:

`PumpSwap causal pipeline p95 <= 5.0s`

Tailfix v3 adds a stricter engineering-only promotion threshold:

`early warning = 4.0s = 80% of the official 5.0s budget`

This does not change the frozen 11/11 gate. It controls whether another economic acquisition may be launched.

### Classification

`FAIL_TAILFIX_V3_UNCHANGED_11_GATE`

- frozen 11/11 systems authority failed;
- no economic acquisition is allowed.

`HOLD_TAILFIX_V3_LATENCY_HEADROOM`

- frozen 11/11 passed;
- but headroom report is missing or at least one monitored causal stage has p95 >=4.0s;
- no economic acquisition is allowed.

`PASS_TAILFIX_V3_11_GATE_WITH_HEADROOM`

- frozen 11/11 passed;
- headroom report present;
- no monitored causal stage has p95 >=4.0s;
- systems profile is eligible to be considered for a **fresh** v68 acquisition.

A PASS here is systems evidence only. It is not evidence of economic edge, executable fills, realized PnL or live-money readiness.

## Frozen 11/11 authority

All remain mandatory:

1. no worker/traceback errors;
2. drops = 0;
3. reference-asset episodes = 0;
4. radar coverage >=95%;
5. true backlog <=5%;
6. Pump p95 <=5s;
7. PumpSwap causal pipeline p95 <=5s;
8. hydration-budget skips = 0;
9. wallet/flow bundles nonempty;
10. replay/audit has no fatal corruption;
11. reservation-superset violations = 0.

Tailfix v3 additionally fails closed on its own invariants, including missing executed resolver/trace/commit-lane instrumentation, resolver SQLite work on the event loop, durable-mapping accounting mismatch, hidden transport oversubscription and same-token overlap.

## CI evidence before live validation

Implementation head before this protocol documentation:

`de89bfc230a290b2d48d7cdf61166126ebc1ddf1`

GitHub Actions unit-test run completed successfully with:

`Ran 997 tests ... OK`

This proves the tested invariants and regression suite on deterministic fixtures. It does **not** prove live Solana/RPC/SQLite tail latency.

## Required live validation

Run one fresh **systems-only** 120s acquisition with `route_research_systems_stability_tailfix_v3.py` after the newest branch head is CI-green.

Accept the systems profile for a future fresh v68 acquisition only if all of the following hold in the same run:

- official 11/11 PASS;
- classification `PASS_TAILFIX_V3_11_GATE_WITH_HEADROOM`;
- PumpSwap pipeline p95 <=5s;
- no monitored headroom stage >=4s;
- `event_loop_store_calls=0`;
- exact durable-mapping accounting;
- zero RPC transport-limit violations/hidden oversubscription;
- zero same-token overlap violations;
- zero reservation-superset violations.

If the result is HOLD or FAIL, there is still no v68 economic verdict. Use the new dominant-stage telemetry to fix the specific systems clock before spending another fresh economic cohort.

## Next systems branch rule

Do not increase workers by trial and error.

If live telemetry shows ready/finalizer queueing as the dominant stage after resolver/global-barrier hardening, the next candidate is bounded multi-finalizer concurrency for disjoint assets/tokens, with upstream consumers changed explicitly and tests proving per-asset FIFO, same-token cross-source serialization and no hidden oversubscription.

If normalization/global-prefix barrier remains dominant, continue at resolver/store/barrier ownership instead. If RPC becomes dominant again, stay within the existing transport ceiling and investigate provider/transport behavior rather than raising concurrency blindly.
