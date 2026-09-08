# v55 Candidate Selection -> Future Holdout Bridge Protocol

Date: 2026-09-07

Mode: **PAPER / RESEARCH / READ ONLY**

Registration timing: this protocol is committed while the fresh v55 live A/B acquisition is still in progress and before its feature-effect output has been reviewed.

## Purpose

Remove post-hoc discretion from the transition between v55 discovery and the next prospective validation.

v55 may produce zero, one, or multiple 900-second descriptive candidates. This protocol defines in advance how at most one candidate may be selected for a later pre-registered holdout.

Discovery selection is not validation.

## Candidate eligibility

A feature is eligible only if all inherited v55 conditions hold at the primary discovery horizon of 900 seconds:

1. v55 causal dataset audit passes;
2. feature coverage is >=80% independently in A and B;
3. LOW/HIGH split support satisfies the inherited minimum in A and B;
4. `effect_for_feature_v47` classifies the feature as `SAME_DIRECTION_DESCRIPTIVE_ONLY`;
5. A, B and ALL median deltas are non-zero and have the same sign.

No 300s or 3600s result can make a feature eligible if it is not eligible at 900s.

No feature outside the frozen v55 feature set may be added after seeing results.

## Numeric grouping

v55 numeric grouping remains value-only and label-free.

For a numeric feature with at least three distinct values, the discovery grouping is:

- LOW: `value <= discovery low_cut`
- MID: `low_cut < value <= discovery high_cut`
- HIGH: `value > discovery high_cut`

The LOW/HIGH cutpoints are produced only from feature values in the v55 discovery sample, not from returns.

If a feature is selected, those exact cutpoints become candidate hypothesis parameters and must be frozen in a separate result/preregistration commit before any future validation run begins.

MID remains diagnostic unless a future protocol registered before validation states otherwise. MID cannot rescue a failed LOW/HIGH primary contrast.

## Favorable direction

For v55 numeric features the effect is defined as:

`median(HIGH) - median(LOW)`

Therefore:

- positive same-direction delta -> HIGH is the discovery-favorable extreme;
- negative same-direction delta -> LOW is the discovery-favorable extreme.

That favorable direction must be frozen before new holdout data exist and cannot be reversed after seeing validation results.

## Pre-registered ranking when multiple candidates exist

Eligible features are ranked by the following deterministic order:

1. **weakest-subcohort separation**, descending:
   `min(abs(delta_median_A), abs(delta_median_B))`
2. **split-balance ratio**, descending:
   `min(abs(A), abs(B)) / max(abs(A), abs(B))`
3. absolute aggregate median separation, descending:
   `abs(delta_median_ALL)`
4. minimum A/B feature coverage, descending;
5. feature name, lexicographically ascending, as a deterministic final tie-break.

Only rank #1 may be carried forward.

Rationale: the first criterion favors a signal that remains separated in its weaker subcohort instead of one whose aggregate magnitude is dominated by a single favorable split. The second criterion further penalizes severe A/B imbalance. This is still discovery and remains exposed to winner's curse/multiple comparisons; a fresh holdout is required.

## If no candidate is eligible

Classification:

`NO_V55_CANDIDATE_FOR_PROSPECTIVE_HOLDOUT`

Do not loosen coverage, support, horizon, direction or feature-set rules to manufacture a candidate.

The correct next step would be a new research question/dataset, not retuning v55.

## If one candidate is selected

Classification:

`SELECTED_V55_DISCOVERY_HYPOTHESIS_FOR_PREREGISTRATION_ONLY`

Before collecting any new validation data, a separate immutable holdout protocol/result-registration commit must record:

- selected feature name and semantic definition;
- discovery LOW/MID/HIGH cutpoints;
- favorable extreme (LOW or HIGH);
- primary horizon 900s;
- primary contrast FAVORABLE vs OPPOSITE EXTREME;
- acquisition profile;
- sample support requirements;
- economic PASS gate below.

## Frozen future economic PASS template

Unless a blocker discovered before the holdout makes the experiment impossible and is documented before data collection, the next validation should retain the same conservative economic standard used for v48, generalized to the selected favorable group.

Primary support:
- FAVORABLE >=5 AVAILABLE at 900s in A;
- OPPOSITE >=5 AVAILABLE at 900s in A;
- FAVORABLE >=5 AVAILABLE at 900s in B;
- OPPOSITE >=5 AVAILABLE at 900s in B.

Primary PASS requires ALL:

1. FAVORABLE median > OPPOSITE median in A;
2. same in B;
3. same in ALL;
4. FAVORABLE median >0 in A and B;
5. FAVORABLE PF >1 in A and B;
6. aggregate FAVORABLE PF >1;
7. aggregate FAVORABLE mean_without_best >0.

300s/3600s and MID are diagnostic only and cannot rescue the 900s primary gate.

Classifications should preserve three outcomes:

- prospective PASS;
- prospective FAIL;
- INCONCLUSIVE for inadequate pre-registered support/observability.

A FAIL cannot be rescued by reversing direction, moving cutpoints, switching horizon, promoting MID, or choosing rank #2 from v55.

## Multiple-comparison interpretation

v55 examines a closed set of multiple features, so the rank #1 candidate is expected to be upward-biased by discovery selection.

The project does not claim statistical/economic edge from its discovery effect size. The independent prospective holdout is the protection against that selection bias.

Do not quote the v55 discovery delta as the expected live return.

## Forbidden

- choosing a candidate by aggregate delta alone when the pre-registered ranking disagrees;
- selecting a semantically preferred feature after seeing returns;
- combining rank #1 with rank #2;
- changing tertile cutpoints using labels;
- choosing 300s/3600s because 900s is weaker;
- reusing v55 A/B as validation;
- carrying multiple v55 candidates into parallel holdouts from the same decision point;
- reversing favorable direction after new data arrive;
- retuning a failed future holdout;
- live-money execution.
