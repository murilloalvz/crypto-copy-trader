# End-to-End Replay Integrity Incident — v5d

Date: 2026-09-03  
Mode: **PAPER / RESEARCH / READ ONLY**

## Classification

`unified-market-smoke-20260903-05d` is **ABORTED BEFORE SUMMARY — TRIGGER REPLAY INTEGRITY FAILURE**.

It is not a throughput, latency, profitability, or strategy result. No detector threshold should be tuned from it.

## Observed failure

The clean v5d capacity stress progressed through Pump and PumpSwap acquisition, persistence, radar evaluation, and episode/bundle creation before aborting in the Pump radar coordinator:

```text
ValueError: market trigger already exists with different data
```

Path:

```text
pump_radar_coordinator
-> evaluate_persisted_pump_notification_for_radar_v4
-> evaluate_market_token
-> assign_market_opportunity_trigger
-> market_opportunity_episode_store
```

## Root cause

The lower persistence layers had already been hardened for concurrent/replayed websocket observations, but `market_opportunity_episode_store` still treated `trigger_key` as if every replay had to reproduce all derived fields byte-for-byte, including the current `observed_at`, direction and trigger kind.

That assumption is invalid for the live concurrent pipeline. `trigger_key` identifies one raw source notification/token evaluation. The same source notification can be delivered/replayed later. By that later time, additional observations may already exist in the store, so recomputing the detector can produce a different descriptive direction or trigger kind even though no new raw trigger identity exists.

A replay must therefore not create a second raw trigger or second episode, and it must not abort the entire acquisition run merely because recomputation later sees a different surrounding market state.

## Trigger/episode replay policy

The trigger store now freezes the first persisted raw trigger for a given `(acquisition_run_key, trigger_key)`:

- exact later replay is idempotent;
- conflicting later replay is written to `market_trigger_replay_conflicts`;
- the original trigger-to-episode assignment remains canonical;
- conflicting replay does not create additional flow, triggers, episodes or enrichment admission;
- an earlier replay arriving after a trigger was already persisted is audited but does not retroactively backdate/repartition an already-opened episode;
- true referential corruption, such as a trigger referencing a missing episode, remains fatal.

The conservative no-retroactive-backdate rule is intentional. Radar coordinators already release notifications in websocket ingress order. Repartitioning an episode after downstream admission would mutate an already-observed experiment boundary.

## Additional end-to-end review

The v5d failure triggered a review of the remaining hot-path state stores rather than another one-line exception fix.

### PumpSwap pool schema hot path

`pumpswap_pool_store` was still executing `CREATE TABLE / CREATE INDEX IF NOT EXISTS` on repeated pool lookups and records. This duplicated the same class of SQLite DDL overhead already removed from the market observation and opportunity episode stores in v5.

The pool store now caches schema readiness per active SQLite database path under a thread lock. This is an operational optimization only; detector thresholds and market semantics are unchanged.

### PumpSwap pool identity replay

Concurrent resolution can learn a pool through RPC while a `CreatePoolEvent` for the same pool is also being processed. The pool store now owns canonical identity semantics:

- same identity, earlier observation: first-known time/provenance is moved earlier;
- same identity, later corroboration: canonical mapping remains unchanged;
- conflicting identities are audited in `pumpswap_pool_mapping_conflicts`;
- earliest observed identity wins;
- equal-time conflicts use a deterministic stable identity tie-break while remaining explicitly audited;
- ambiguous cross-run historical identities are not reused; the resolver returns no historical mapping and falls back to fresh resolution instead of trusting ambiguity.

### Concurrent resolver canonical reload

After an async resolution finishes, `ConcurrentReusablePumpSwapPoolResolver` now reloads the canonical mapping from the store before returning and cacheing it. This closes a race where an RPC object could become stale relative to a racing earlier `CreatePoolEvent`.

## Failure diagnostics

`unified_market_latency_smoke_v5.py` now prints replay telemetry in a `finally` block so diagnostics survive an unrelated future failure before normal `SUMMARY` output:

```text
pump_replay_conflicts=...
market_replay_conflicts=...
market_trigger_replay_conflicts=...
pumpswap_pool_mapping_conflicts=...
```

Unknown errors still fail fast. These counters are audit evidence, not automatic PASS/FAIL criteria by themselves.

## Validation

Final implementation validation on branch `fix/end-to-end-replay-integrity-v5d`:

- `python -m compileall -q .`: PASS;
- `python -m unittest discover -s tests -q`: **571 tests, 0 failures**;
- CI: PASS.

Regression coverage includes:

- exact trigger replay idempotency;
- conflicting trigger replay audit without duplicate episode;
- conservative handling of an earlier replay after episode assignment;
- PumpSwap pool first-known canonicalization;
- conflicting pool identity audit;
- ambiguous historical identity not reused;
- concurrent resolver returns store-canonical mapping rather than a stale resolution object.

## What did not change

No changes were made to:

- radar thresholds;
- 30s / 300s windows;
- transaction-awareness gate;
- fresh-market 120s rule;
- episode 60s acquisition window for new trigger keys;
- wallet intelligence policy;
- Jupiter integration;
- risk/hazard integration;
- execution policy;
- economic outcome definition.

## Next gate

Run one fresh 120-second capacity/latency stress with the same frozen operational configuration and a never-used `run_key`.

PASS criteria remain:

1. no traceback / worker errors;
2. zero dropped notifications;
3. zero reference-asset episodes;
4. radar coverage >=95%;
5. deadline backlog <=5% of received;
6. Pump radar end-to-end p95 <=5s;
7. PumpSwap radar end-to-end p95 <=5s;
8. budget skips == 0;
9. admitted bundles are not systematically empty.

Any non-zero replay-conflict counters must be inspected before a long acquisition.

If the fresh run still fails latency/capacity after reaching `SUMMARY`, do not keep increasing concurrency blindly. The next architectural step is removing global PumpSwap cross-pool head-of-line blocking while preserving causal ordering at the opportunity-asset level.

Jupiter and the 12h acquisition remain blocked until this operational gate passes.
