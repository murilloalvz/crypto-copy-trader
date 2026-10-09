# Route Research v49 — Systems Stability Protocol

Date: 2026-09-07
Mode: **PAPER / RESEARCH / READ ONLY**

## Why v49 exists

The first fresh v48 holdout attempt stopped fail-closed before forward economic collection because the frozen v44/v46 acquisition path passed only 9/11 same-run systems gates:

- Pump radar p95: 6498.4 ms (>5000 ms)
- PumpSwap pipeline p95: 8898.1 ms (>5000 ms)
- coverage: 97.3% (PASS)
- true backlog: 2.667% (PASS)
- drops/errors/hydration-budget/reservation-superset gates: PASS

The Flow60 economic hypothesis was therefore **not evaluated** and remains frozen.

## Dominant measured clocks

The failed run showed two capacity problems:

1. Pump prepare tail capacity
   - arrival rate ~= 1918 / 120 = 15.98 notifications/s
   - Pump prepare service p95 = 918.8 ms
   - 12 workers imply p95 service capacity ~= 13.06 notifications/s
   - therefore the prior 12-worker profile is tail-underprovisioned for the observed load.

2. PumpSwap global reservation head-of-line
   - 108 prepared PumpSwap items were waiting for ingress-ordered reservation at deadline
   - normalization-to-reservation p95 = 6319.8 ms
   - ingress-to-reservation p95 = 8881.1 ms
   - SQLite writer queue/result p95 stayed comparatively small
   - the dominant clock is an early unresolved pool-identity sequence hole, not writer throughput or detector compute.

## v49 changes

v49 changes **systems scheduling only**:

### A. Pump prepare capacity

Pump prepare workers increase from 12 to 20.

This is measured capacity sizing, not trial-and-error tuning. At the failed-run p95 service time, 20 workers imply approximately 21.77 notifications/s of p95 service capacity versus ~15.98 notifications/s observed arrival.

### B. PumpSwap ingress identity prefetch

For PumpSwap trade pools that do not have a same-notification CreatePool event, immutable pool identity resolution is started as soon as the log notification enters the stream.

The prefetch:

- uses the exact same resolver instance;
- keeps the same per-pool single-flight lock;
- keeps the same hydration budget;
- keeps the same RPC hedging and timeout behavior;
- does not create detector observations;
- does not persist market trades;
- does not create reservations;
- does not mutate episode state;
- does not alter strict reservation/FIFO ordering;
- does not retry or backfill missing data.

The authoritative normalization/persistence path still performs its normal resolve call. Prefetch only gives that call a chance to reuse work already started/completed for the same pool.

## Systems-only validation

Run:

`python route_research_systems_stability_v49.py --run-key <fresh-systems-run-key>`

The runner uses the same v44 provider pacing and v43 120-second acquisition shape, but it intentionally blocks the forward SELL collector after the systems gate. Any route-research decisions/outcome schedules created under this diagnostic run key are excluded from v48 holdout evidence.

PASS requires the unchanged v43 same-run systems gate to report **11/11**.

PASS classification:

`PASS_V49_SYSTEMS_STABILITY_PROFILE`

FAIL classification:

`FAIL_V49_SYSTEMS_STABILITY_PROFILE`

A v49 PASS is only evidence that the amended systems scheduling profile is stable enough for another fresh v48 acquisition. It is not economic evidence and does not validate Flow60.

## Frozen economic hypothesis remains unchanged

v49 MUST NOT change:

- feature: `flow60_event_count`
- bins: LOW <=25 / MID 26..47 / HIGH >47
- primary horizon: 900s
- primary contrast: LOW vs HIGH
- v48 support/economic PASS criteria
- market detector thresholds
- route-only notional/slippage/horizons

Only after a v49 systems PASS may the acquisition implementation be amended to use the validated systems scheduling profile for a new fresh v48 run key.
