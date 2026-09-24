# Participant Quality Native Memory v0 — Frozen Protocol — 2026-09-24

Mode: PAPER / RESEARCH / READ ONLY

## Purpose

Build native market-first memory for Participant Quality on the current Signal Plane / Research Plane
pipeline before any new economic holdout.

This phase does NOT test profitability. It exists only to answer:

> Can the current pipeline accumulate enough strictly pre-T0 participant history for a future
> Participant Quality hypothesis to be observable with useful support?

## Why this is a separate phase

The replicated historical Participant Quality result used mature Launch Burst history. When applied to
the V68 sample, current native market-first history coverage was too sparse. Missing history is
missing, not zero and not a loss.

The next action is therefore to improve causal memory, not to reinterpret the V68 economics.

## Frozen memory acquisition plan

Exactly four sequential memory cohorts are authorized:

- M1
- M2
- M3
- M4

Each cohort uses:

- current frozen Signal Plane / Research Plane route-decision path;
- acquisition duration 120 seconds;
- max episodes 40;
- minimum research decisions 30;
- route-only BUY notional US$25;
- slippage 100 bps;
- hazard start interval 650ms;
- entry start interval 1000ms;
- exit start interval 250ms.

Run count is frozen at four BEFORE acquisition. Do not add a fifth cohort because coverage or economics
look disappointing.

## Outcome maturity required for memory

For each memory cohort, the next cohort may not start until all scheduled 300s and 900s route-only
outcomes for that run are terminal.

3600s outcomes are not required for this memory phase and may remain pending.

The memory feature uses only the 900s horizon.

## Native Participant Quality feature

For a current episode:

1. reconstruct the current 30-second participant wallet set using the existing causal enrichment
   semantics at research_decision_as_of;
2. load only official market-first opportunity associations whose decision and 900s outcome were
   both known strictly before the current episode T0;
3. for each current participant wallet with eligible prior associations, compute that wallet's median
   prior 900s executable quote return;
4. take the median across those wallet medians.

Feature ID:

native_participant_prior_900_quote_return_median_of_wallet_medians_pct

Higher is the prior-informed favorable direction. This direction comes from the previously replicated
Participant Quality concept, but this native 900s variant is a new feature and is NOT yet economically
validated.

## Memory coverage audit

After M4 completes, compute feature availability for each M1-M4 episode using only information that was
strictly known at that episode T0.

No current/future outcome is used to compute feature availability or feature value.

Readiness requires BOTH:

- M4 feature availability >= 50% of its research decisions;
- aggregate feature-available episodes across M2+M3+M4 >= 30.

If readiness fails:

INCONCLUSIVE_NATIVE_PARTICIPANT_MEMORY_COVERAGE

Do not add more memory cohorts automatically.

If readiness passes:

READY_TO_PREREGISTER_NATIVE_PARTICIPANT_QUALITY_HOLDOUT

## Outcome-blind cutoff

Only if readiness passes, compute one supporting future threshold from feature VALUES ONLY:

- cutoff = median of all available native Participant Quality values from M2+M3+M4.

No returns, P&L, labels or economic outcomes may influence this cutoff.

Future direction is predeclared:

- HIGH: feature > cutoff
- LOW: feature <= cutoff
- favorable: HIGH

The cutoff is not a validated trading rule. It only becomes an immutable candidate parameter for a
separate future prospective holdout protocol.

## Forbidden

- inspecting memory-cohort economics to change run count;
- selecting a different history horizon after seeing values;
- treating missing history as zero or negative;
- using same/future episode outcomes as participant history;
- threshold sweep;
- changing favorable direction after seeing outcomes;
- using V68 as replacement validation;
- calling memory readiness edge;
- automatic live-money execution.

## Next step after readiness

If READY, write a separate immutable prospective holdout protocol with economic PASS/FAIL/INCONCLUSIVE
criteria BEFORE acquiring new validation cohorts.

If INCONCLUSIVE, stop this branch and move to another research family rather than extending the same
memory sequence post hoc.
