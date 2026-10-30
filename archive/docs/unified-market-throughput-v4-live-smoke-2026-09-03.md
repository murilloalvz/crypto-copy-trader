# Unified Market Throughput v4 — Live Smoke (2026-09-03)

Mode: PAPER / RESEARCH / READ ONLY.

Run: `unified-market-smoke-20260903-04`
Duration: 120s

## Result

**THROUGHPUT/COVERAGE PASS, LATENCY FAIL.**

The v4 architecture fixed the v3 capacity/backlog problem but did not satisfy the pre-frozen early-opportunity latency gate.

## Observed metrics

- received: Pump 1,432; PumpSwap 1,517; total 2,949
- enqueued: all received; dropped 0
- persistence completed: Pump 1,432; PumpSwap 1,515
- radar processed: Pump 1,432; PumpSwap 1,492
- total radar coverage: 99.2%
- worker errors: 0
- deadline overrun: 0.0s
- remaining backlog: Pump 0; PumpSwap 25 total (2 inflight + 23 reorder), about 0.85% of enqueued
- reference-asset episodes: 0
- unique episodes: 52 (Pump 16, PumpSwap 36)
- bundles remained populated: 918 fast-window events and 649 participant wallets total
- PumpSwap network hydrations: 74; successes 72; RPC failures 0; budget skips 0

Latency:

- Pump persist queue wait p50 12.1s / p95 38.0s / max 38.8s
- Pump radar end-to-end p50 12.5s / p95 38.3s / max 39.0s
- PumpSwap persist queue wait p50 0.18s / p95 1.14s / max 2.02s
- PumpSwap radar end-to-end p50 2.44s / p95 7.81s / max 9.57s

## Gate comparison

PASS:
- no traceback / worker errors
- zero dropped notifications
- reference_asset_episodes == 0
- both venues persisted observations
- radar coverage >=95%
- backlog <=5%
- budget_skips == 0
- episode bundles not systematically empty

FAIL:
- Pump radar p95 <=5s (observed 38.3s)
- PumpSwap radar p95 <=5s (observed 7.8s)

## Interpretation

The system can now absorb almost the entire 120s market stream by the deadline, but many observations are evaluated too late for a causal early-opportunity system. This is not an economic failure and must not trigger radar retuning.

Hot-path inspection found repeated market observation schema DDL checks on every persistence/read path. v5 therefore keeps the same detector and causal ordering while caching schema readiness per SQLite path. The cache is thread-safe and remains isolated across temporary/test database paths.

Jupiter/risk remain blocked until a short live latency smoke satisfies the existing <=5s p95 radar criterion for both venues.
