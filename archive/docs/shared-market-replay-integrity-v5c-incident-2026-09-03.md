# Shared Market Replay Integrity — v5c Incident (2026-09-03)

Mode: PAPER / RESEARCH / READ ONLY.

## Trigger

A clean v5 capacity-stress run using a new namespace:

`unified-market-smoke-20260903-05c`

reproduced a fatal PumpSwap persistence conflict:

```text
ValueError: market trade event already exists with different data
```

The traceback terminated inside `record_market_trade()` called by `persist_pumpswap_notification_normalized()`.

Because `05c` used a fresh `run_key`, this reproduction rules out contamination from the previously aborted `05b` namespace. The incident is therefore a valid shared-store replay/concurrency problem, not a throughput/latency result.

## Scientific classification

`05c` = **ABORTED BEFORE SUMMARY — SHARED REPLAY INTEGRITY FAILURE**.

It must not be used to infer:
- radar coverage;
- queue capacity;
- p95 latency;
- profitability;
- detector quality.

## Root semantic issue

Concurrent persistence can complete out of websocket observation order. In addition, normalized PumpSwap identity can be replayed differently for the same immutable event key while the stream is running at `confirmed` commitment.

The old shared store assumed:

```text
same run_key + event_key => same identity forever
```

and raised on any divergence. That fail-fast behavior protected silent mutation but made a single replay ambiguity fatal to the entire acquisition run.

## Resolution

`src/market_observation_store.py` now owns replay-conflict semantics for all shared market observations.

Rules:
1. exact replay remains idempotent;
2. collector `observed_at`, not SQLite completion order, defines causal availability;
3. an exact replay with earlier `observed_at` moves the canonical availability timestamp earlier;
4. a conflicting identity is written to `market_replay_conflicts` with stored/incoming identity, timestamps and canonical action;
5. the earlier observed identity remains canonical;
6. if timestamps are equal at second resolution, a stable serialized-identity ordering is used only as a deterministic tie-break and the ambiguity remains explicitly audited;
7. a conflict returns duplicate/replay semantics to callers and does not create an extra market-flow event;
8. conflict no longer crashes acquisition.

Pump-specific `pump_replay_conflicts` remains as adapter-level telemetry for the earlier Pump incident. Shared normalized paths, including PumpSwap, use `market_replay_conflicts`.

## Smoke telemetry

`unified_market_latency_smoke_v5.py` now prints both:

```text
pump_replay_conflicts=...
market_replay_conflicts=... breakdown={...}
```

The shared count is queried once after the run, avoiding race-prone per-worker attribution.

## Validation

Latest CI on the implementation branch:
- `python -m compileall -q .` PASS;
- full unittest suite PASS;
- 565 tests / 0 failures on the pre-tie-break commit; final tie-break commit CI also PASS.

Added regression coverage for:
- exact replay;
- earlier completion-order inversion;
- later conflicting identity retention;
- earlier conflicting identity replacement;
- PumpSwap normalized replay conflict without acquisition crash.

## Next gate

Run a fresh namespace with the exact frozen v5b capacity configuration. Do not reuse `05b` or `05c`.

The next run is valid only if it reaches SUMMARY. After that, evaluate the pre-frozen throughput/latency criteria. Non-zero replay-conflict telemetry is not an automatic FAIL, but it must be inspected before any long acquisition.

Jupiter and the 12h acquisition remain blocked until latency/capacity passes.