# Wallet Forward v2 — Run 1 × Run 2 Final Decision

Date: 2026-09-03

Mode: **RESEARCH / READ ONLY**

This document closes the preregistered Wallet Forward v2 replication step. It does not promote shadow or live trading and it does not pool the two runs automatically.

## Runs

### Run 1

Run key: `wallet-forward-1788360461-8a3986f9`

- status: `COMPLETED`
- duration: 10h00m04s
- cohort: 3 frozen wallets
- enrollment: 4h
- follow-up: 6h
- polling: 10s
- commitment: confirmed
- Jupiter quote mode: proxy/read-only
- delays: 0/15/30/60/120s
- copy notional: US$25
- forward actions: 15
- BUY/SELL: 9/6
- enrolled BUYs: 4
- finality: 15/15 finalized, 15 success, 0 error
- causal boundary: clean

Quantity-aware replay with exact quote identity:

| Delay | Closed | Open | Censored | Mean net return | Median net return | Win rate | Profit factor |
|---|---:|---:|---:|---:|---:|---:|---:|
| +0s | 3 | 0 | 1 | -28.76% | -40.40% | 33.3% | 0.0060 |
| +15s | 3 | 0 | 1 | -30.37% | -45.76% | 33.3% | 0.0148 |
| +30s | 0 | 0 | 4 | n/a | n/a | n/a | n/a |
| +60s | 3 | 0 | 1 | -25.36% | -33.61% | 33.3% | 0.0376 |
| +120s | 0 | 0 | 4 | n/a | n/a | n/a | n/a |

These values are descriptive only. Three of four enrolled BUYs belong to the same wallet×token cluster, so they are not four independent economic opportunities.

### Run 2

Run key: `wallet-forward-1788400735-5cbe70af`

- status: `COMPLETED`
- duration: 10h00m07s
- cohort: same 3 frozen wallets
- enrollment: 4h
- follow-up: 6h
- polling: 10s
- commitment: confirmed
- Jupiter quote mode: proxy/read-only
- delays: 0/15/30/60/120s
- copy notional: US$25
- forward actions: 3
- BUY/SELL: 0/3
- enrolled BUYs: 0
- RPC sync/capture failures: 0
- bootstrap failures: 0
- RPC recoveries: 0
- finality: **3/3 finalized, 3 success, 0 error, 0 missing**

Run 2 therefore has **no economic sample**. It neither confirms nor refutes the Run 1 return observations.

## Technical comparability

The two runs use the same technical regime and frozen cohort. They remain separate experimental windows. Same-regime status does not authorize automatic pooling.

## Effective economic sample

Across the two preregistered 10h windows:

- nominal observation time: 20h
- total forward actions: 18
- total enrolled BUYs: 4
- Run 1 enrolled BUYs: 4
- Run 2 enrolled BUYs: 0
- 3/4 enrolled BUYs came from one wallet×token cluster

The effective independent sample is therefore substantially smaller than the raw BUY count suggests.

## J8PS long-horizon observation

The `7mP...` Run 1 BUY in token `J8PS...` was right-censored at the Run 1 endpoint because no source SELL occurred inside the preregistered window.

Run 2 later observed a complete source liquidation with the exact accumulated raw quantity, approximately 19h after the original BUY detection.

This later SELL is useful evidence that some source-wallet holding horizons exceed the 10h experiment window. It is **not** retroactively added to Run 1 P&L because it occurred outside Run 1's frozen endpoint.

## Audit fixes discovered during closeout

### Exact quote identity

The legacy economic replay CLI built `quote_key -> quote` by zipping caller key order with a loader result ordered by observation time. The two sequences are not contractually aligned.

The corrected path resolves each quote by exact key identity. The corrected Run 1 economics remain the values listed above, but the old ordering dependency is no longer acceptable for future audits.

### Cross-run SELL quote lineage

Run 2's quote watcher created SELL probes using successful BUY quotes from Run 1 for the same wallet/token. This did not change Run 2's frozen economic denominator, but it consumed quote capacity and made logs look as if the current run possessed an economic entry.

The corrected lineage rule is:

> a SELL event may only reuse successful BUY quote lineage whose source observation has the exact same `run_key`.

Legacy/unscoped observations do not receive guessed SELL lineage.

### Misleading event logging

The quote watcher previously printed every ingested event with a `[wallet buy]` prefix, including SELLs. The corrected log includes the persisted side explicitly.

## Preregistered decision classification

The post-Run2 framework defined Outcome D as the case where the sample is too small to support a profitability conclusion.

**Final classification: OUTCOME D — TOO LITTLE ECONOMIC SAMPLE.**

This means:

- do not claim wallet-only edge;
- do not claim wallet-only failure from the Run 1 descriptive returns;
- do not retune delays/cohort based on those returns;
- do not automatically launch Run 3;
- do not promote shadow or live;
- redesign acquisition only under a new preregistered protocol.

## Next methodological gate

Exactly one next gate is selected:

**Causal Opportunity Acquisition v1**

The purpose is to solve sample scarcity and collect richer causal context while treating wallet activity as one information channel rather than a guaranteed copy signal.

Passing the next gate will validate data acquisition quality only. It will not establish economic edge.
