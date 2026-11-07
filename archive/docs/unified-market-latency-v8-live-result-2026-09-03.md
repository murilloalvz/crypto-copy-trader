# Unified Market Latency v8 — Live Result

Mode: PAPER / RESEARCH / READ ONLY.

Run: `unified-market-smoke-20260903-08`
Duration: 120s

## Frozen gate result

- worker errors: PASS (`{}`)
- drops: PASS (`0`)
- reference-asset episodes: PASS (`0`)
- radar coverage >=95%: FAIL (`75.6%`)
- total deadline backlog <=5%: FAIL (PumpSwap reorder `1374` plus small ingress/inflight backlog)
- Pump radar p95 <=5s: PASS (`2.319s`)
- PumpSwap radar p95 <=5s: FAIL (`54.973s`)
- hydration budget skips: PASS (`0`)
- admitted bundles populated: PASS (`79` episodes, wallet/flow bundles populated)
- replay conflict counters: PASS for this run (`0` across Pump/shared market/trigger/pool mapping)

Classification: **PUMP PASS / PUMPSWAP RADAR CAPACITY FAIL**.

## Important telemetry

- PumpSwap received: `3553`
- PumpSwap persistence completed: `3531` (~29.4/s)
- PumpSwap radar processed: `2157` (~18.0/s)
- PumpSwap persistence p95: `497.7ms`
- PumpSwap radar service p50/p95: `49.2ms / 789.7ms`
- PumpSwap end-to-end p50/p95: `11.732s / 54.973s`
- scheduler reservations: `3083`
- reported ready backlog: `50`
- reported waiting backlog: `0`

The reported `waiting_backlog=0` is not trustworthy for v8 because the runner cancelled scheduler waiters in `finally` before printing the summary. This telemetry defect is fixed before v9 by preserving a pre-cancellation scheduler snapshot.

## v9 decision

v9 does not change detector thresholds, causal clocks, persistence semantics, replay semantics, or per-asset FIFO scheduling. It is a measured capacity stress:

- PumpSwap persistence arrival rate in v8: ~29.4 notifications/s
- 4 PumpSwap radar workers delivered ~18.0 notifications/s
- therefore 4 workers were demonstrably below arrival capacity under this burst
- v9 raises PumpSwap radar workers to 8 and preserves the real pre-cancellation ready/waiting backlog

This is not blind concurrency tuning; it is a bounded stress justified by measured service throughput. If v9 still fails, do not raise workers again automatically. Use the preserved scheduler backlog plus radar service-time telemetry to determine whether hot-asset causal serialization or shared SQLite/read contention is the next bottleneck.

Jupiter/risk/12h remain blocked until the latency gate passes.
