# Unified Market Enrichment Smoke v2 — 2026-09-03

Run: `unified-market-smoke-20260903-02`
Mode: PAPER / RESEARCH / READ ONLY
Requested duration: 120s

## Result

Classification: **CAUSAL BUNDLE PASS / THROUGHPUT FAIL**

The v2 smoke fixed the prior zero-flow bundle bug. Episode bundles now contain the causal fast-window flow and wallets that generated the trigger. However, the unified single-consumer architecture could not keep up with live Pump + PumpSwap ingress.

## Observed summary

- elapsed: 125.6s;
- received/produced notifications:
  - Pump: 1,054;
  - PumpSwap: 1,426;
  - total: 2,480;
- processed:
  - Pump: 252;
  - PumpSwap: 228;
  - total: 480;
- backlog at deadline:
  - Pump: 802;
  - PumpSwap: 1,198;
  - total: 2,000;
- queue high-water: 2,000 / 2,000;
- persisted trades:
  - Pump: 234;
  - PumpSwap: 255;
- affected tokens: 117;
- raw radar hits:
  - PumpSwap: 4;
  - Pump: 2;
- unique episodes: 2;
- opened by source: 1 PumpSwap / 1 Pump;
- enrichment admitted: 2;
- bundle wallet total: 23;
- bundle fast-30s flow total: 29;
- risk missing: 2, expected because hazard is not integrated;
- PumpSwap historical pool hits: 66;
- run-store hits: 1;
- cache hits: 91;
- network hydrations: 97;
- hydration successes: 97;
- real RPC failures: 0;
- budget skips: 0;
- negative-cache skips: 0.

## Important positive finding

The local causal enrichment boundary is now correct:

- PumpSwap episode: flow30=19, wallets=19;
- Pump episode: flow30=10, wallets=4.

Therefore `radar -> episode -> local flow/wallet bundle` is no longer systematically empty.

## Capacity failure

Only ~19.4% of received notifications reached radar processing before the acquisition deadline (480 / 2,480). The shared queue saturated completely.

This means Jupiter/risk I/O must not be added yet. Doing so would increase delay and worsen coverage.

## Asset-role incident

The PumpSwap episode surfaced `So11111111...` (WSOL) as the opportunity token. This exposed a semantic bug: the adapter treated `base_mint` as the opportunity asset unconditionally.

PumpSwap events are base-relative. Pools with WSOL as base and a non-reference token as quote require:

- opportunity token = quote token;
- Buy/Sell inversion for opportunity-token semantics.

This is fixed in the v3 normalized persistence path. Reference assets themselves are not valid opportunity episodes.

## Decision

- Do not retune radar thresholds.
- Do not add Jupiter yet.
- Do not start 12h.
- Implement source-separated queues, bounded concurrent PumpSwap persistence/resolution, single-flight pool hydration, ordered PumpSwap radar evaluation, and explicit asset-role normalization.
- Re-run a 120s throughput smoke under pre-frozen operational PASS criteria.
