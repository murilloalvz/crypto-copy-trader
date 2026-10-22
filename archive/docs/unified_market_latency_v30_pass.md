# Unified Market Latency v30 — Formal PASS

Date: 2026-09-04
Mode: PAPER / RESEARCH / READ ONLY
Run key: `unified-market-smoke-20260904-30`

## Result

The frozen Unified Market Latency gate passed in v30.

### Load and completion

- elapsed: 120.2s
- received: Pump 3,627 + PumpSwap 7,739 = 11,366
- persistence completed: Pump 3,617 + PumpSwap 7,724
- radar processed: Pump 3,600 + PumpSwap 7,687 = 11,287
- radar coverage: 99.3%
- true deadline backlog: (11,366 - 11,287) / 11,366 = 79 / 11,366 = 0.695%
- drops: 0
- worker errors: 0

### Frozen latency gates

- Pump radar p95: 3.1338s <= 5s — PASS
- PumpSwap pipeline p95: 2.0522s <= 5s — PASS
- coverage: 99.3% >= 95% — PASS
- true backlog: 0.695% <= 5% — PASS

### Safety / integrity gates

- reference_asset_episodes: 0 — PASS
- hydration budget skips: 0 — PASS
- reservation_superset_violations: 0 — PASS
- unresolved PumpSwap trades: 0
- bundles were not systematically empty: wallets total 3,059; flow30 total 4,229
- replay remained auditable; optimistic persistence collision paths were exercised without worker failure

## v30 profile

- Pump microbatch: 32 / 25ms
- Pump prepare workers: 12
- PumpSwap orchestration workers: 256
- PumpSwap prepare submitters: 64
- PumpSwap prepare executor workers: 32
- PumpSwap writer: one thread-owned SQLite microbatch writer, batch 32 / 10ms
- default blocking-I/O executor workers: 32
- max concurrent expensive pool resolutions: 18
- max hydrations: 1,500
- queue size: 5,000
- SQLite WAL + IMMEDIATE writer admission

The larger orchestration counts do not imply unbounded RPC or SQLite concurrency. RPC hydration remains bounded at 18 and SQLite remains single-writer.

## Key latency measurements

Pump:
- persistence queue p95: 0.7296s
- radar end-to-end p95: 3.1338s
- prepare p95: 0.5108s

PumpSwap:
- persistence queue p95: 0.2323s
- persistence service p95: 0.8035s
- normalization -> reservation p95: 1.0349s
- ingress -> reservation p95: 1.2268s
- prepare queue p95: 0.5187s
- prepare service p95: 0.6121s
- prepare E2E p95: 1.6741s
- prepared -> submit p95: 0.2457s
- causal dependency p95: 0.0s
- ready queue p95: 0.0s
- finalize-start E2E p95: 2.0362s
- pipeline E2E p95: 2.0522s

Writer:
- PumpSwap writer queue p95: 0.4448s
- writer result p95: 0.5273s
- batch service p95: 0.1308s

## v29 persistence fast-path evidence retained in v30

Pump:
- trade insert attempts: 3,233
- trade collision reads: 4 (0.124%)

PumpSwap:
- prepared items: 7,738
- trade insert attempts: 8,477
- trade collision reads: 7 (0.083%)
- affected-token batch readbacks: 680
- repeated-key readbacks: 2
- readbacks per prepared item: 0.0881

This confirms the insert-first / collision-read slow path removed thousands of unnecessary SELECTs while preserving replay semantics.

## Formal gate decision

All 11 frozen Unified Market Latency conditions are satisfied.

**UNIFIED MARKET LATENCY GATE = PASS**

This is a systems latency / observability PASS only. It is not evidence of economic edge or profitability.

## Next frozen stage

Proceed in the previously frozen order:

1. Jupiter executable quote only for newly admitted episodes.
2. Minimal hazard/risk provider with explicit missing/failure semantics.
3. Historical wallet outcomes resolved before T0 where applicable.
4. Freeze final `decision_as_of` after required provider attempts.
5. Executable forward outcomes at +5m / +15m / +60m.
6. Short true economic E2E smoke.
7. Provider coverage/reconnect/dedup/clock/cost audit.
8. Hydration/rate/backpressure policy.
9. Freeze runnable economic protocol.
10. First 12h collection only after those gates.
