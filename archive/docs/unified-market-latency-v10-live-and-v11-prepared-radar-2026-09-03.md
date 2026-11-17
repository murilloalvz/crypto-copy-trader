# Unified Market Latency v10 live result and v11 prepared-radar split — 2026-09-03

## Scope

Mode remains **PAPER / RESEARCH / READ ONLY**.

This report records the live result of `unified_market_latency_smoke_v10.py` and the
architecture chosen for v11. No detector threshold, causal clock, replay rule, pool identity
policy, episode rule, or provider policy was changed in response to the live result.

## v10 command

```powershell
python unified_market_latency_smoke_v10.py --run-key unified-market-smoke-20260903-10 --duration-seconds 120 --commitment confirmed --max-hydrations 1500 --rpc-timeout-seconds 3 --pump-batch-size 32 --pump-batch-max-wait-ms 25 --pumpswap-workers 24 --pumpswap-radar-workers 8 --max-concurrent-resolutions 18 --queue-size 5000
```

## v10 live result

Run: `unified-market-smoke-20260903-10`

- elapsed: 121.4s;
- received: Pump 1,743 + PumpSwap 3,789 = 5,532;
- drops: 0;
- worker errors: 0;
- persistence completed: Pump 1,743 / PumpSwap 3,787;
- radar processed: Pump 1,743 / PumpSwap 2,460;
- total radar coverage: **76.0% — FAIL**;
- reference asset episodes: 0;
- hydration budget skips: 0;
- RPC failures: 0;
- replay conflicts: 0 across Pump/shared market/trigger/pool mapping.

Pump remained inside the frozen latency gate:

- Pump persistence queue p95: **2.242s**;
- Pump radar end-to-end p95: **3.864s — PASS**.

PumpSwap failed strongly:

- persistence queue wait p50/p95/max: **10.807s / 29.094s / 33.188s**;
- persistence service p50/p95/max: **0.016s / 2.754s / 13.985s**;
- persist-complete -> reservation p50/p95/max: **5.321s / 11.112s / 13.987s**;
- scheduler task dispatch p95: **0.999s**;
- causal dependency wait p50/p95/max: **11.894s / 54.449s / 68.103s**;
- ready queue wait p50/p95/max: **1.168s / 10.644s / 15.458s**;
- radar evaluation p50/p95/max: **0.182s / 1.138s / 2.535s**;
- full pipeline p50/p95/max: **39.279s / 90.996s / 101.449s**.

The detector itself was not expensive:

- transaction-view read p95: 53.8ms;
- history read p95: 69.0ms;
- aggregate radar DB read p95: 106.9ms;
- detector compute p95: 0.3ms;
- episode assignment p95: 16.6ms;
- post-evaluation handling p95: 0ms.

## Root-cause classification

### Primary: hot-asset causal serialization

The v10 scheduler recorded:

- 3,733 reservations;
- 222 assets with reservations;
- 1,198 jobs still waiting on causal predecessors at deadline;
- only 75 jobs ready;
- max waiting depth for a single asset: **108**;
- 11 assets accounted for 50% of total causal wait;
- 32 assets accounted for 90% of total causal wait.

The hottest assets each accumulated roughly 137-159 reservations and around 87-108 waiting
jobs. Their causal wait p95 was around 61-65 seconds.

This is not the old v7 starvation bug. Workers are no longer being consumed while waiting.
Instead, v8-v10 serialize the **entire radar evaluation** for every notification sharing an
asset. Under a hot token burst, read/detect work that is causally bounded by `as_of` is being
forced through a serial chain even though it does not mutate episode state.

Classification:

**FAIL — PUMPSWAP HOT-ASSET SERIALIZATION, WITH SECONDARY PERSISTENCE/REORDER PRESSURE.**

### Secondary: PumpSwap persistence burst pressure

v10 also showed a 29.1s p95 before persistence started and an 11.1s p95 from persistence
completion to ingress-ordered reservation. This cannot be ignored. v11 deliberately does not
change persistence yet because the next experiment should isolate the effect of removing
unnecessary radar serialization first.

If v11 removes the causal radar tail but latency remains dominated by persistence queue/reorder,
the next change should target PumpSwap persistence architecture rather than detector workers.

## Why same-asset preparation can run in parallel

For PumpSwap radar v3/v4, the expensive/read-only part is:

1. load the transaction's canonical persisted observations;
2. derive the token's causal `token_as_of`;
3. load token history with `observed_at <= token_as_of`;
4. run the frozen movement detector.

Those steps do not read or mutate opportunity episode state. Later-persisted observations are
excluded by the `as_of` boundary.

The stateful phase is `assign_market_opportunity_trigger(...)`, because first-trigger episode
assignment must remain ordered for a token.

Therefore v11 splits radar into:

```text
persistence completed
        |
        +--> parallel prepare
        |    transaction view
        |    causal history read
        |    frozen detector
        |
ingress-order asset reservation
        |
        +--> per-asset FIFO barrier
                 |
                 +--> finalize trigger / episode assignment
                 +--> episode-scoped enrichment
```

A later notification may finish preparation before an earlier notification for the same asset,
but the ticket issued from ingress order prevents later finalization from passing its predecessor.

## v11 code

New bridge:

- `src/pumpswap_radar_bridge_v5.py`
  - `prepare_persisted_pumpswap_notification_for_radar_v5`;
  - `finalize_prepared_pumpswap_radar_v5`.

New smoke:

- `unified_market_latency_smoke_v11.py`.

Tests cover:

- prepare phase creates no episode side effects;
- finalization matches v4 trigger/episode semantics;
- sequential prepared triggers keep the same canonical first episode trigger;
- a later reservation submitted before its predecessor still cannot violate FIFO.

Validation after implementation:

- `python -m compileall -q .`: PASS;
- **590 tests / 0 failures**;
- GitHub Actions CI: PASS.

## Frozen v11 configuration

Keep:

- duration 120s;
- commitment confirmed;
- Pump batch size 32;
- Pump max batch wait 25ms;
- PumpSwap persistence workers 24;
- PumpSwap prepare workers 8;
- PumpSwap finalizer workers 1;
- max concurrent resolutions 18;
- max hydrations 1500;
- queue size 5000.

Do not add workers or tune detector thresholds based on the v10 result.

## v11 decision gate

The original latency safety conditions remain:

1. no traceback/worker errors;
2. drops 0;
3. reference asset episodes 0;
4. total radar coverage >=95%;
5. total deadline backlog <=5% of received;
6. Pump radar p95 <=5s;
7. PumpSwap causal result availability p95 <=5s;
8. hydration budget skips 0;
9. bundles not systematically empty;
10. replay counters explainable and no integrity corruption.

v11 additionally reports the PumpSwap backlog by stage so `pumpswap_total_radar` is no longer
mislabelled as reorder backlog:

- actual order/reorder queue;
- prepare queue;
- prepared waiting for reservation;
- reservation waiting for prepare;
- ready finalization queue;
- causal finalization waiters.

## If v11 fails

Interpret in this order:

- persistence queue still dominates -> design PumpSwap resolve/SQLite persistence pipeline;
- actual order/reorder dominates -> remove global HOL without weakening canonical identity;
- prepare queue dominates -> optimize read preparation / thread-pool usage;
- finalization causal wait remains high -> verify stateful episode commit cost and ticket release;
- finalization ready queue dominates -> finalizer capacity is insufficient;
- all stages low but E2E high -> reconcile clocks before any architecture change.

Jupiter, risk/hazard integration and the 12h collection remain blocked until the frozen unified
latency gate passes.
