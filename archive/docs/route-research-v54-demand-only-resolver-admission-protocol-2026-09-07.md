# Route Research v54 — Demand-Only PumpSwap Resolver Admission Protocol

Date: 2026-09-07
Mode: **PAPER / RESEARCH / READ ONLY**

## Trigger

The first v48 run using the validated v53 systems profile reached subcohort B, then failed the unchanged 11-gate systems check before forward collection:

- Pump p95: 3.051s — PASS
- PumpSwap p95: 7.429s — FAIL
- coverage: 97.5%
- true backlog: 2.492%
- result: 10/11
- no forward collector for B
- therefore no v48 Flow60 verdict

Same-run v53 telemetry showed:

- global resolver capacity waits: 0
- demand resolution-capacity wait p95: 0ms
- demand pool-lock wait p95: 2401.8ms
- demand pool-lock wait max: 6311.4ms
- demand resolve max: 7197.3ms
- global prefix normalization barrier p95: 4693.2ms

The v53 optional ingress prefetch still calls the same authoritative `resolver.resolve` path after admission. That path owns the same per-pool single-flight lock used by causal normalization and can hold it through store/history/network resolution. Therefore speculative work can still become the lock owner that a later causal demand waits behind.

This is a systems hypothesis only. The live telemetry does not prove that every observed pool-lock wait was caused by prefetch.

## v54 change

v54 removes **only speculative ingress resolver admission**.

Ingress still observes candidate pool identities for diagnostics, but optional prefetch:

- creates no resolver task;
- never calls `resolver.resolve`;
- never acquires a per-pool resolver lock;
- never acquires expensive-resolution capacity;
- never consumes hydration budget;
- never persists a pool mapping;
- never reserves an asset;
- never creates detector evidence.

Authoritative normalization remains unchanged and still calls the inherited v53/v52 resolver with the original causal `as_of`.

## Frozen semantics

v54 does not change:

- detector thresholds;
- episode semantics;
- Pump/PumpSwap reservation order;
- same-asset FIFO;
- stateful finalizer count;
- replay or as-of semantics;
- hydration budget;
- v52 wall deadline;
- RPC hedging/batching;
- Pump prepare workers (20);
- provider pacing (650/1000/250ms);
- route-only notional (US$25);
- slippage (100bps);
- horizons (300/900/3600s);
- v48 Flow60 bins or primary 900s gate.

## Live test

Run exactly one fresh systems-only profile:

`python route_research_systems_stability_v54.py --run-key route-research-systems-stability-20260907-54`

The forward collector is forcibly disabled.

## Gate

Use the unchanged 11/11 systems gate. Do not relax the 5s p95 threshold.

Additional v54 requirements:

- v51/v52/v53 diagnostics present;
- v52 cleanup telemetry present;
- v54 diagnostic present;
- `scheduled=0` for speculative ingress resolver work;
- no forward collector.

Exact v50 causal attribution remains a separate diagnostic-quality gate and cannot rewrite the systems verdict.

## Interpretation

If v54 passes 11/11, speculative resolver ownership is removed from the validated systems profile. Only then may v48 acquisition be amended again, before a new virgin holdout run key is used.

If v54 fails and demand pool-lock waits remain high, the remaining same-pool HOL is authoritative demand-vs-demand single-flight rather than speculative ingress work. Do not re-enable prefetch, increase workers blindly, relax FIFO, or change economic semantics.

If v54 fails while pool-lock waits are low, classify the remaining dominant same-run clock before any next architecture change.

## v48 contamination rule

The failed `route-research-prospective-holdout-20260907-48v53` A/B base is burned for prospective validation. Because B failed systems before forward collection, the frozen Flow60 primary hypothesis remains **NOT_EVALUATED**. Do not inspect or reuse any partial economic result from A to choose, tune, or rescue the v48 hypothesis.
