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
- add `trace_attribution_complete=True/False`;
- require complete ingress/normalization/reservation/submit-or-skip attribution before accepting `dominant_clock`;
- make the systems diagnostic guard fail closed with `FAIL_V50_DIAGNOSTIC_INCOMPLETE` on an incomplete trace.

No market, detector, persistence, FIFO, provider or economic semantics changed in this correction.

## Interpretation

v50 is diagnostic only. `dominant_clock` is a descriptive attribution, not a new pass/fail threshold.

If `global_sequence_barrier` dominates, the next engineering task is to design a causally safe replacement for the global pre-ticket watermark while preserving every ordering dependency that can mutate the same token/episode state. No relaxation is permitted merely to improve latency.

If another clock dominates, change only that measured stage.

A `dominant_clock` value is scientifically usable only when `trace_attribution_complete=True`.

## Scientific guard

Do not run v48 while the corrected v50 causal attribution is unresolved. The latest live run established same-run systems 11/11 for the v49 scheduling profile, but the remaining diagnostic question is still which causal clock produced the residual tail. Do not inspect or use prospective Flow60 economics to tune systems.
