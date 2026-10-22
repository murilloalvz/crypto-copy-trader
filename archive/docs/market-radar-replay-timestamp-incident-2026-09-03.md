# Market Radar Replay Timestamp Incident — 2026-09-03

Status: **RESOLVED / LOCAL RE-SMOKE PASS**

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

The run did not complete its requested 120-second window and remains **FAILED / PARTIAL**. Its already-persisted evidence is not deleted, but its counters must not be compared as a completed acquisition sample.

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

`src/market_observation_store.py` compares immutable event fields separately from `observed_at`.

Later identical replays return `False` (duplicate/replay) instead of raising.

Backdated replays remain errors.

Actual event mutations remain errors.

## Regression coverage

Tests cover:

- identical trade replay at a later `observed_at`;
- preservation of the original first-seen timestamp;
- rejection of a replay that would backdate availability;
- identical lifecycle replay at a later `observed_at`;
- existing mutation-conflict behavior;
- the exact Pump path: the same signature/event replayed by a later WebSocket delivery persists once, returns duplicate on replay and keeps the original first-seen clock.

Validation on the final executable fix state:

```text
python -m compileall -q .
python -m unittest discover -s tests -q
Ran 523 tests
OK
```

## Local re-smoke

After promotion and local sync, the user ran a fresh bounded validation with a new run key:

```text
python market_radar_smoke.py --run-key market-radar-smoke-20260903-03 --duration-seconds 120 --commitment confirmed
```

The full 120-second window completed without traceback.

Relevant totals:

```text
notifications=2034
decoded_trades=2111
sol_eligible=2037
persisted=2037
duplicate_or_replayed_eligible=0
raw_radar_hits=738
continuation_hits=707
unique_episodes=31
```

This particular live window contained no eligible provider replay, so the runtime did not need to exercise the duplicate branch during the smoke. That does not invalidate the fix: the exact replay behavior is regression-tested. The local smoke establishes that the corrected store semantics do not regress live acquisition and that the radar pipeline now completes normally under real traffic.

## Methodological consequence

No Market Opportunity Radar threshold was changed.

This was an operational/idempotence bug discovered before economic evaluation. The fix changes replay handling only; it does not use outcomes, P&L, future prices, or any post-T0 economic information.

## Final disposition

- `market-radar-smoke-20260903-02`: retained as **FAILED / PARTIAL** incident evidence;
- replay semantics: **FIXED + REGRESSION TESTED**;
- `market-radar-smoke-20260903-03`: **COMPLETED / LIVE OPERATIONAL PASS**;
- no need to rerun the failed `-02` key;
- no 12-hour acquisition is authorized yet.
