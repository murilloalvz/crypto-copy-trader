# Route Research v55 — Causal Early-Opportunity Discovery Protocol

Date: 2026-09-07
Mode: **PAPER / RESEARCH / READ ONLY**

## Purpose

v55 starts a new discovery cycle after the prospective rejection of the frozen v48 Flow60 hypothesis.

The question is:

> Among market episodes already detected by the frozen momentum radar, which simple features observable by `research_decision_as_of` are associated with better forward route-only outcomes, especially at 900s?

This is discovery, not validation. No v55 result may be called an edge, trading rule, executable strategy, or live-money gate.

## Why v55 exists

v48 established that raw `flow60_event_count` alone is not a robust prospective proxy for opportunity stage. The next step is not to retune Flow60. It is to examine a small, predeclared family of causal dynamics already available in the score-free snapshot:

- recent intensity;
- short-vs-long acceleration;
- buy/sell direction;
- buyer diversity;
- wallet repetition.

## Frozen acquisition path

v55 uses the existing v46 dual-subcohort acquisition semantics on the validated v54 systems profile.

Frozen:
- detector version and thresholds;
- two sequential fresh subcohorts A and B;
- cap 40 / minimum 30 research decisions each;
- hazard start interval 650ms;
- entry start interval 1000ms;
- exit start interval 250ms;
- route-only BUY US$25 / 100bps;
- horizons 300/900/3600;
- exact entry-output SELL amount;
- no signing/submission/fill;
- same systems/collector/lineage gates;
- Pump prepare workers 20;
- v54 demand-only resolver admission.

A fresh base run key is mandatory. Existing outcomes under either `-A` or `-B` fail closed.

## Closed feature set

The following feature list is frozen before fresh v55 acquisition.

### Intensity
- `flow10_event_count`

### Acceleration
- `flow10_vs_60_event_rate_ratio`
- `flow30_vs_300_event_rate_ratio`

Ratios compare event rates, not raw counts:
- `(flow10_count / 10) / (flow60_count / 60)`
- `(flow30_count / 30) / (flow300_count / 300)`

If the longer window has zero events, the ratio is explicit missingness, not zero and not backfilled.

### Direction
- `flow10_buy_share_pct`
- `flow60_buy_share_pct`

### Diversity
- `flow10_unique_buy_wallet_count`
- `flow30_unique_buy_wallet_count`
- `flow60_unique_buy_wallet_count`
- `flow30_wallet_direction_balance`
- `flow60_wallet_direction_balance`

Wallet direction balance is `unique_buy_wallet_count - unique_sell_wallet_count` for the same causal window.

### Repetition
- `flow30_repeated_wallet_event_share_pct`
- `flow60_repeated_wallet_event_share_pct`

Repetition remains missing when wallet identity coverage is insufficient under the existing snapshot semantics.

## Explicit exclusion of the failed v48 feature

`flow60_event_count` is NOT a v55 candidate feature.

It may remain visible in historical diagnostics, but v55 cannot recycle it as a newly discovered hypothesis because it has already failed a prospective holdout.

## Causal construction rule

Every v55 feature must be derived from the existing score-free opportunity snapshot reconstructed at `research_decision_as_of`.

Requirements:
- no future market observation;
- no outcome-derived feature;
- no later quote substituted for missing causal quote;
- no historical backfill presented as if available at T0;
- feature clock <= `research_decision_as_of` for every row.

The existing v47 dataset builder remains the lineage authority. v55 augments only rows that already pass v47 causal checks.

## Discovery grouping rule

Numeric groups are value-only tertile-style groupings inherited from v47.

Group cutoffs are determined from feature values only, never labels/returns.

Forbidden:
- grid-searching thresholds for return;
- logistic regression / random forest / XGBoost;
- arbitrary feature combinations;
- choosing a split because it maximizes P&L;
- removing losers;
- selecting only favorable subcohorts.

## Primary discovery horizon

900s is the primary discovery horizon for candidate review.

300s and 3600s remain diagnostics for interpretation and robustness only.

This is not a pass/fail economic horizon because v55 is discovery.

## Candidate eligibility

A feature can appear in the v55 900s hypothesis-candidate shortlist only when:
- A/B causal dataset audit passes;
- feature coverage is >=80% in A and >=80% in B;
- inherited v47 minimum group-support rules are met;
- the descriptive median-return contrast has the same direction in A and B.

Candidate status means only:
`HYPOTHESIS_CANDIDATE_FOR_SEPARATE_FUTURE_HOLDOUT_ONLY`

Magnitude may order the review list but does not validate the candidate.

## Dataset acceptance

v55 causal discovery dataset passes only if:
- A rows >=30;
- B rows >=30;
- zero lineage violations;
- zero missing decisions;
- zero missing episodes;
- zero missing hazard attempts;
- zero missing entry quotes;
- zero official decision mutations;
- zero v55 augmentation failures;
- zero feature-clock violations.

Classification:
`PASS_V55_CAUSAL_DISCOVERY_DATASET`

The final discovery runner classification is:
`READY_FOR_V55_DESCRIPTIVE_HYPOTHESIS_REVIEW`

This classification can occur even if no useful candidate exists. A scientifically clean negative discovery is valid.

## What happens after v55

Do not launch another holdout automatically.

After v55 completes:
1. review candidate coverage/support and A/B direction;
2. reject semantically weak or redundant candidates;
3. choose at most one simple hypothesis for the next holdout;
4. freeze its feature, comparison, cutoffs, horizon, support rule and pass criteria in a new protocol;
5. only then collect a new untouched prospective holdout.

The v55 A/B sample is discovery data forever and cannot serve as that holdout.
