# Route Research v41 — live structural result — 2026-09-06

Run: `unified-market-route-research-smoke-20260906-41`

Mode: PAPER / RESEARCH / READ ONLY.

## Result split

### Route-research plumbing

PASS.

- selected: 12
- hazard AVAILABLE: 12/12
- entry eligible: 12
- entry terminal coverage among eligible: 100%
- selected terminal disposition coverage: 100%
- entry AVAILABLE: 10
- entry PROVIDER_ERROR: 2
- research decisions frozen: 10
- research outcomes scheduled: 30
- hazard wait timeout: 0
- reused entry attempts: 0
- research worker errors: 0
- route-only executable violations: 0
- research decision clock violations: 0
- official decision mutation violations: 0
- research schedule violations: 0
- classification: `PASS_ROUTE_ONLY_RESEARCH_DECISION_PLUMBING`

This confirms the v40 12->11 issue was accounting, not a lost eligible Jupiter entry. Historical v40 classification remains unchanged.

### v40 persisted structural diagnostic

The v40 upstream exclusion was explicit:

- episode `54EZa3pJgphmpump`
- hazard `PROVIDER_ERROR`
- exact persisted error: Solana RPC HTTP 429 Too Many Requests
- Jupiter entry correctly NOT_ATTEMPTED

The repeated v40 forward failure was also provider-side and persistent for one episode:

- episode `4sj7cSWQZyunpump`
- +300s: Jupiter `/order` HTTP 400 `Failed to get quotes`
- +900s: same provider error
- +3600s: same provider error

Interpretation: persistent route/provider unavailability for that token-sized route, not three collector plumbing failures.

## Systems latency

v41 materially improved the v40 burst but did not pass the frozen 5s PumpSwap gate.

- received: Pump 1712 + PumpSwap 6161 = 7873
- processed: Pump 1711 + PumpSwap 6034 = 7745
- coverage: 98.4% — PASS
- true backlog: 128/7873 = 1.626% — PASS
- Pump p95: 3.338s — PASS
- PumpSwap pipeline p95: 6.387s — FAIL
- drops: 0
- worker errors: 0
- reference asset episodes: 0
- hydration budget skips: 0
- reservation superset violations: 0

The v41 parallel hydration transport worked:

- network hydrations: 179
- successful batches: 171
- batch workers: 8
- inflight high water: 8
- endpoint requests: 342
- all hedges failed: 0
- parallel batch p95 service: 564.6ms

Compared with v40 PumpSwap p95 ~36.4s, v41 reduced the tail to ~6.39s, proving the serialized hydration transport was a major bottleneck.

## Residual dominant clock

The remaining tail is now concentrated after hydration in hot-asset stateful ordering/finalization:

- normalization -> reservation p95: 3.025s
- prepared -> submit p95: 1.866s
- reservation -> submit p95: 2.075s
- finalize causal dependency p95: 315ms, max 5.908s
- finalize ready queue p95: 1.141s, max 6.209s
- finalize start E2E p95: 6.387s
- hot assets show dependency p95 around 4–5.5s
- demotion wait p95: 5.306s
- demoted finalizer acks pending at deadline: 10

Writer service remained comparatively bounded:

- PumpSwap writer batch service p95: 120.6ms
- SQLite causal admission p95: 157.5ms

Therefore the next change must target the residual proof-based continuation/FIFO timing rather than increase workers or hydration budget.

## v42 candidate

v42 evaluates the same v27/v34 continuation proof earlier: on each new scheduler submit, already-pending followers are rechecked and only those now provably continuation-only are demoted. Ready/running/ambiguous/late-earlier work remains untouched and strict per-asset FIFO remains intact.

Files:

- `src/pumpswap_eager_demoting_scheduler_v42.py`
- `unified_market_route_research_smoke_v42.py`
- `tests/test_pumpswap_eager_demoting_scheduler_v42.py`

CI after test correction: compile + full unit suite PASS.

v42 is CODE/CI READY only. It needs a fresh 120s live structural smoke before any promotion.
