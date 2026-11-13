# Unified Market Latency v6 — live result and v7 design

Date: 2026-09-03
Mode: PAPER / RESEARCH / READ ONLY

## v6 live run

Run key: `unified-market-smoke-20260903-06`
Duration: 120s
Configuration:
- Pump ordered microbatch writer
- Pump batch size 32
- Pump batch max wait 25ms
- PumpSwap persistence workers 24
- PumpSwap concurrent resolutions 18
- max hydrations 1500
- queue size 5000

## Frozen gate result

Observed:
- received: PumpSwap 2,181 / Pump 1,349 / total 3,530
- dropped: 0
- worker errors: 0
- persistence completed: PumpSwap 2,181 / Pump 1,349
- radar processed: PumpSwap 2,181 / Pump 1,348
- radar coverage: 100.0%
- deadline backlog: 1 Pump reorder item / total ~0.03%
- reference asset episodes: 0
- budget skips: 0
- admitted bundles: 84, populated

Latency:
- Pump persist queue p95: 1.909s
- Pump radar e2e p95: 2.802s
- PumpSwap persist queue p95: 0.583s
- PumpSwap radar e2e p95: 7.952s

Pump microbatch telemetry:
- 163 batches
- average batch size 8.28
- max batch size 32

Replay telemetry:
- Pump replay conflicts: 0
- shared market replay conflicts: 1 (`trade:retain_earlier_observation`)
- market trigger replay conflicts: 0
- PumpSwap pool mapping conflicts: 0

## Classification

`INTEGRITY PASS / COVERAGE PASS / PUMP LATENCY PASS / PUMPSWAP LATENCY FAIL`

The v6 Pump change solved the Pump latency gate without changing detector or causal clocks. The remaining failure is isolated to PumpSwap radar scheduling.

The PumpSwap persistence path is not the observed bottleneck in this run: p95 persistence wait was only 0.583s while radar e2e wait was 7.952s. RPC was also healthy (71/71 hydrations, zero RPC failures, zero budget skips).

## Replay conflict note

The single shared market conflict is not an automatic gate failure under the frozen policy because the conflict was audited and the earlier observation was retained. However, it must be inspected before any long acquisition. `market_replay_conflict_report.py` was added to print the exact event key, clocks and stored/incoming identities from the local run database.

## v7 hypothesis

The v6 PumpSwap coordinator globally serializes every notification after concurrent persistence. This creates cross-asset head-of-line blocking: an expensive radar evaluation for token A can delay token B even when the two assets are causally independent.

v7 removes that unnecessary serialization while preserving causal order for shared opportunity assets.

## v7 architecture

```text
PumpSwap websocket
-> bounded concurrent pool resolution / normalized persistence
-> completion queue
-> LIGHTWEIGHT global ingress-order dispatcher
-> per-opportunity-asset ticket reservation
-> N concurrent radar workers
```

The global dispatcher does not run the radar. It only releases persisted notifications in original websocket sequence and issues monotonically increasing tickets for each canonical affected opportunity token.

A radar worker may evaluate a notification only when every affected token's earlier ticket has completed. Therefore:
- same token: FIFO is preserved;
- overlapping multi-token notifications: partial order is preserved;
- disjoint tokens: can run concurrently;
- no later notification can overtake an earlier notification for the same opportunity asset.

Canonical affected assets are loaded from the already-persisted transaction view after normalized persistence. Incoming identities rejected by replay canonicalization cannot accidentally influence scheduling.

## v7 frozen operational parameters

Before live validation:
- Pump microbatch size: 32
- Pump microbatch max wait: 25ms
- Pump writer count: 1
- PumpSwap persistence workers: 24
- PumpSwap radar workers: 4
- max concurrent PumpSwap resolutions: 18
- max hydrations: 1500
- queue size: 5000
- duration: 120s
- commitment: confirmed

Four radar workers were chosen deliberately instead of mirroring the 24 persistence workers. The expected input rate in v6 was ~18 PumpSwap notifications/s; four workers provide substantial radar headroom while limiting concurrent SQLite read/write pressure from trigger/episode evaluation.

## v7 gate

Same scientific gate as v6. PASS only if all are true:
1. no traceback / worker errors;
2. zero dropped notifications;
3. `reference_asset_episodes == 0`;
4. both venues persist observations;
5. total radar coverage >=95%;
6. total deadline backlog <=5% received;
7. Pump radar e2e p95 <=5s;
8. PumpSwap radar e2e p95 <=5s;
9. budget skips == 0;
10. admitted bundles are not systematically empty.

Replay conflicts remain audit telemetry rather than automatic failure, but every non-zero conflict must be inspected before long acquisition.

No detector thresholds, decision rules, Jupiter provider, hazard provider, outcome logic, or economic scoring are changed by v7.
