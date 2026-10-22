# Burst Participation Structure Discovery v0 — Frozen Protocol — 2026-09-24

Mode: PAPER / RESEARCH / READ ONLY

## Purpose

Start a new Market-First discovery cycle after the frozen v68 Flow60 holdout failed.

The consumed v68 -03 A/B sample may be used only as retrospective discovery data for this new
question. It MUST NOT be reused as prospective validation, and this cycle MUST NOT be described as
a rescue of Flow60 or as validation of another v55 feature.

Research question:

> Among Burst episodes already detected by the frozen radar, do causal participant-structure
> features observable by research_decision_as_of separate catastrophic tail risk at 900 seconds?

## Closed feature family

This protocol intentionally excludes every v55 candidate feature, including wallet repetition.

The closed feature set is:

- flow30_top1_wallet_event_share_pct
- flow30_top3_wallet_event_share_pct
- flow60_top1_wallet_event_share_pct
- flow60_top3_wallet_event_share_pct
- flow30_buy_sell_wallet_overlap_share_pct
- flow60_buy_sell_wallet_overlap_share_pct

All are event-count / wallet-identity structure features reconstructed causally from persisted market
trades known by research_decision_as_of.

## Causal construction

For each episode:

- load only market trades with observed_at <= research_decision_as_of;
- derive chain_as_of exactly as the existing opportunity snapshot does:
  max(first_trigger_chain_time, causally visible trade chain_time);
- 30s and 60s windows use strict lower bound and inclusive chain_as_of upper bound;
- participant-structure features are missing unless wallet identity coverage is complete;
- no outcome, later quote, future trade, or label enters feature construction.

Definitions:

- top1 wallet event share = largest wallet event-count share in the window;
- top3 wallet event share = sum of the three largest wallet event-count shares;
- buy/sell overlap share = number of wallets appearing on both sides divided by total unique wallets.

These are descriptive structure metrics only. They are not manipulation, sybil, insider, wash-trading,
or organic-demand labels.

## Discovery sample

Only:

- v68-flow60-fresh-20260922-03-A
- v68-flow60-fresh-20260922-03-B

The sample is already burned for Flow60 validation and remains burned. Results from this new feature
family are discovery-only forever.

## Primary horizon

900 seconds.

300s and 3600s are not used to create candidate eligibility in this protocol.

## Grouping

For each numeric feature:

- LOW <= global lower-tercile cutpoint
- MID <= global upper-tercile cutpoint
- HIGH > global upper-tercile cutpoint

Cutpoints use feature values only, never outcomes.

## Catastrophic tail

Fixed before feature evaluation:

- catastrophic route-only return <= -80.0%

This threshold is a discovery endpoint for tail-risk separation, not an execution stop-loss.

## Candidate eligibility

A feature is a discovery candidate only when ALL hold:

1. coverage >=80% independently in A and B;
2. LOW and HIGH each have >=5 AVAILABLE 900s outcomes in A and B;
3. Spearman direction is non-zero and the same in A, B, and ALL;
4. the discovery-favorable extreme has higher median return than the opposite extreme in A and B;
5. the discovery-favorable extreme has a lower catastrophic-loss rate than the opposite extreme in A and B;
6. the discovery-favorable extreme has higher mean_without_best than the opposite extreme in A and B;
7. the discovery-favorable extreme has higher Profit Factor than the opposite extreme in A and B.

Favorable extreme is defined only by the sign of aggregate Spearman:

- positive -> HIGH
- negative -> LOW

No direction reversal is allowed after results are seen.

## Candidate selection if multiple survive

Rank deterministically by:

1. weakest-subcohort catastrophic-tail reduction, descending;
2. weakest-subcohort median separation, descending;
3. weakest-subcohort mean_without_best improvement, descending;
4. absolute aggregate Spearman, descending;
5. feature name ascending.

Only rank #1 may move to a separate future preregistration.

## Forbidden

- using flow30/flow60 repetition as a candidate in this cycle;
- using decision_delay_seconds as alpha;
- using Flow60 buy-share as a rescue;
- combining features after seeing results;
- threshold sweep;
- changing the -80% endpoint after seeing results;
- switching primary horizon;
- calling a discovery candidate edge;
- reusing v68 -03 as validation;
- live-money execution.

## Next action

If one candidate survives, freeze it in a separate prospective holdout protocol BEFORE collecting any
new data. If none survives, do not loosen this protocol; move to another research family.
