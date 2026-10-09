# Unified Market Latency v8 — Nonblocking PumpSwap Ready Scheduler

Mode: PAPER / RESEARCH / READ ONLY.

## Why v8 exists

v7 preserved FIFO per opportunity asset, but radar workers dequeued work before waiting for the corresponding asset ticket. A future ticket could therefore occupy a worker while unrelated ready work remained queued. Under the v7 live burst this produced 1,091 pending PumpSwap radar jobs and p95 end-to-end latency of 65.05s.

## v8 architecture

```text
PumpSwap websocket
-> bounded concurrent identity resolution / persistence
-> ingress-order dispatcher
-> per-asset FIFO reservation
-> dependency waiter (does not consume execution slot)
-> ready queue
-> bounded radar workers
```

Only causally-ready reservations enter the execution pool. Waiting for an earlier ticket consumes no radar worker slot.

## Additional semantics

A PumpSwap notification whose canonical persistence result contains no newly-persisted trade and no newly-persisted lifecycle event is a no-new-evidence replay. v8 acknowledges it as processed without recomputing radar because the observable market state did not change. Duplicate/replayed trade counts are reported explicitly.

## Telemetry

- `pumpswap_radar_end_to_end_wait_ms`: ingress to start of radar execution.
- `pumpswap_radar_service_time_ms`: actual radar evaluation + episode handling cost.
- `ready_backlog`: causally-ready jobs waiting for execution capacity.
- `waiting_backlog`: jobs waiting for predecessor tickets.
- `no_new_evidence_skips`: canonical no-op replays intentionally not recomputed.
- `duplicate_or_replayed_trades`: persisted duplicate/replay workload.

## Frozen v8 live config

- 120s
- confirmed
- Pump ordered microbatch: size 32, max dwell 25ms
- PumpSwap persistence workers 24
- PumpSwap radar workers 4
- max concurrent resolutions 18
- max hydrations 1500
- queue size 5000

## PASS gate

1. no traceback / worker errors;
2. zero drops;
3. zero reference-asset episodes;
4. radar coverage >=95%;
5. total deadline backlog <=5% of received;
6. Pump radar p95 <=5s;
7. PumpSwap radar p95 <=5s;
8. budget skips 0;
9. admitted bundles not systematically empty;
10. replay conflicts remain auditable and show no unexplained referential corruption.

If v8 fails, do not increase workers automatically. Use service-time and ready/waiting backlog telemetry to identify whether the next bottleneck is radar/SQLite cost or unavoidable hot-asset causal serialization.
