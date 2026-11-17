# PumpSwap causal-tail tailfix v1 — systems protocol

Date: 2026-09-08

Mode: **PAPER / RESEARCH / READ ONLY**.

## Why this exists

The attempted V68 prospective acquisition stopped before forward economics because the frozen
same-run systems gate was 10/11. The only failed gate was PumpSwap causal-pipeline p95:

- Pump p95: 4891.0 ms — PASS (`<= 5000 ms`)
- PumpSwap p95: 8870.6 ms — FAIL (`<= 5000 ms`)
- coverage: 100%
- true deadline backlog: 0%
- drops: 0
- worker errors: 0
- reservation-superset violations: 0

V50 attributed the dominant causal clock to per-asset dependency, while v51 showed a large
stateful ready-queue tail. The inherited v22/v54 topology also routes Pump and PumpSwap stateful
trigger finalization through one shared one-thread executor.

The V68 economic hypothesis therefore remains **NOT EVALUATED**. This change is not an economic
retune and must not be interpreted as evidence for or against `flow60_buy_share_pct`.

## Tailfix v1 change

Tailfix v1 changes one systems scheduling boundary only:

1. Pump stateful trigger finalization has one bounded one-thread lane.
2. PumpSwap stateful trigger finalization has one bounded one-thread lane.
3. Both lanes share the same process-local lock registry keyed by trigger token mint.
4. A job touching multiple trigger tokens acquires the complete sorted token set.
5. The same token therefore cannot finalize concurrently across Pump and PumpSwap.
6. Different tokens may finalize concurrently across the two sources.
7. Any synchronous stage that cannot be classified as a trigger-bearing Pump/PumpSwap prepared
   value falls back to the inherited runner; a completed systems smoke with such a fallback is
   rejected fail-closed.

This removes **global cross-source serialization for unrelated tokens** without removing
**same-token serialization**.

## What remains frozen

Tailfix v1 does **not** change:

- market detector thresholds or method version;
- episode window or first-persisted canonical semantics;
- no-retroactive-enrollment handling;
- Pump ingress order;
- PumpSwap reservation tickets or per-asset FIFO;
- v27 continuation proof/demotion semantics;
- replay behavior;
- causal `chain_time` / `observed_at` / as-of rules;
- resolver budget or hydration semantics;
- v54 demand-only resolver admission;
- hazard provider or provider pacing;
- route-only $25 notional or 100 bps slippage;
- V68 feature, bins, favorable direction, 900s primary horizon, support requirements or economic
  PASS/FAIL criteria;
- the unchanged 11/11 systems threshold, including PumpSwap p95 `<= 5s`.

## Why same-token locking is required

`assign_market_opportunity_trigger` deliberately retains the first persisted canonical episode
and audits late-earlier cross-source evidence instead of retroactively reshaping the sample.
Running two same-token stateful assignments concurrently would create an unnecessary new race
around the read-before-write episode decision. Tailfix v1 does not permit that race.

The optimization is therefore narrower:

```text
Pump token A stateful commit  ─┐
                               ├─ may overlap when tokens differ
PumpSwap token B stateful commit ┘

Pump token X stateful commit  ───── serialized ───── PumpSwap token X stateful commit
```

## Fail-closed telemetry

The smoke prints:

- `pump_calls`
- `pumpswap_calls`
- `fallback_calls`
- `max_parallel_calls`
- `same_token_overlap_violations`
- per-source commit-lane queue waits
- cross-source token-lock wait
- stateful commit service time

A completed tailfix systems run requires:

- `fallback_calls=0`
- `same_token_overlap_violations=0`
- both Pump and PumpSwap lanes observed
- the pre-existing v54 diagnostics present
- unchanged systems gate = **11/11**

No forward collector is allowed in the systems-only runner.

## Validation order

1. Unit/CI tests.
2. Fresh 120s **systems-only** run using a fresh run key.
3. If 11/11 passes, preserve that as the accepted systems profile for the next clean V68
   acquisition attempt.
4. Only then run a fresh V68 prospective acquisition identity.

A systems PASS proves only that this scheduling profile meets the frozen operational gate under
that observed load. It does not prove economic edge, executable fill quality, realized PnL, or
live-money readiness.
