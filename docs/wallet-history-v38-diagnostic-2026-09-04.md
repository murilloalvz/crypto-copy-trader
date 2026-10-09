# Market-First Wallet History Diagnostic v38 — 2026-09-04

Mode: **READ ONLY / PAPER / RESEARCH**

Run:

`unified-market-onchain-hazard-smoke-20260904-37`

Horizon inspected: `300s`

## Result

- episodes inspected: 12
- participant wallet observations: 194
- candidate prior official episodes: 0
- eligible labeled prior episodes: 0
- prior episodes matching current participants: 0
- historical associations: 0
- `no_prior_official_market_first_decisions`: 12/12
- `no_valid_market_first_history_sample`: 12/12

Classification:

`INCONCLUSIVE_NO_OFFICIAL_MARKET_FIRST_HISTORY_SAMPLE`

## Interpretation

This is the expected causal result and is not a strategy failure.

The diagnostic confirmed that the wallet-history layer did **not** promote legacy wallet-first PnL, discovery leaderboards, exploratory copyability labels, later outcomes or artificial backfill into the current market-first evidence bundle.

At this stage there are no prior episodes with official frozen `decision_as_of` plus causal executable forward outcomes. Therefore there is no valid historical wallet-opportunity sample to reuse.

The correct behavior is explicit no-sample.

An outcome observed in the same whole second as the current episode T0 remains excluded because ordering is ambiguous at second-level resolution.

## Promotion rule retained

A historical wallet-opportunity association may contribute only when the prior episode has official market-first lineage and its label was already observable strictly before current T0.

`no valid history sample` is preferred to contaminated history.
