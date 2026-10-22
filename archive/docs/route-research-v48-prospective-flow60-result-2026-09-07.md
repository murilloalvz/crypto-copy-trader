# Route Research v48 — Prospective Flow60 Holdout Result

Date: 2026-09-07
Mode: **PAPER / RESEARCH / READ ONLY**

## Final classification

`FAIL_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS`

This is a valid prospective economic rejection, not a systems or collection failure.

## Validity gates

Base:
`route-research-prospective-holdout-20260907-48v54`

- A research decisions: 40
- B research decisions: 40
- rows total: 80
- lineage violations: 0
- missing decisions: 0
- missing episodes: 0
- missing hazard attempts: 0
- missing entry quotes: 0
- official decision mutations: 0
- v48 causal audit: PASS
- both v46 subcohorts passed their acquisition/forward gate
- systems gate passed in the final B run: 11/11

Therefore the Flow60 hypothesis was actually evaluated prospectively.

## Frozen primary test

Feature: `flow60_event_count`

Bins:
- LOW <=25
- MID 26..47
- HIGH >47

Primary horizon: 900s
Primary contrast: LOW vs HIGH

Primary support was adequate.

## 900s result

A:
- LOW n=9 median=-18.472% PF=0.561
- HIGH n=11 median=-36.705% PF=0.549

B:
- LOW n=10 median=-9.805% PF=0.027
- HIGH n=5 median=+6.962% PF=0.256

ALL:
- LOW n=19 median=-10.770% PF=0.303 mean_without_best=-32.040%
- HIGH n=16 median=-11.315% PF=0.486

Gate fields:
- support_ok=True
- same_direction_ok=False
- low_positive_median_both=False
- low_pf_gt_one_both=False
- aggregate_low_pf_gt_one=False
- aggregate_low_mean_without_best_positive=False

## Scientific interpretation

The discovery-era idea that lower `flow60_event_count` could proxy an earlier/less-saturated stage did not replicate as a robust prospective route-only economic segment.

Do not rescue this sample by:
- changing LOW/MID/HIGH cutoffs;
- promoting MID because one subcohort looked favorable;
- switching the primary horizon to 300s or 3600s;
- mining a replacement feature from the same holdout and presenting it as validation;
- reusing A or B as a future holdout.

The entire v48-v54 sample is now discovery/post-mortem evidence only.

## Baseline population reminder

Across the 80 detector-population rows at 900s:
- available=64
- positive share=42.19%
- mean=-12.53%
- median=-9.82%
- profit factor=0.633
- mean without best=-20.27%
- best=+475.17%

The next research problem is therefore selection: retain access to rare explosive moves while rejecting a large fraction of economically poor detector episodes.
