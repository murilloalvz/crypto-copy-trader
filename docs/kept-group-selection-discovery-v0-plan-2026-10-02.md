# KEPT-Group Selection Discovery V0 — Analysis Plan (written before any run) — 2026-10-02

Mode: PAPER / RESEARCH / DESCRIPTIVE DISCOVERY / NO LIVE MONEY

**This is hypothesis generation, not validation.** It produces no verdict for any experiment and no trading rule.
The rows it reads are consumed: any hypothesis it suggests needs a separately preregistered confirmation on
fresh data. Recorded before the script is run so the choices below cannot be adapted to what it shows.

## Question

Among episodes the validated rejection filter keeps (`abs(entry price impact) <= 2pp` at a USD 25 route-only BUY),
do any persisted causal pre-entry features rank-separate better from worse 900s route-only returns?

## Data (fixed)

- V1 cohorts `rejection-filter-v1-20260929-01-G1..G4` and V2 cohorts `rejection-filter-v2-20260930-01-H1..H5`
  (all VALID). Both studies are consumed; V0 F1 stays unread.
- KEPT episodes only, hard-excluding mint/freeze authority present. Label: 900s route-only return, AVAILABLE and
  collected on time (<= 60s late). Missing, late, technical and no-route outcomes are never converted to values.
- Each token counts once across V1+V2 (first episode by `research_decision_as_of`; ties by `episode_key`).

## Features (fixed, no new engineering)

Every numeric or boolean causal feature already built by the V55 dataset (V47 features plus the 12 V55
transforms), plus `abs(entry_price_impact_pct_points)` (replaces the raw signed value). A feature is tested only
with >= 80% coverage among the paired KEPT rows and at least two distinct values. Categorical features are listed as
skipped. No interactions, bins, transforms or horizon switching.

## Statistic and multiplicity (fixed)

- Primary: Spearman rho between feature and 900s return (rank-based, robust to the rare large winners).
- Two-sided permutation p-value (20,000 permutations, seed 20261002), Bonferroni-adjusted over the number of
  features tested.
- All features are reported in alphabetical order. Nothing is selected, ranked or hidden by effect size.
- Reported alongside, never gating: rho in V1 rows, rho in V2 rows, rho against the 300s return, the minimum
  detectable |rho| at the Bonferroni level for the sample size, and the KEPT 900s baseline distribution.
- A feature is called a **robust discovery candidate** only if Bonferroni p < 0.05, the sign agrees between the V1
  and V2 subsets, and the sign agrees with the 300s rho. "Candidate" means "worth preregistering", nothing more.

## What can follow

- Candidates (if any) may feed ONE separately preregistered selection hypothesis with a frozen cutoff and direction,
  confirmed on fresh cohorts with the V2-style machinery. Nothing in this analysis may be used as that confirmation.
- No candidates is an acceptable and likely outcome: ~100 KEPT pairs with only a handful of large winners gives low
  power, and the report states the minimum detectable effect.

## Not authorized

TAKE/SKIP, funded BUY, shadow, live money, exit policy, any change to the frozen rejection rule, or any edge claim.
V48 FAIL/CLOSED; V55 burned for V68 validation; V68 NOT_EVALUATED; Participant Quality `KILL`: untouched.
