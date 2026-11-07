# Route Research v47 — Offline Causal Feature Review Protocol

Date: 2026-09-06
Mode: READ ONLY / DESCRIPTIVE DISCOVERY

## Purpose

Use the completed v46 A/B route-only cohorts to discover descriptive feature/outcome relationships without changing the detector, strategy, provider semantics, or any historical evidence.

v47 is not a strategy optimizer and cannot establish profitability. A and B have already been observed, so neither is a virgin holdout for a new rule.

## Cohort

Input is one completed v46 base run. The CLI derives `<base>-A` and `<base>-B` and keeps the original run identities throughout the review.

Expected canonical input: `route-research-forward-cohort-20260906-46`.

## Strict causal cutoff

For every episode, the feature cutoff is the persisted `research_decision_as_of`.

A feature is eligible only if its real availability clock is `<= research_decision_as_of`.

- episode identity/direction/kind: first persisted trigger clock;
- flow and current-wallet aggregates: rebuilt with the existing dual-clock snapshot builder at the decision cutoff;
- hazard: persisted v37 attempt/evidence observed no later than the decision cutoff;
- entry surface: the exact persisted route-only BUY quote frozen into the decision, observed no later than the decision cutoff.

Any post-decision feature clock is a lineage violation. No later snapshot, candle, provider retry, backfill, or replacement is allowed.

Official `market_opportunity_episodes.decision_as_of` must remain NULL. v47 never mutates it.

## Feature families frozen before v47 output

Episode / clock:
- `episode_trigger_kind`
- `episode_trigger_direction`
- `decision_delay_seconds`

Flow:
- `flow30_event_count`
- `flow30_buy_share_pct`
- `flow30_wallet_identity_coverage_pct`
- `flow30_notional_imbalance_pct`
- `flow30_return_pct`
- `flow60_event_count`
- `flow300_event_count`

Current wallet participation:
- `wallet_participant_count`
- `wallet_repeated_event_share_pct`

On-chain hazard:
- `hazard_mint_authority_present`
- `hazard_freeze_authority_present`
- `hazard_token_2022`
- `hazard_extensions_count`

Route-only entry surface:
- `entry_price_impact_pct_points`
- `entry_liquidity_usd`

No legacy discovery score, leaderboard PnL, future wallet outcome, later provider state, or post-decision route outcome is an input feature.

## Labels

Labels remain the exact v46 route-only outcomes at:
- 300s
- 900s
- 3600s

Only `AVAILABLE` outcomes produce return labels. Explicit route/provider missingness stays missing and is never imputed.

## Numeric grouping

Numeric features use value-only descriptive bins. The cut points are derived only from the feature values, never from outcome labels.

- one unique value: no comparison;
- two unique values: LOW/HIGH exact-value split;
- three or more unique values: value-only LOW/MID/HIGH tercile-style bins.

These are descriptive bins, not trading thresholds.

## Split consistency

For a directional comparison to be marked `SAME_DIRECTION_DESCRIPTIVE_ONLY`:
- comparable groups must each have at least 5 AVAILABLE labels in subcohort A;
- the same groups must each have at least 5 AVAILABLE labels in subcohort B;
- median-return separation must point in the same non-zero direction in A, B, and aggregate.

Disagreement is `UNSTABLE_ACROSS_SUBCOHORTS`. Low support remains explicit.

No p-value or feature ranking in v47 is a release gate.

## Output and classification

v47 reports:
1. causal dataset/lineage audit;
2. baseline economics A/B/aggregate;
3. feature coverage;
4. per-horizon descriptive median-return separation across A/B/aggregate;
5. same-direction hypothesis candidates.

`READY_FOR_DESCRIPTIVE_HYPOTHESIS_REVIEW` means only that the persisted causal sample is usable for selecting a hypothesis to freeze for a future fresh test.

It does NOT mean:
- profitable edge;
- executable edge;
- landed/fill edge;
- approved filter;
- shadow/live release.

Any candidate selected after v47 must be documented and frozen before a new v48 out-of-sample cohort. The v46 A/B data cannot be reused as proof of that selected rule.
