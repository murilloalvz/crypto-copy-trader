# Unified Market Latency Smoke v5 — Live Result — 2026-09-03

Mode: PAPER / RESEARCH / READ ONLY.

Run: `unified-market-smoke-20260903-05`
Duration: 120s
Configuration: Pump workers 4; PumpSwap workers 8; max concurrent PumpSwap resolutions 6; max hydrations 1000; queue size 5000.

## Result

**FAIL — latency/capacity under burst load.**

The v5 schema-readiness cache materially improved the Pump path relative to v4, but the run encountered a substantially heavier PumpSwap burst and the globally ingress-ordered PumpSwap coordinator developed severe head-of-line backlog. This run does not justify Jupiter integration or the 12h acquisition.

## Observed summary

- elapsed 120.1s; deadline overrun 0.1s;
- received: PumpSwap 3,606; Pump 1,339; total 4,945;
- dropped: 0;
- worker errors: 0;
- radar processed: PumpSwap 2,751; Pump 1,187;
- total radar coverage: **79.6%**;
- deadline backlog: Pump ingress 148, Pump reorder 4, PumpSwap ingress 458, PumpSwap inflight 2, PumpSwap reorder 395;
- persisted trades: PumpSwap 3,598; Pump 1,183;
- unique episodes/enrichments: 68/68;
- reference-asset episodes: 0;
- bundle totals: wallets 1,292; flow30 events 1,818;
- Pump radar end-to-end latency: p50 2.19s, p95 **8.52s**, max 24.04s;
- PumpSwap persistence queue latency: p50 48.11s, p95 55.80s, max 61.78s;
- PumpSwap radar end-to-end latency: p50 53.37s, p95 **71.15s**, max 74.69s;
- PumpSwap network hydrations: 350; successes 348; RPC failures 0; budget skips 0;
- single-flight waits: 155.

## Interpretation

1. Schema caching helped the Pump path: Pump p95 improved from 38.3s in v4 to 8.5s in v5 despite a different live load. This is operational evidence, not a controlled benchmark.
2. The run is not directly comparable to v4 as a pure A/B test because PumpSwap ingress rose from 1,517 notifications in v4 to 3,606 in v5.
3. PumpSwap failure is dominated by queueing/head-of-line pressure, not RPC errors or hydration-budget exhaustion: RPC failures and budget skips were both zero.
4. The current global ingress-order guarantee is scientifically safe but couples unrelated pools. Before weakening causal ordering, first test whether bounded worker/resolution capacity can absorb a burst of this magnitude while preserving the existing semantics.
5. No radar threshold, episode rule, economic feature, or outcome definition should be changed from this smoke.

## Next gate — v5b capacity stress

Keep the v5 code and causal ordering unchanged. Increase only operational concurrency for a short 120s stress smoke:

- Pump workers: 8;
- PumpSwap workers: 24;
- max concurrent PumpSwap resolutions: 18;
- max hydrations: 1500;
- queue size: 5000.

The same frozen engineering pass criteria remain:

- dropped = 0;
- worker errors = 0;
- reference-asset episodes = 0;
- radar coverage >=95%;
- total deadline backlog <=5% of received;
- Pump radar end-to-end p95 <=5s;
- PumpSwap radar end-to-end p95 <=5s;
- hydration budget skips = 0.

If v5b still fails under burst load, do not keep increasing concurrency blindly. The next architecture change must remove global cross-pool head-of-line blocking while explicitly preserving causal ordering at the opportunity-asset level.
