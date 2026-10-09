# Route Research v47 Candidate Robustness Review Protocol — 2026-09-06

## Purpose

Deepen the already-observed v47 descriptive candidates before any v48 prospective holdout.

This step is **not** a new acquisition, model fit, threshold search, detector change, or trading rule. It reuses the exact v47 causal dataset, feature definitions, and value-only groupings and only adds heavy-tail robustness metrics for candidates already classified as `SAME_DIRECTION_DESCRIPTIVE_ONLY`.

Mode remains:

**PAPER / RESEARCH / READ ONLY**

## Frozen inputs

Base cohort:

`route-research-forward-cohort-20260906-46`

Subcohorts:

- `route-research-forward-cohort-20260906-46-A`
- `route-research-forward-cohort-20260906-46-B`

The v47 causal cutoff remains unchanged:

`feature_observed_at <= research_decision_as_of`

Numeric grouping boundaries are the original v47 value-only boundaries. Returns never participate in threshold construction.

## Candidate eligibility

Only v47 effects already classified as:

`SAME_DIRECTION_DESCRIPTIVE_ONLY`

are expanded in this review.

No new feature, interaction, threshold, horizon, notional, or subgroup may be introduced by this step.

## Metrics

For each candidate comparison, each horizon, and each of A, B, and aggregate, report both compared groups separately using:

- n;
- positive share;
- mean return;
- median return;
- profit factor;
- best return;
- worst return;
- mean without best;
- largest winner share of gross profit.

The purpose is to identify whether apparent separation is economically broad or dominated by one heavy-tail winner.

## Interpretation rules

A candidate remains only a **descriptive hypothesis candidate** when:

- causal audit remains clean;
- both A and B retain adequate support;
- the direction already observed in v47 remains interpretable when group-level economics are inspected;
- the result is not obviously explained by one winner or a tiny subset;
- missingness/support limitations are kept explicit.

Do not count duplicate or near-duplicate feature representations as independent evidence. For example, if two features induce effectively the same grouping in this cohort, treat them as one underlying descriptive phenomenon until fresh data separates them.

Do not create a mechanical outlier-concentration threshold from this sample. The robustness metrics are diagnostic, not a second optimization objective.

## Failure / rejection conditions

Reject or defer a candidate when any of the following is material:

- causal/lineage audit failure;
- low group support;
- A/B economic shape is inconsistent despite same-sign median delta;
- apparent advantage disappears when the best winner is removed;
- gross profit is dominated by one winner to a degree that makes the evidence clearly fragile;
- the feature is redundant with another representation and adds no independent information.

These are research judgments, not live strategy gates.

## Next gate

After this robustness review, either:

1. classify `NO_STABLE_DESCRIPTIVE_FEATURE_HYPOTHESIS` and improve observation / collect more frozen data; or
2. choose a small number of scientifically defensible hypotheses, freeze their exact definitions and existing v47 segmentation in a pre-registered v48 protocol, then collect **fresh** prospective data.

A/B from v46 can never become the validation holdout for a rule discovered from them.

## Command

```powershell
python route_research_feature_robustness_v47.py --base-run-key route-research-forward-cohort-20260906-46
```

Do not start v48 before reviewing the complete output of this command.
