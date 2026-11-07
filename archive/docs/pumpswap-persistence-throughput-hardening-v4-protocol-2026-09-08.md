# PumpSwap Persistence Throughput Hardening v4 — Systems Protocol

Date: 2026-09-08  
Mode: **PAPER / RESEARCH / READ ONLY**

## Purpose

Tailfix v3 fixed the previously dominant PumpSwap causal tail but exposed a different systems
failure: individual events were fast enough while the persistence path could not drain the full
120-second acquisition window before the frozen deadline.

This protocol is systems-only. It cannot validate Flow60 buy-share economics, route-only edge,
transaction fills, realized PnL or live-money readiness.

## Evidence that motivated v4

Tailfix v3 live run:

- PumpSwap received: 2,969
- PumpSwap persistence completed: 2,559
- PumpSwap radar processed: 2,551
- coverage: 90.4% — FAIL
- true backlog: 9.597% — FAIL
- Pump p95: 1.516s — PASS
- PumpSwap pipeline p95: 1.894s — PASS
- drops: 0
- worker errors: 0
- hydration budget skips: 0
- reservation-superset violations: 0
- writer queue at deadline: 224
- PumpSwap ingress backlog: 154
- PumpSwap in-flight persistence: 256
- pool-identity durable mapping writes: 243
- SQLite resolution admission p95: ~314ms
- pool durable mapping write p95: ~362ms
- writer batch service p95: ~93ms

Interpretation: v3 was no longer latency-bound at the resolver or finalizer. The new failure mode was
**sustained persistence drain capacity**: the bounded persistence worker reservoir could become
occupied while the single authoritative SQLite writer still had a large queue at the deadline.

## Root-cause class addressed by v4

v3 intentionally gave pool-identity durability the highest SQLite admission priority because an
unknown pool blocks normalization and can amplify into a global sequence barrier. Once SQLite work
was moved off the event loop, many independent identity writes could wait concurrently for that
high-priority gate.

That removed event-loop blocking, but an unbounded stream of high-priority mapping writes could
repeatedly precede an already-waiting causal observation batch. In addition, the dominant fresh-run
mapping path still executed a pre-insert SELECT even though almost every run-scoped pool mapping was
new.

v4 addresses both issues without adding SQLite writers.

## Frozen v4 changes

### 1. Bounded resolution fairness

SQLite remains one physical writer.

Priority remains:

`resolution > causal > audit`

but when a causal writer is already waiting, v4 allows at most **one consecutive resolution grant**
before a causal writer receives a turn.

This is admission fairness, not transaction concurrency. Two SQLite writers are never active at the
same time.

The historical default remains unchanged when this v4 policy is not installed.

### 2. Optimistic run-scoped pool mapping persistence

For a fresh `(acquisition_run_key, pool_address)` mapping, v4 uses:

`INSERT OR IGNORE -> collision SELECT only if the UNIQUE insert did not win`

instead of:

`SELECT -> INSERT`

The following semantics are unchanged:

- run/pool UNIQUE identity
- earliest `observed_at` is canonical
- equal-time identity conflicts use the same deterministic lexical tie-break
- conflicts remain auditable
- a pool identity is not published to normalization before durable persistence completes

### 3. PumpSwap writer pressure telemetry

The authoritative observation writer remains behaviorally unchanged. v4 measures:

- submissions
- completions
- pending requests at close
- queue high-water
- queue depth immediately before close
- batch count
- average / maximum batch size
- configured batch size
- average batch fill percentage

These metrics distinguish a fast per-event pipeline from a writer that is silently approaching
sustained saturation.

## Preventive promotion policy

The official v43 11/11 systems gate is unchanged.

Tailfix v3 latency headroom is also retained:

- official Pump/PumpSwap p95 ceiling: 5s
- engineering early warning: any causal stage p95 >=4s

v4 adds a persistence-pressure promotion warning:

- PumpSwap writer queue high-water >=80% of the configured PumpSwap persistence-worker reservoir

The 80% rule is **promotion-only**. It does not rewrite the official 11/11 gate. It exists so a run
that barely passes under one traffic window does not spend a fresh economic V68 sample while the
writer is already near saturation.

Possible v4 wrapper outcomes:

- `FAIL_TAILFIX_V4_UNCHANGED_11_GATE`
- `HOLD_TAILFIX_V4_PREVENTIVE_HEADROOM`
- `PASS_TAILFIX_V4_11_GATE_WITH_LATENCY_AND_THROUGHPUT_HEADROOM`

Only the last classification may unlock another fresh V68 acquisition.

## Scientific / causal invariants

v4 does **not** change:

- market-opportunity detector thresholds
- trigger semantics
- first-persisted episode semantics
- conservative reservation ordering
- per-asset FIFO
- same-token Pump/PumpSwap cross-source serialization
- replay/conflict auditing
- causal `as_of`
- provider pacing
- route-only notional/slippage/horizons
- v68 feature, bins, direction, primary horizon or economic PASS criteria
- hydration or RPC concurrency ceilings
- 5s official latency threshold

No second physical SQLite writer is introduced.

## Required tests before live

1. bounded fairness gives a waiting causal writer a turn after one resolution grant;
2. fairness still permits only one active SQLite writer;
3. default historical admission policy remains unchanged outside v4;
4. fresh pool mapping insert skips the collision SELECT;
5. same-identity replay preserves earliest observation;
6. conflicting identity preserves the exact audit/canonical rule;
7. writer telemetry correctly accounts submissions, completions, pending pressure and batching;
8. v4 seams install and restore cleanly;
9. promotion guard cannot rescue an official systems FAIL;
10. promotion guard HOLDS on either latency or writer-pressure warning;
11. full repository CI remains green.

## Live acceptance

Run one fresh 120-second systems-only v4 acquisition.

Accept v4 for V68 only if:

1. official systems result is 11/11;
2. no v3 latency stage has p95 >=4s;
3. no hidden transport/same-token/reservation invariant fails;
4. v4 writer-pressure warning is false;
5. final classification is exactly
   `PASS_TAILFIX_V4_11_GATE_WITH_LATENCY_AND_THROUGHPUT_HEADROOM`.

If any item fails, do not start forward economic collection and do not reinterpret the failure as a
Flow60 buy-share economic result.
