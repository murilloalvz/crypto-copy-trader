# PumpSwap pool identity/context — decision (2026-09-10)

## Decision

**ADAPT: persistent causal identity cache + bounded asynchronous single-flight lazy lookup.**

Do not block the signal hot path on pool RPC. Do not backfill the first unknown trade. Do not assume SOL quote orientation.

This is a systems/context-availability decision only. No economic edge was evaluated.

## Evidence

### Persistent cache baseline

Corrected adapter audit over the source shadow:

- PumpSwap trade events: 2,395;
- cache-adapted events: 317;
- missing context: 2,078;
- persistent source-shadow cache coverage: 13.2359%.

### Corrected lazy-lookup counterfactual

The replay is valid:

- decoded identity rows: 75;
- initial identity rows: 75;
- invalid identity rows: 0;
- unique observed pools: 177;
- first unknown trade is never retroactively recovered.

Context coverage under fixed successful lookup/decode delays:

- 50 ms: 91.6493%;
- 100 ms: 89.5616%;
- 250 ms: 86.7641%;
- 500 ms: 82.0042%;
- 1,000 ms: 74.5303%.

These are structural counterfactuals, not live integrated lookup measurements.

### Real Helius Free lookup latency

`getAccountInfo`, commitment `processed`, 177 observed PumpSwap pools:

- accounts found: 177/177;
- request errors: 0;
- owner mismatches: 0;
- p50: 231.2241 ms;
- p95: 458.5871 ms;
- p99: 498.7377 ms;
- max: 504.9429 ms.

The measured p95 is closest to the replay's 500 ms scenario, where structural context coverage was ~82%. That is supporting architecture evidence only; it is **not** a claim that a live integrated system will achieve exactly 82%.

## Target architecture

```text
PumpSwap trade/event
    |
    +--> identity already causal in persistent/in-memory cache
    |       -> adapt immediately
    |
    +--> identity unknown
            -> trade remains MISSING_CONTEXT for its own T0
            -> enqueue bounded single-flight lookup by pool
            -> lookup/decode completes asynchronously
            -> identity becomes available only from local completion time forward
            -> later trades may use it
```

Rules:

1. The first cache-miss trade remains missing.
2. A later lookup result is never backfilled into earlier T0.
3. Concurrent misses for the same pool coalesce into one in-flight lookup.
4. Lookup queue/concurrency is bounded and observable.
5. RPC errors/missing accounts/owner mismatch remain explicit missingness.
6. Persistence and research/audit remain off the signal hot path.
7. Startup/bootstrap identities are causal only from their actual local availability time; they do not rewrite a historical source shadow.

## Promotion gate for integrated live use

Before calling this path production-ready, measure in a fresh live window:

- cache-hit share;
- unknown-pool first-trade count;
- lookup requests vs deduped/coalesced misses;
- lookup p50/p95/p99;
- lookup error/missing/decode-failure rates;
- later-trade context recovery share;
- queue depth/oldest age;
- signal hot-path p95/p99 with lookups enabled;
- zero retroactive context violations.

A live result materially below the counterfactual expectation should trigger diagnosis of event spacing, request contention, provider pacing, or decode/persistence integration before changing the provider.
