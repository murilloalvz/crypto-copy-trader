# Market Radar Replay Timestamp Incident — 2026-09-03

Status: **FIXED IN CODE / AWAITING LOCAL RE-SMOKE**

Mode: **PAPER / RESEARCH / READ ONLY**

## Incident

During the second bounded live Market Radar smoke:

```text
python market_radar_smoke.py --run-key market-radar-smoke-20260903-02 --duration-seconds 120 --commitment confirmed
```

the collector opened at least one opportunity episode and then stopped with:

```text
ValueError: market trade event already exists with different data
```

The run did not complete its requested 120-second window and must therefore remain **FAILED / PARTIAL**. Its already-persisted evidence is not deleted, but its counters must not be compared as a completed acquisition sample.

## Root cause

Pump trade identity is keyed deterministically by acquisition run plus:

```text
pump:<signature>:<event-index>
```

The same on-chain event may be delivered more than once by an RPC/WebSocket provider. The immutable event identity remained the same, but a later delivery naturally received a later local `observed_at`.

`record_market_trade()` and `record_market_lifecycle()` were comparing `observed_at` as if it were part of immutable event identity. Therefore an otherwise identical replay was incorrectly classified as a mutation conflict.

## Correct causal semantics

`observed_at` is a collector availability boundary.

For one stable `(acquisition_run_key, event_key)`:

- the first persisted `observed_at` is the causal first-seen time;
- an identical replay with the same or later `observed_at` is idempotent and must not create a new row;
- the stored first-seen `observed_at` is preserved;
- a replay claiming an earlier `observed_at` is rejected, because the store must never retroactively backdate availability;
- any change to immutable event identity/data still raises a conflict.

The same rule applies to lifecycle observations.

## Fix

`src/market_observation_store.py` now compares immutable event fields separately from `observed_at`.

Later identical replays return `False` (duplicate/replay) instead of raising.

Backdated replays remain errors.

Actual event mutations remain errors.

## Regression coverage

Tests now cover:

- identical trade replay at a later `observed_at`;
- preservation of the original first-seen timestamp;
- rejection of a replay that would backdate availability;
- identical lifecycle replay at a later `observed_at`;
- existing mutation-conflict behavior;
- the exact Pump path: the same signature/event replayed by a later WebSocket delivery persists once, returns duplicate on replay and keeps the original first-seen clock.

Validation on the final fix branch:

```text
python -m compileall -q .
python -m unittest discover -s tests -q
Ran 523 tests
OK
```

## Methodological consequence

No Market Opportunity Radar thresholds were changed.

This was an operational/idempotence bug discovered before economic evaluation. The fix changes replay handling only; it does not use outcomes, P&L, future prices, or any post-T0 economic information.

## Next validation

Do not resume the partial `market-radar-smoke-20260903-02` as a completed smoke.

After the fix is promoted and synced locally, run a new bounded smoke with a fresh run key. A successful completion should confirm that provider replays are counted as `duplicate_or_replayed_eligible` instead of terminating the collector.
