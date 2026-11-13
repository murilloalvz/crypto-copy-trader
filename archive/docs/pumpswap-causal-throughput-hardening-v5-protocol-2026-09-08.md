# PumpSwap Causal Throughput Hardening v5 — Systems Protocol

Date: 2026-09-08  
Mode: **PAPER / RESEARCH / READ ONLY**

## Purpose

Tailfix v4 proved that the persistence pipeline can drain a high-volume 120-second acquisition, but
its fairness intervention exposed a deeper normalization problem. Throughput reached 100% coverage
and zero backlog while PumpSwap causal pipeline p95 regressed to ~19.1s.

V5 is a systems-only architecture correction. It cannot validate Flow60 buy-share economics, route
edge, fills, realized PnL or live-money readiness.

## Evidence that motivated v5

Fresh v4 systems-only run on 2026-09-08:

- PumpSwap received / persisted / radar processed: 5,191 / 5,191 / 5,191
- Pump received / persisted / radar processed: 2,107 / 2,107 / 2,107
- radar coverage: **100.0% PASS**
- true backlog: **0.000% PASS**
- drops / worker errors: 0 / 0
- Pump p95: **2.463s PASS**
- PumpSwap pipeline p95: **19.066s FAIL**
- normalization->reservation p95: **17.421s**
- global prefix normalization barrier p95: **17.412s**
- resolver pool-lock hold p95: **4.439s**
- resolver durable mapping write p95: **4.221s**
- SQLite resolution-admission wait p95: **3.566s**
- demand same-pool lock wait p95: **14.934s**
- RPC decision availability remained healthy at ~0.534s p95 with zero transport-limit violations
- mapping writes: 560
- pool-mapping collision reads: 238 (**42.5%**)
- identity conflicts: 0
- writer pending at close: 0

Interpretation: v4 solved the v3 drain failure, but the system was spending substantial critical-path
time repeatedly reconciling the same immutable pool identities. Strict global ingress reservation
ordering then amplified a handful of slow normalizations into multi-second waits for hundreds of
otherwise-ready successors.

## Root-cause classes addressed by v5

### A. Historical-promotion stampede before single-flight

The v3 resolver attempted current/historical lookup before acquiring the per-pool single-flight
lock. Concurrent notifications for the same historical pool could therefore all miss the current-run
row, all find the same prior-run identity and all request durable promotion independently.

The v4 evidence is consistent with this class: 238 mapping collision reads with zero identity
conflicts. Collision is not automatically proof of duplicate concurrency, but combined with the
resolver topology it is direct evidence that the same run/pool identity was frequently already
present by the time another write attempted to insert it.

V5 moves historical promotion behind the existing per-pool single-flight lock and rechecks
current-run cache/store after lock acquisition. One worker promotes/resolves; waiters reuse.

### B. Older queued notifications re-resolving an identity learned later in the same run

The historical/base resolver cache is strict: a mapping whose `observed_at` is later than a
notification's `as_of` is not a causal cache hit. That is correct for using evidence *at the earlier
time*, but normalization already has a stronger availability contract:

`effective_observed_at = max(notification.observed_at, mapping.observed_at)`

Therefore, once the immutable identity has actually become durable in the current run, an older
queued notification may safely use it **only as delayed knowledge**. The resulting normalized trade
is not published at the older notification time; its usable observation time is clamped forward to
the mapping availability time.

Example:

- notification received/observed at t=120
- pool identity becomes durably known at t=130
- normalized trade is stored with `observed_at=130`, never 120

This is delayed availability, not lookahead or backdating.

Prior-run historical lookup remains strict to the notification's original observed time. V5 never
pulls a historical row observed after that cutoff merely because it exists in the database.

### C. Synchronous CreatePool identity persistence on the event loop

The legacy normalization function called `resolver.learn_from_create(...)` synchronously. The v4
live run happened to contain no lifecycle inserts, so this did not dominate that run, but it remained
a latent event-loop blocking class.

V5 introduces an awaited async CreatePool learning hook. Durable pool-store work executes off the
asyncio event loop while retaining the same per-pool lock and durable-before-publication rule.

### D. Max-only writer pressure warning

V4 used writer queue high-water as a promotion warning. High-water is valuable diagnostically but a
single transient spike can exceed 80% even when the writer drains completely and sustained wait is
healthy.

V5 retains high-water for diagnostics but promotion uses sustained evidence:

- p95 writer queue depth relative to the bounded PumpSwap persistence-worker reservoir;
- p95 authoritative writer result wait;
- pending/queued work at close.

## Frozen v5 architecture

### Normalization-specific resolver contract

For each pool:

1. current-run durable cache/store may be reused immediately by normalization;
2. if its mapping availability is later than the notification, downstream event `observed_at` is
   clamped to that later time;
3. if no current-run mapping exists, acquire the existing per-pool single-flight lock;
4. recheck current-run cache/store under the lock;
5. only then query prior-run historical identity using the notification's strict causal cutoff;
6. promote historical identity durably under the lock, at most once per current-run pool;
7. otherwise perform the existing bounded RPC resolution;
8. persist/reload canonical mapping before publication;
9. same-pool waiters reuse the first durable result.

The inherited RPC semaphore/transport ceiling is unchanged.

### SQLite fairness

V5 does **not** retune v4's fairness constant. It keeps the v4 rule so this experiment tests removal
of redundant resolution demand rather than silently changing two independent knobs at once.

There is still exactly one active SQLite writer admission at a time.

### Writer headroom

V5 records:

- queue depth samples at every writer submission;
- queue depth p50 / p95;
- queue high-water;
- per-request writer queue-wait p95;
- per-request writer result-wait p95;
- writer batch-service p95;
- pending/queue-before-close;
- inherited batch utilization.

A sustained writer promotion warning is raised if any is true:

1. writer has pending work at close;
2. queue-before-close is nonzero;
3. writer result-wait p95 >=4.0s;
4. queue-depth p95 >=80% of the configured PumpSwap persistence-worker reservoir.

A high-water spike alone does not block promotion.

## Preventive acceptance policy

The official frozen systems gate remains unchanged:

1. no worker/traceback errors
2. drops = 0
3. reference asset episodes = 0
4. coverage >=95%
5. true backlog <=5%
6. Pump p95 <=5s
7. PumpSwap p95 <=5s
8. hydration budget skips = 0
9. wallet/flow bundles nonempty
10. replay/audit valid
11. reservation-superset violations = 0

V3's engineering headroom also remains:

- no monitored causal stage p95 >=4.0s

V5 adds resolver evidence plus sustained writer headroom. Possible wrapper outcomes:

- `FAIL_TAILFIX_V5_UNCHANGED_11_GATE`
- `HOLD_TAILFIX_V5_PREVENTIVE_HEADROOM`
- `PASS_TAILFIX_V5_11_GATE_WITH_CAUSAL_AND_THROUGHPUT_HEADROOM`

Only the exact PASS classification can be considered for a later fresh V68 acquisition.

## Deterministic tests required before live

V5 must prove at least:

1. concurrent historical reuse for one pool produces one current-run durable promotion;
2. multiple older queued events for one newly resolved pool share one network resolution;
3. current-run delayed identity reuse clamps normalized event availability forward;
4. prior-run historical identity after the notification cutoff is not reused;
5. CreatePool identity learning is async and durable;
6. normalized trade keys, side semantics and effective-observed-at rule remain unchanged;
7. v5 resolver/normalizer/writer seams restore on success and exception;
8. transient writer high-water with healthy p95 does not create a false warning;
9. sustained queue-depth p95 does warn;
10. writer result-wait p95 >=4s does warn;
11. incomplete drain does warn;
12. official systems FAIL cannot be rescued by preventive evidence;
13. missing preventive evidence or any latency/writer warning produces HOLD;
14. full repository compile/tests remain green.

## Deferred known serialization

The inherited PumpSwap ready path still has one finalizer consumer. V5 deliberately does not raise
that worker count yet. In the v4 run, stateful/demoted ready-queue tails occurred downstream of a
~17s global normalization burst, so they are not yet proven to be an independent capacity limit.

If a valid v5 live run removes normalization/barrier warnings but ready-queue p95 remains >=4s, then
a separate bounded multi-finalizer change may be justified. It must preserve scheduler-issued
per-asset FIFO and same-token Pump/PumpSwap serialization. V5 does not speculate on that before the
upstream burst cause is removed.

## Scientific invariants unchanged

V5 does not change:

- Solana detector thresholds
- episode/trigger semantics
- reservation-superset fail-closed rule
- global ingress reservation correctness
- per-asset FIFO
- same-token cross-source serialization
- replay/conflict audit policy
- historical causal cutoff
- provider pacing
- route-only notional/slippage/horizons
- v68 feature/bins/direction/horizon/economic PASS rules
- RPC concurrency ceiling
- official 5s latency threshold

V68 remains `NOT_EVALUATED` until a fresh systems-only profile passes all required gates/headroom.
