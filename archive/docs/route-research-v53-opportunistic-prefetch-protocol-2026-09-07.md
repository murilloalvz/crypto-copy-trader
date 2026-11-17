# Route Research v53 — Opportunistic PumpSwap ingress prefetch protocol

Date: 2026-09-07
Branch: `feat/exit-engine-v1`
Mode: **PAPER / RESEARCH / READ ONLY**

## Why v53 exists

The fresh v52 systems-only run `route-research-systems-stability-20260907-52` failed the unchanged same-run systems gate at **10/11**.

Same-run systems evidence:
- Pump p95: 1.482s — PASS
- PumpSwap causal pipeline p95: **7.981s — FAIL**
- coverage: 97.1% — PASS
- true backlog: 2.945% — PASS
- no worker errors, drops, hydration-budget skips or reservation-superset violations
- no forward economic collector

v52 transport evidence:
- hedge wall deadline: 3.000s
- deadline expirations: **0**
- hedge fetch p95: **431.8ms**, max 663.6ms
- hedge cleanup p95: 221.9ms, max 587.1ms
- v41 batch service p95: 493.6ms, max 809.4ms

Yet causal normalization remained slow:
- self ingress->normalization p95: 894.0ms, max **13.044s**
- global prefix normalization barrier p95: **5.786s**, max 12.166s
- normalization->reservation reconstructed p95: 5.788s

Therefore the live v52 result falsifies the working hypothesis that the external hedged RPC wall time itself explains the 8-13s normalization tails in this run.

## Additional v52 evidence

The same resolver is shared by authoritative normalization and optional v49 ingress prefetch.

v52 reported:
- v49 prefetch scheduled: 2629
- v49 coalesced inflight: 544
- resolver singleflight waits: 204
- network hydrations: 242
- historical pool hits: 157

The current `ConcurrentReusablePumpSwapPoolResolver.resolve` ordering is:

`causal cache -> per-pool lock -> global resolution semaphore -> canonical resolver work`

v49 prefetch calls this same authoritative `resolve` method. Optional speculative work can therefore wait in the same global capacity path used by real normalization demand. A later authoritative request has no priority mechanism over speculative requests already queued for unrelated pools. This is a systems scheduling risk, not a causal/economic rule.

The early v52 global blockers are consistent with a cold-start burst problem, but this protocol does **not** claim the prefetch queue is already proven to be the only remaining bottleneck. v53 therefore combines a minimal prefetch admission change with direct resolver wait-stage telemetry in the same systems-only run.

## v53 amendment

v53 changes **only optional ingress prefetch admission**.

For each v49 candidate pool:
1. retain the existing causal-cache fast path even if network capacity is full;
2. if the same pool is already resolving, skip this speculative prefetch instead of waiting on its pool lock;
3. if the inherited global expensive-resolution semaphore has no immediate capacity, skip this speculative prefetch instead of joining its wait queue;
4. otherwise call the exact existing `resolver.resolve(pool, as_of=...)` path.

A skipped prefetch:
- is **not** an unresolved canonical trade;
- does not set negative cache;
- does not consume hydration budget;
- does not create a reservation;
- does not create detector evidence;
- does not persist a pool mapping;
- does not change authoritative normalization behavior.

The authoritative normalization path is untouched. If it needs the pool identity, it still calls the same resolver and may wait for capacity as required.

## Why this is safer than changing the global watermark

v52 did not establish a safe narrower conflict domain. Pool address alone remains insufficient because the causal scheduler orders canonical opportunity assets by `token_mint`, and the repository does not prove `token_mint -> exactly one PumpSwap pool`.

v53 therefore does **not**:
- replace the global ingress reservation watermark;
- reorder canonical notifications;
- introduce per-pool causal FIFO as a substitute for token-level ordering;
- allow later same-token evidence to overtake an earlier unresolved notification.

It only prevents optional speculative optimization work from deliberately queueing when the authoritative resolver is already busy.

## Resolver wait-stage telemetry

v53 wraps the existing resolver synchronization primitives observationally. The parent `resolve` implementation is not replaced.

The same run must print:
- demand total resolver latency;
- prefetch total resolver latency;
- demand per-pool lock wait;
- prefetch per-pool lock wait;
- demand global resolution-capacity wait;
- prefetch global resolution-capacity wait;
- pool-lock wait count;
- resolution-capacity wait count;
- capacity waiter high-water split demand/prefetch;
- hottest pools by accumulated lock wait;
- v53 prefetch admitted/skipped-capacity/skipped-pool-busy counts.

This is intended to make one v53 live execution useful even if the systems gate still fails.

## What v53 does NOT change

v53 does not change:
- detector thresholds/version;
- Pump/PumpSwap websocket acquisition content/order;
- transaction parsing;
- pool mapping identity or causal `observed_at` rules;
- v52 RPC timeout/deadline semantics;
- hydration budget;
- authoritative resolver cache/store/historical/network behavior;
- global reservation ordering;
- per-asset FIFO;
- v51 stateful-ready priority;
- SQLite persistence/replay;
- episode assignment/no-retroactive-enrollment;
- wallet/flow/hazard definitions;
- provider pacing 650/1000/250ms;
- route-only notional/slippage/horizons;
- Flow60 bins LOW<=25 / MID26..47 / HIGH>47;
- primary 900s horizon;
- v48 support/PASS rules;
- 120s systems deadline;
- Pump/PumpSwap 5s latency threshold;
- forward economic collection.

## Unit/regression requirements before live

Tests must prove:
1. saturated resolver capacity causes speculative prefetch to skip without calling `resolver.resolve`;
2. a busy same-pool lock causes speculative prefetch to skip without waiting;
3. free capacity still permits normal prefetch;
4. a causal cache hit remains available even while capacity is saturated;
5. skipped prefetch is not counted as unresolved or failed;
6. resolver telemetry observes real capacity wait without replacing parent resolve semantics;
7. resolver telemetry observes same-pool lock wait;
8. prefetch and demand task timings are classified separately;
9. v53 installs/restores v52 resolver and v49 prefetch globals;
10. systems verdict remains independent from exact v50 trace completeness;
11. missing v52 cleanup or v53 telemetry fails closed;
12. forward collector remains forbidden.

## Live decision rule

Use one fresh systems-only run key after CI.

PASS requires the unchanged v43 same-run result **11/11**, no forward collector, v51/v52/v53 diagnostics present, v52 cleanup telemetry present, and no fatal scheduler/resolver error.

If v53 passes:
- stop systems latency tuning;
- freeze the validated systems profile;
- wire it into the frozen v48 prospective acquisition path with regression tests;
- only then start a fresh prospective Flow60 holdout.

If v53 fails:
- do not reroll blindly;
- do not relax the 5s gate;
- do not tune Flow60;
- classify the same-run dominant wait using v50 + v51 + v52 + v53 telemetry.

Interpretation guide if v53 fails:
- high **demand_pool_lock_wait** => same-pool single-flight path remains dominant;
- high **demand_resolution_capacity_wait** => global resolver capacity/admission is dominant;
- both low while demand total resolve is high => investigate canonical store/historical/network-inner service before touching ordering;
- resolver waits low while global barrier remains high => revisit reservation-watermark architecture only with a new explicit causal proof.
