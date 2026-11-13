# Unified Market Latency v9 Live Result + v10 Diagnostic

Mode: **PAPER / RESEARCH / READ ONLY**.

Date: 2026-09-03.

## v9 live run

Run: `unified-market-smoke-20260903-09`

Duration: 120s

Configuration:
- commitment: confirmed
- Pump ordered microbatch: 32 / 25ms max dwell
- PumpSwap persistence workers: 24
- PumpSwap radar workers: 8
- max concurrent resolutions: 18
- max hydrations: 1500
- queue size: 5000

## Frozen gate result

PASS:
- drops: 0
- worker errors: 0
- reference-asset episodes: 0
- radar coverage: 97.3% (gate >=95%)
- total deadline backlog: 96 / 3504 = ~2.74% (gate <=5%)
- Pump radar p95: 1.798s (gate <=5s)
- hydration budget skips: 0
- RPC failures: 0
- admitted bundles populated: 62 episodes

FAIL:
- PumpSwap radar end-to-end p95: **18.311s** (gate <=5s)

Classification: **PUMP PASS / PUMPSWAP LATENCY TAIL FAIL**.

Jupiter, hazard/risk integration, final `decision_as_of`, executable forward outcomes and 12h remain blocked.

## v8 -> v9 improvement

v8:
- coverage 75.6%
- PumpSwap radar processed 2157 / 3553 received
- PumpSwap reorder backlog 1374
- PumpSwap radar end-to-end p95 54.973s
- PumpSwap radar service p95 0.790s
- 4 radar workers

v9:
- coverage 97.3%
- PumpSwap radar processed 1927 / 1979 received
- PumpSwap reorder backlog 51
- PumpSwap radar end-to-end p95 18.311s
- PumpSwap radar service p95 0.676s
- 8 radar workers

The v9 bounded capacity stress substantially removed the gross throughput deficit. Under this particular run, persisted PumpSwap throughput (~16.5/s) and radar-processed throughput (~16.1/s) were close enough for deadline backlog to remain below the frozen 5% gate.

The remaining failure is not explained by radar service cost alone: p95 service is ~0.676s while p95 time until radar service starts is ~18.3s.

## Replay telemetry

v9:
- `pump_replay_conflicts=1`, action `retain_earlier_observation`
- `market_replay_conflicts=2`, breakdown `trade:retain_earlier_observation`
- `market_trigger_replay_conflicts=0`
- `pumpswap_pool_mapping_conflicts=0`

These counters remain audit evidence. They are not zeroed or reclassified to make the latency gate pass.

## v10 decision

Do **not** increase PumpSwap radar workers again without diagnosis.

v10 is instrumentation-only and keeps:
- detector thresholds unchanged
- causal clocks unchanged
- per-asset FIFO unchanged
- persistence semantics unchanged
- replay semantics unchanged
- episode semantics unchanged
- provider policy unchanged
- PumpSwap radar workers at 8

The objective is to decompose the latency visible in v9 into:

1. ingress -> persistence worker queue wait
2. persistence service
3. persistence completion -> ingress-order reservation / dispatcher wait
4. reservation -> scheduler waiter task start
5. per-asset causal dependency wait
6. ready queue wait
7. radar service (kept comparable with v8/v9: evaluation + result handling/enrichment)
8. total pipeline end-to-end

Radar internals are also timed observationally:
- transaction-view read
- token history read
- detector compute
- episode assignment/write
- aggregate DB read time
- evaluation time before result handling
- post-evaluation result handling/enrichment time

## Hot-asset diagnostics

The scheduler records diagnostic-only per-asset telemetry:
- reservation count
- max outstanding ticket depth
- max simultaneous causal waiters
- active waiters at the deadline snapshot
- dependency wait count
- dependency wait total
- dependency wait p50/p95/max

The v10 summary reports:
- top assets by reservations
- top assets by accumulated causal wait
- number of assets accounting for 50% and 90% of causal waiting
- maximum simultaneous waiting jobs for one asset

Multi-asset notifications remain FIFO across all involved assets. Diagnostic attribution is observational and does not participate in scheduling.

## Interpretation after v10

If `pumpswap_scheduler_dispatch_wait_ms` dominates:
- investigate event-loop/scheduler task dispatch overhead before attributing the delay to causal serialization

If `pumpswap_causal_dependency_wait_ms` dominates the 18s tail and wait is concentrated in a few assets:
- classify as hot-asset causal serialization
- optimize only with a design that preserves causal semantics

If `pumpswap_ready_queue_wait_ms` dominates:
- investigate execution-pool scheduling/capacity before any concurrency change

If `pumpswap_persist_to_reservation_wait_ms` dominates:
- investigate ingress-order reorder/dispatcher head-of-line

If DB read timing becomes a large fraction of radar service or grows strongly under concurrency:
- investigate shared SQLite/read contention and schema/read-path overhead

If post-evaluation time dominates:
- investigate episode admission/enrichment cost independently from radar evaluation

If none explains the total:
- reconcile phase sums against `pumpswap_radar_end_to_end_wait_ms` before changing architecture.

## Frozen gate

Latency gate passes only if:
- coverage >=95%
- total deadline backlog <=5%
- Pump radar p95 <=5s
- PumpSwap radar p95 <=5s
- drops 0
- worker errors 0
- reference-asset episodes 0
- hydration healthy
- replay behavior explainable/auditable

Only after PASS:
`Jupiter executable quotes -> risk/hazard -> decision_as_of -> executable forward economic outcomes`.

The 12h collection remains later, after the true economic E2E path and provider/backpressure policy are validated.
