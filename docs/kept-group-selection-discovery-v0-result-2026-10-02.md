# KEPT-Group Selection Discovery V0 — Result — 2026-10-02

Mode: PAPER / RESEARCH / DESCRIPTIVE DISCOVERY / NO LIVE MONEY. **Hypothesis generation only; no verdict,
no rule, no edge claim.** Plan (written before the run): `docs/kept-group-selection-discovery-v0-plan-2026-10-02.md`.

## Result against the plan

- Sample: 108 KEPT episodes with an on-time 900s return (V1 54, V2 54), one per token. 22 features tested;
  Bonferroni over 22; minimum detectable |rho| at 80% power ~0.36.
- **Robust discovery candidates (Bonferroni p < 0.05 with matching signs): none.**
- KEPT baseline at 900s (pooled, deduplicated): median -0.36%, mean-without-best -9.8%, profit factor 0.72, 3
  winners >= +100%, 13 catastrophic outcomes. (V2 alone looked near break-even, PF 1.02; pooled it is below 1.
  The "near break-even" reading is not stable.)

## What the table does show (not significant at the preregistered level)

A coherent cluster of buy-side-dominance features is positively rank-correlated with the 900s return, with the
same sign in the V1 subset, the V2 subset and the 300s return:

| Feature | rho 900s | p (perm) | p (Bonferroni) | rho V1 | rho V2 | rho 300s |
|---|---|---|---|---|---|---|
| flow60_wallet_direction_balance | +0.28 | 0.003 | 0.075 | +0.27 | +0.28 | +0.15 |
| flow10_buy_share_pct | +0.27 | 0.005 | 0.114 | +0.38 | +0.14 | +0.13 |
| flow60_buy_share_pct | +0.26 | 0.006 | 0.141 | +0.30 | +0.23 | +0.08 |
| flow30_buy_share_pct | +0.26 | 0.008 | 0.166 | +0.30 | +0.20 | +0.12 |
| flow30_wallet_direction_balance | +0.25 | 0.010 | 0.216 | +0.21 | +0.26 | +0.14 |

The five features measure nearly the same thing, so the Bonferroni correction over 22 is conservative for them;
but picking the best of a cluster after seeing it is a forking path, and the observed ~0.27 is likely inflated
(95% CI for rho 0.27 at n=108 is roughly 0.09-0.44) and sits below the stated minimum detectable effect.
Everything else is indistinguishable from noise, including `abs_entry_price_impact_pp` (the filter's own
variable, rho -0.09). Liquidity-type features had 0% coverage and could not be tested.

## Caution: this points the opposite way from the V55 discovery

The V55 discovery (burned, 62 rows, never validated) favoured LOW `flow60_buy_share_pct`; here, conditional on
KEPT and on different cohorts, higher buy share goes with better 900s returns. This is not a rescue or a
refutation of anything frozen: V68 stays `NOT_EVALUATED` with its frozen contract, and no feature, bin, direction
or horizon of V68 may be changed on this basis. Any follow-up must be a new, separately preregistered
hypothesis, not described as a V68 variant. The contradiction mostly illustrates how fragile discovery-sample
findings are.

## Disposition

- Nothing here is confirmed. A candidate hypothesis, if pursued, needs fresh cohorts and a preregistered single
  feature, direction, cutoff (set outcome-blind) and gates that include the actionable comparisons (group profit
  factor and median), not only a rank correlation. Native Participant Quality died on exactly that profit-factor gate.
- Sample-size reality (single test, two-sided alpha 0.05, 80% power): rho 0.30 needs ~85 KEPT pairs, rho 0.25
  ~123, rho 0.20 ~194, rho 0.15 ~347. The V1/V2 yield was ~11-13 KEPT pairs per cohort, so n=150 means roughly
  12-14 more cohorts with the current design.
- Not authorized: TAKE/SKIP, funded BUY, shadow, live money, exit policy, any edge claim, any change to the frozen
  rejection rule. V48 FAIL/CLOSED; V55 burned for V68 validation; V68 NOT_EVALUATED; Participant Quality `KILL`:
  untouched.
