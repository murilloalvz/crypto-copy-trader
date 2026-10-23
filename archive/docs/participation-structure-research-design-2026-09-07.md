# Participation Structure Research — Boundary and Future Design

Date: 2026-09-07

Mode: **PAPER / RESEARCH / READ ONLY**

## Research question

Among already-detected market opportunities, can transaction-level participation structure help distinguish broadening demand from activity concentrated in a small/repeating set of wallets?

This is a research question about observable structure. It is **not** a claim that the system can currently detect wash trading, sybil behavior, insider coordination or manipulation.

## Why this layer exists

The accepted market-first detector intentionally reacts to market movement. A movement can be economically attractive, late/crowded, or mechanically amplified by concentrated/repeated activity.

Raw event count alone cannot separate those cases. The prospectively rejected Flow60 hypothesis is evidence that a single recent-activity count is not a robust stage proxy by itself.

A future selection engine therefore needs richer causal context, while preserving the distinction between:

- **what is observed**;
- **what is inferred**;
- **what has been validated prospectively**.

## Existing aggregate integrity layer

`src/market_integrity.py` already exposes aggregate observational fields such as:

- buy pressure;
- trade imbalance;
- volume acceleration;
- transactions per holder;
- provider-reported concentration/risk fields when available.

Its own detection limits correctly state that aggregate snapshots cannot identify self-trading, counterparty graphs, order-level sequences or funding relationships.

That module remains valid and should not be relabeled as a manipulation detector.

## New transaction-level participation evidence

The v55/v56-era market observation store can support additional descriptive structure when wallet identity coverage is adequate.

Potential evidence families include:

### Breadth
- unique participating wallets;
- unique buy wallets;
- unique sell wallets;
- short-window growth/rate of unique buyers.

### Repetition
- repeated-wallet event share;
- event count per unique wallet;
- persistence of the same wallet across short windows.

### Concentration
- top-1 wallet event share;
- top-3 wallet event share;
- concentration change across 10/30/60-second windows.

### Directional participation
- unique-buy versus unique-sell wallet balance;
- overlap between wallets buying and selling inside the same causal window.

### Activity acceleration
- short/long event-rate ratios;
- short/long unique-buyer-rate ratios.

These fields describe the shape of participation only.

## Semantic boundary

The following wording is allowed before validation:

- concentrated participation;
- repeated-wallet activity;
- broad/narrow participation;
- directional wallet imbalance;
- buy/sell wallet overlap;
- participation acceleration.

The following wording is forbidden without an independently validated study and stronger evidence:

- wash trading detected;
- sybil cluster detected;
- insider manipulation;
- fake organic demand;
- coordinated pump;
- malicious wallet cluster.

A high top-1 event share can arise from many benign or malicious mechanisms; the metric alone does not identify causation.

## Data-quality contract

Participation metrics that depend on wallet identity must not be presented as complete when wallet identity coverage is partial.

Preferred behavior:

- complete wallet identity -> compute structure fields;
- partial identity -> preserve coverage and leave pseudo-complete concentration/repetition fields missing;
- zero identity -> explicit unavailable.

Notional- or price-derived fields follow the same complete-coverage discipline where required.

## Future evidence needed for stronger coordination claims

A future coordination/manipulation study may require additional independently sourced evidence such as:

- wallet funding relationships known as-of;
- common funder clusters;
- transaction/account graph proximity;
- sub-second/order-level transaction ordering;
- round-trip/self-transfer patterns;
- creator/deployer relationships;
- known launch/sniper semantics;
- matched control tokens and prospective labels.

None of these may be synthesized from missing data or inferred from a single concentration ratio.

## Experimental sequencing

1. v55 completes unchanged.
2. Review v55 participation/dynamics features as discovery only.
3. If warranted, pre-register at most one simple economic hypothesis for a new holdout.
4. Independently build stronger coordination evidence if the data source and semantics can be defended.
5. Only after causal labels and controls exist should a manipulation-specific classifier or threshold be considered.

## Relationship to v56

`src/exceptional_trade_preentry_v56.py` already provides strict dual-clock pre-entry participation structure around an arbitrary wallet-entry reference. Those metrics are suitable for future exceptional-trade research because the target entry and same-second activity are excluded and later-observed backfill cannot leak backward.

v56 remains a scaffold; no exceptional-trade outcome definition is registered yet.

## Relationship to v57

Social evidence is independent. Author diversity or social acceleration must not be used to label on-chain participation as organic without separate validation.

## What this design proves

Nothing economic by itself. It establishes a terminology and causal boundary so later implementations do not overclaim what wallet-count/concentration statistics can prove.

## Forbidden

- adding a manipulation score now;
- choosing thresholds from v48/v55 outcome labels and presenting them as causal validation;
- computing concentration from only the observed subset while hiding identity missingness;
- equating repetition with wash trading;
- using post-entry/post-decision graph evidence as if known earlier;
- changing the frozen detector to suppress patterns before their economics are prospectively validated;
- concurrent live economic acquisition while v55 is running;
- live-money execution.
