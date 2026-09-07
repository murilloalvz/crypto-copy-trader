# v50 PumpSwap causal clock diagnostic

Date: 2026-09-07

Mode: **PAPER / RESEARCH / READ ONLY**

## Why v50 exists

The v49b systems-only run passed 10/11 frozen systems gates. Pump recovered to p95 1.920s, while PumpSwap remained above the frozen 5s gate at p95 10.099s.

The important v49b shape was:

- PumpSwap normalization-to-reservation p95: 9.432s
- prepared-to-submit p95: 8.451s
- reservation-to-submit p95: 0.819s
- scheduler dispatch p95: 0ms
- per-asset dependency wait p95: 0ms, max about 4.993s
- writer batch service p95: 91ms
- all PumpSwap backlog categories at deadline: 0
- reservation superset violations: 0
- hydration budget skips: 0

This shape is consistent with a global ingress-sequence reservation watermark holding already-normalized successors behind an earlier sequence whose normalization completes late. v50 measures that hypothesis directly before any scheduler change.

## Frozen semantics

v50 changes no scheduling behavior. It runs the exact v49 scheduling profile and observes timestamps only.

The following remain unchanged:

- detector thresholds and method version
- episode identity/window rules
- persistence and replay semantics
- causal `as_of` rules
- global ingress reservation ordering
- per-asset FIFO tickets
- v34/v42 proof-based continuation demotion
- provider pacing
- route-only BUY/SELL definitions
- Flow60 hypothesis and bins
- systems latency gates

The forward SELL collector is intentionally blocked by the systems-only runner, exactly as in v49.

## Diagnostic reconstruction

For each PumpSwap ingress sequence, v50 records:

1. stream ingress timestamp;
2. causal normalization completion timestamp;
3. reservation creation timestamp;
4. scheduler submit/skip timestamp;
5. dependency-ready timestamp when applicable.

Because the v19 reservation coordinator issues tickets strictly by ingress sequence, sequence `i` cannot receive a reservation before every sequence `0..i` has produced its normalization hint.

For each sequence, v50 reconstructs:

- `self_ingress_to_normalization`;
- `global_prefix_normalization_barrier` = prefix-max normalization completion among `0..i` minus this item's own normalization completion;
- `post_prefix_reservation_coordinator` = reservation creation minus that prefix-max completion;
- `normalization_to_reservation`;
- `reservation_to_submit`;
- `submit_to_dependency_ready`.

A sequence whose normalization time is the prefix maximum is identified as the blocker for already-normalized successors until a later prefix maximum supersedes it.

Top blockers are reported with:

- sequence;
- transaction signature (shortened in console output);
- reservation assets;
- blocker self-normalization latency;
- number of successors blocked;
- total successor barrier time;
- maximum successor barrier time.

## First live v50 attempt — systems evidence valid, attribution invalid

Run:
`route-research-systems-diagnostic-20260907-50`

The underlying systems path passed the unchanged v43 gate **11/11**:

- coverage 100.0%
- true backlog 0%
- Pump p95 3.324s
- PumpSwap p95 3.179s
- drops 0
- worker errors 0
- hydration budget skips 0
- reservation superset violations 0

This is valid same-run systems evidence for the v49 scheduling profile.

However, the initial v50 tracer output was incomplete:

- stream ingress observed: 2230 versus 4802 PumpSwap notifications processed;
- normalization observed: 0;
- reservations attributed: 413;
- attributed rows: 0;
- `dominant_clock=insufficient_trace`.

Therefore the causal-clock attribution from that attempt is **invalid** even though the systems 11/11 result remains valid independently.

Root causes in diagnostic instrumentation:

1. notification correlation used `id(notification)` without retaining the notification object, allowing CPython object-id reuse during a high-throughput run;
2. v20 installs its own indexed normalization wrapper into v19 and calls a normalization primitive imported into the v20 module by value, bypassing the original v50 hook.

Corrections:

- retain each notification object for the lifetime of the trace so its `id()` cannot be recycled;
- instrument both the v19 entry point and the lower v20 normalization primitive;
- fail closed if exact ingress/normalization/reservation coverage is not captured.

No market, detector, persistence, FIFO, provider or economic semantics changed in this correction.

## Second live v50 attempt — systems PASS and global barrier identified

Run:
`route-research-systems-diagnostic-20260907-50b`

Same-run systems gate:

- coverage **99.5%**
- true backlog **0.482%**
- Pump p95 **1.838s**
- PumpSwap p95 **4.002s**
- result **11/11**
- drops 0
- worker errors 0
- hydration budget skips 0
- reservation superset violations 0
- forward collector did not start.

Corrected tracer coverage:

- ingress **3357/3357**
- normalization **3357/3357**
- reservations **3357/3357**
- attributed rows **3357/3357**
- submit/skip **3345/3357 = 99.643%**

Measured clocks:

- self ingress -> normalization p95 **369.3ms**
- global prefix normalization barrier p95 **3550.7ms**
- post-prefix reservation coordinator p95 **146.7ms**
- normalization -> reservation reconstructed p95 **3683.9ms**
- reservation -> submit p95 **996.0ms**
- submit -> dependency ready p95 **672.4ms** among stateful ready work
- `dominant_clock=global_sequence_barrier`.

Representative head-of-line blockers included:

- seq 768: self-normalization 4.425s, **131 successors blocked**, max successor wait 4.216s;
- seq 307: self-normalization 4.211s, **138 successors blocked**, max successor wait 4.143s;
- seq 63: self-normalization 6.284s, **138 successors blocked**, max successor wait 5.849s;
- seq 33: self-normalization 8.934s, **29 successors blocked**, max successor wait 8.560s.

This directly supports the previously inferred mechanism: an older ingress sequence whose immutable pool normalization completes late holds unrelated already-normalized successors behind the global reservation watermark.

The original guard still classified the run as `FAIL_V50_DIAGNOSTIC_INCOMPLETE` because 12 reservations had not reached submit/skip at the exact 120s deadline. Those 12 are exactly reflected by `pumpswap_reservation_waiting_payload=12` in the frozen systems snapshot.

## Diagnostic acceptance rule after v50b

Do **not** add a post-deadline drain. v19 intentionally cancels timed workers at the frozen systems deadline, so allowing extra processing after 120s would change the systems-gate semantics and make the run incomparable with historical v42/v44/v49 evidence.

Instead separate the causal stages:

### Global barrier attribution — exact requirement

Accept only when all are true:

- ingress > 0;
- normalization count == ingress count;
- reservation count == ingress count;
- attributed rows == ingress count.

This is the exact evidence required to reconstruct the global normalization-prefix barrier.

### Later lifecycle comparison — coverage requirement

Submit/skip occurs after reservation and can legitimately be truncated at the exact systems deadline. To compare its p95 against the fully observed reservation clocks without extending the run, require:

- submit/skip coverage >= **95%** of reservations.

This matches the existing systems coverage standard and remains fail-closed on material lifecycle truncation.

The diagnostic now prints separately:

- `barrier_attribution_complete`;
- `lifecycle_attribution_complete`;
- `lifecycle_submit_coverage_pct`;
- `causal_clock_attribution_acceptable`.

A dominant-clock attribution is accepted only when barrier attribution is exact, later lifecycle coverage is >=95%, and the trace is non-empty. Full lifecycle completion remains descriptive and is not manufactured by post-deadline draining.

## Interpretation

v50 is diagnostic only. `dominant_clock` is a descriptive systems attribution, not a new trading or economic rule.

The v50b evidence identifies the global ingress-sequence normalization barrier as the dominant remaining causal clock under that run. This does **not** imply the watermark should automatically be removed. Any future redesign must prove that no work capable of mutating the same token/episode state can overtake an earlier causal predecessor.

Two recent systems-only executions of the v49 profile have now produced 11/11 under the unchanged v43 gate (the first v50 run and v50b), while v50b directly attributed the residual tail to the global sequence barrier.

## Scientific guard

Do not use v50 as economic evidence. Flow60 remains frozen and prospectively NOT_EVALUATED. Do not change bins, horizon, detector or provider pacing from this systems diagnostic.

One final fresh v50 replication may be used to confirm `causal_clock_attribution_acceptable=True` under the corrected acceptance rule. If it also preserves systems 11/11, the v49 systems profile can be treated as independently validated for wiring into the frozen v48 acquisition path without changing economic semantics.
