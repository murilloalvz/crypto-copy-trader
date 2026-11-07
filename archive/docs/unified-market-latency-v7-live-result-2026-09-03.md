# Unified Market Latency v7 — Live Result

Run: `unified-market-smoke-20260903-07`
Mode: PAPER / RESEARCH / READ ONLY.

## Result

- elapsed: 120.0s
- received: PumpSwap 3,297; Pump 2,742; total 6,039
- drops: 0
- persistence completed: PumpSwap 3,297; Pump 2,742
- radar processed: PumpSwap 2,206; Pump 2,742
- coverage: 81.9%
- worker errors: 0
- deadline backlog: PumpSwap radar/reorder 1,091; all ingress/inflight queues 0
- Pump persistence p95: 1.452s
- Pump radar end-to-end p95: 2.423s
- PumpSwap persistence p95: 2.258s
- PumpSwap radar end-to-end p95: 65.051s
- PumpSwap asset-order reservations: 3,297
- multi-asset notifications: 9
- max assets/notification: 2
- PumpSwap radar work backlog: 1,091
- hydrations: 93/93 success; RPC failures 0; budget skips 0
- replay telemetry: Pump 17 retain-earlier; market 4 retain-earlier trade; trigger 4 retain-first; pool mapping 0.

## Classification

**FAIL — PUMPSWAP RADAR SCHEDULER STARVATION / CAPACITY FAIL.**

The v7 per-asset FIFO idea is causally conservative, but the worker-pool implementation waits for an asset ticket *after* a worker has already dequeued the work item. A worker blocked on a future ticket consumes a scarce radar worker slot, while causally runnable work for unrelated assets remains queued. Under burst this can starve the worker pool.

Observed throughput confirms that four v7 radar workers did not improve aggregate PumpSwap radar throughput materially relative to the prior sequential path: 2,206 evaluations in 120s (~18.4/s), while ingress was 3,297 (~27.5/s).

This run does not invalidate per-asset ordering. It invalidates the blocking-worker implementation.

## v8 design requirement

- preserve ingress-issued per-asset FIFO tickets;
- waiting for predecessors must consume **zero radar execution slots**;
- only causally-ready work may acquire bounded radar concurrency;
- keep Pump ordered microbatch unchanged;
- keep detector thresholds/clocks/replay semantics unchanged;
- add radar service-time telemetry separately from end-to-end queue latency;
- do not increase concurrency blindly before validating scheduler behavior.

Replay conflicts are audit telemetry and must be inspected before any long acquisition; they are not interpreted as economic evidence.
