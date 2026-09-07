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

## Interpretation

v50 is diagnostic only. `dominant_clock` is a descriptive attribution, not a new pass/fail threshold.

If `global_sequence_barrier` dominates, the next engineering task is to design a causally safe replacement for the global pre-ticket watermark while preserving every ordering dependency that can mutate the same token/episode state. No relaxation is permitted merely to improve latency.

If another clock dominates, change only that measured stage.

## Scientific guard

Do not run v48 while v50/v49 systems evidence is unresolved. Do not inspect or use prospective Flow60 economics to tune systems.
