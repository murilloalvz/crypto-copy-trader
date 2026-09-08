# Route Research v55 — Causal Early-Opportunity Discovery Result — 2026-09-08

## Status

**COMPLETE / DISCOVERY-ONLY / ONE ELIGIBLE 900s CANDIDATE**

This document records the fresh v55 discovery run. It is not a prospective economic validation and does not authorize a trading rule, shadow execution, or live money.

## Fresh base

`route-research-early-opportunity-discovery-20260907-55`

Subcohorts:
- `...-A`
- `...-B`

## Causal validity

- rows total: 79
- A: 39
- B: 40
- lineage violations: 0
- missing decisions: 0
- missing episodes: 0
- missing hazard attempts: 0
- missing entry quotes: 0
- official decision mutations: 0
- augmentation failures: 0
- feature clock violations: 0
- classification: `PASS_V55_CAUSAL_DISCOVERY_DATASET`

Both v46 subcohorts passed the frozen acquisition gate. The validated v54 systems profile remained in use. No v55 feature changed during acquisition.

## Baseline route-only economics

### 900s

A:
- n=29
- positive share=58.621%
- mean=+1.355%
- median=+3.929%
- PF=1.054

B:
- n=33
- positive share=54.545%
- mean=+29.177%
- median=+1.460%
- PF=2.204

ALL:
- n=62
- positive share=56.452%
- mean=+16.164%
- median=+2.525%
- PF=1.655

Important robustness note: B's 900s mean is dominated by a +1157.888% winner; its `mean_without_best` was negative in the underlying v43/v46 descriptive report. Baseline profitability is therefore not interpreted as a validated detector edge.

## Frozen v55 feature coverage

All closed-set features except `flow10_buy_share_pct` reached 100% A/B coverage. `flow10_buy_share_pct` was only 51.3% in A and 57.5% in B and was ineligible under the pre-registered >=80% per-subcohort coverage requirement.

## Primary 900s discovery review

Exactly one feature satisfied both:
1. pre-registered coverage eligibility; and
2. same-direction descriptive HIGH-vs-LOW median contrast in A and B with inherited split support.

### Candidate

`flow60_buy_share_pct`

Family: `direction`

Value-only tertiles published by the frozen v55 runner:
- LOW <= 57.1429
- MID <= 65.7143
- HIGH > 65.7143

900s HIGH-minus-LOW median deltas:
- A: -10.660 percentage points, support `(LOW=10, HIGH=6)`
- B: -8.360 percentage points, support `(LOW=11, HIGH=10)`
- ALL: -8.639 percentage points

Classification:
`SAME_DIRECTION_DESCRIPTIVE_ONLY`

Candidate status:
`HYPOTHESIS_CANDIDATE_FOR_SEPARATE_FUTURE_HOLDOUT_ONLY`

## Pre-registered candidate selection outcome

The candidate-selection bridge was committed before v55 results were reviewed. Since only one eligible 900s candidate survived, the deterministic ranking has no discretionary tie or alternate feature to choose.

Selected rank #1:
- feature: `flow60_buy_share_pct`
- favorable discovery extreme: `LOW`
- opposite extreme: `HIGH`

Reason: v55 defines effect as `median(HIGH)-median(LOW)`. The effect was negative in A, B, and ALL; therefore the pre-registered bridge maps LOW to the favorable discovery group.

No rank #2 exists. No other v55 feature may be used to rescue a future failure of this candidate on the same validation sequence.

## Interpretation

The discovery result is consistent with a hypothesis that, **among market movements already detected by the frozen momentum radar**, a lower 60-second buy share may correspond to less one-sided/FOMO-dominated flow and better subsequent 900-second route-only outcomes than an extremely buy-dominated state.

This does **not** mean:
- sell pressure is bullish;
- low buy share is a trading rule;
- the detector is economically validated;
- the effect is causal;
- the effect is executable after fees/fills;
- 300s or 3600s can validate the hypothesis.

A fresh prospective holdout is required.

## Burned sample rule

The v55 A/B rows are discovery data and are permanently burned for validation of this hypothesis. They cannot be reused for:
- prospective PASS/FAIL;
- cutpoint retuning;
- feature combinations;
- choosing MID instead of LOW/HIGH;
- changing the primary horizon;
- selecting a replacement feature after failure.

## Next scientific action

Freeze one separate prospective holdout using:
- feature `flow60_buy_share_pct`
- LOW <= 57.1429
- MID <= 65.7143
- HIGH > 65.7143
- favorable=LOW
- opposite=HIGH
- primary horizon=900s
- minimum extreme support >=5 in A and B
- v48-style robust economic gate
- fresh untouched A+B acquisition only
