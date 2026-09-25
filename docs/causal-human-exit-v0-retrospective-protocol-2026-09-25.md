# Causal Human Exit V0 — Retrospective Diagnostic Protocol — 2026-09-25

Mode: HUMAN-ASSISTED EDGE RESEARCH / RETROSPECTIVE DIAGNOSTIC / NO LIVE MONEY

## Purpose

Evaluate whether an exit policy that a human could have executed from causal route-path observations
would have captured existing real-market opportunities better than the standardized Fixed +60s
benchmark.

This is an evaluation layer, not a new entry-selector research line.

Post-Transition Pullback / Reacceleration V0 remains the active Market-First line.

## Scientific status

The policy is frozen before running the historical comparison.

Historical results from this diagnostic:

- may motivate a future prospective exit hypothesis;
- may inform Market Path / Signal Packet design;
- may not confirm Signal Edge, Human-Assisted Edge or Autonomous Edge;
- may not be used to retune the same historical sample.

## Inputs

Existing real-market route-shadow artifacts only:

- frozen route-result-v2.json;
- existing market-paths-smart-ladder-25-v0.json;
- frozen route-paper contract.

No new market acquisition is required.

## Observation semantics

The policy reacts only at route marks that were actually observed in the stored path.

No interpolation.

No continuous first-touch claim.

MFE is descriptive and is never treated as an achievable exit unless the exit rule actually fires at
an observed route mark.

## Frozen exit policy

Priority order:

1. GOOD_PROFIT
2. STRONG_DECELERATION
3. RISK_BREAK

### GOOD_PROFIT

Full exit at the first observed net route return >= +25%.

### STRONG_DECELERATION

Full exit only when all are true:

- prior observed peak >= +12%;
- current return is at least 10 percentage points below that observed peak;
- current mark deteriorated by at least 5 percentage points from the immediately previous observed
  mark;
- current mark is below the previous mark.

This is a price-path deceleration proxy for the historical artifacts.

It does not claim to measure flow deceleration.

Future Post-Transition data should additionally carry causal flow/participation state.

### RISK_BREAK

Full exit when:

- at least two valid route observations exist;
- current net route return <= -20%;
- current return is below the previous observed return.

### No forced time exit

If none of the rules fires, status is:

`CENSORED_OPEN_AT_LAST_OBSERVATION`

The last route mark is reported for context but is not treated as a realized simulated exit.

## Market Path metrics

For every paired path:

- observed MFE;
- observed MAE;
- time to observed MFE;
- time to observed MAE;
- last observed return;
- valid route-observation count;
- peak giveback at a causal exit.

## Comparison

Fixed +60 remains the standardized benchmark.

The report separates:

- Fixed +60 for all paired path entries;
- exit-trigger coverage;
- triggered-subset Fixed +60;
- triggered-subset Causal Human Exit V0;
- mean human-minus-fixed difference;
- share of triggered trades where the causal exit beat Fixed +60;
- censoring count;
- exit reason counts.

Censored trades are never silently converted into realized dynamic-exit PnL.

## Historical batch rule

The exact same frozen policy is applied unchanged to every historical capture.

No per-run tuning.

No threshold changes after observing one capture.

## Product interpretation

This V0 tests only one narrow question:

> When an already-detected opportunity evolves on an observed route path, could a simple causal
> human-like exit have closed at a realistically observable state better than Fixed +60?

It does not yet test the richer future state requested for Post-Transition:

- flow deceleration;
- unique-buyer slowdown;
- sell-flow acceleration;
- concentration deterioration;
- routeability change through time.

Those belong in the prospective Post-Transition Market Path collector.
