# Analysis Capability Inventory V0

Status: research architecture inventory. This document does not define a trading rule or score.

## Separation of research tracks

The project keeps two independent evidence tracks:

1. **Market-First** — protocol state, market activity, microstructure, execution surface and structural token/holder risk.
2. **Social/Event-First** — social/event evidence developed independently.

Cross-track convergence is a separate hypothesis and must not be assumed or used to retune either track after outcomes are observed.

## What already exists internally

### Market microstructure

`src/opportunity_snapshot_core.py`

Current causal windows expose:

- event count, buy count and sell count;
- unique buy/sell wallets when wallet identity is covered;
- wallet identity coverage;
- repeated-wallet event share;
- notional coverage and signed notional flow;
- notional imbalance;
- price coverage and observed return;
- explicit data-quality flags;
- execution quotes, liquidity, provider price impact, quote age and router identity.

### Activity dynamics

`src/market_activity_dynamics_v0.py`

Existing research primitives include:

- observed event/buy/sell rates over 0-10s, 10-30s, 30-60s and 60-300s intervals;
- adjacent rate ratios for acceleration/deceleration;
- notional-rate dynamics where coverage permits;
- participant context without incorrectly subtracting unique wallets across overlapping cumulative windows.

### Protocol lifecycle and reserves

`src/market_protocol_facts.py`

Existing causal facts include:

- Pump bonding-curve activity;
- Pump curve completion state;
- virtual/real reserves and total supply when observed;
- PumpSwap pool reserves and effective quote reserves;
- explicit canonical Pump -> PumpSwap migration evidence;
- lifecycle labels that do not infer migration from PumpSwap activity alone;
- provenance and missingness.

### Unified Market-First baseline

`src/market_intelligence_baseline.py`

This already composes protocol facts, flow windows, execution context and matched-unit liquidity-normalized flow into one immutable, score-free research surface.

## New capability: structural token/holder risk

`src/token_structural_risk_v0.py`

Purpose: normalize structural risk evidence from external or chain-derived providers without adopting a provider's opaque score as truth.

Normalized evidence currently supports:

- holder count;
- top-10 holder concentration;
- largest-holder concentration;
- dev, insider, sniper and bundler concentration claims;
- mint-authority and freeze-authority state;
- provider honeypot claim;
- liquidity burned/locked percentages;
- creator wallet;
- provider/source provenance and local observation time.

Rules:

- only evidence with `observed_at <= as_of` is visible;
- only the latest causal observation per provider is used;
- numeric disagreement is represented as a source range, not silently averaged;
- boolean claims require unanimous known-provider agreement for a consensus value;
- conflicts become explicit data-quality flags;
- no risk score, TAKE/SKIP recommendation or economic claim is produced.

## Why provider adapters are preferred over rebuilding everything now

Current third-party APIs already expose useful raw or semi-processed primitives that can be normalized into our evidence model:

### Birdeye

Relevant documented capabilities include:

- token security: `GET /defi/token_security`;
- holder distribution: `GET /holder/v1/distribution`;
- holder profile/positions with `bundler`, `sniper`, `insider`, and `dev` tags;
- first buyers and holder history in newer token APIs.

References:

- https://docs.birdeye.so/reference/get-defi-token_security
- https://docs.birdeye.so/changelog/20260417-release-token-holder-profile-positions-apis
- https://docs.birdeye.so/changelog/20260120-release-token-holder-distribution-on-solana

### Solana Tracker

Relevant documented capabilities include:

- top-20/top-100/full holder lists;
- holder concentration and holder history;
- token information with risk fields;
- filters/fields for top10, dev, insiders, snipers and bundlers;
- live holder updates.

References:

- https://docs.solanatracker.io/guides/token-holders
- https://docs.solanatracker.io/data-api/tokens/get-token-information
- https://docs.solanatracker.io/data-api/search/token-search

These sources are useful evidence providers, not ground truth. Their derived labels must retain source provenance.

## Highest-value gaps after this inventory

### A. Provider adapters for structural risk

Build thin adapters into `StructuralRiskObservationV0` for providers already available to the project. Do not place network calls in the Signal Plane hot path until measured.

### B. Holder-change dynamics

Research holder-count velocity and concentration change using causal historical snapshots. This should remain separate from price/flow outcomes until pre-registered.

### C. Creator/funding graph facts

The repo contains wallet/funding-link research primitives, but the Market-First token surface does not yet expose a normalized creator/funder graph at token T0. Candidate facts:

- creator wallet known/unknown;
- creator funding source;
- shared funder across launches;
- prior launches associated with creator/funder;
- causal provenance and confidence/missingness.

Do not convert these directly into a risk score before prospective validation.

### D. Supply-distribution quality

Top-10 concentration alone can be misleading because LP/program/system accounts may need classification or exclusion. Any concentration metric used economically should freeze its account-exclusion policy first.

### E. Direct Pump execution surface

The Launch Burst work showed that route-provider coverage and signal quality are different questions. A direct Pump bonding-curve quote/execution simulator remains useful for pre-graduation execution research.

### F. Human-facing evidence explanation

Before automated execution, the UI should explain a signal in factual blocks such as:

- market movement observed;
- participant structure observed;
- token/holder structural facts;
- execution/liquidity facts;
- missing evidence and conflicts;
- why the signal was emitted under a frozen rule.

This should be evidence-first and must not invent confidence from missing fields.

## Explicit non-goals

Do not yet:

- merge Market-First and Social/Event-First scores;
- assign weights to structural-risk fields based on intuition;
- call provider tags ground truth;
- use future outcomes to tune structural-risk thresholds;
- silently replace missing values with safe defaults;
- infer execution quality from market-signal quality.
