# Rejection Filter Prospective Holdout V0 — Preregistration (FINAL DRAFT, pending owner freeze) — 2026-09-29

Mode: PAPER / RESEARCH / PROSPECTIVE / NO LIVE MONEY

**STATUS: FINAL DRAFT — NOT YET FROZEN. This document authorizes no acquisition, no provider call
and no run.** Design decisions are closed (4 cohorts; impact-only rule; Participant Quality excluded).
It becomes frozen only when the project owner commits it unchanged (section 15) before the first
fresh run key exists. Once frozen, nothing below may move.

## 1. Why this hypothesis exists (lineage, stated honestly)

- V55 discovery rows are burned. A descriptive study on them
  (`research/study_v55_rejection_lens_v0.py`, 62 rows with 900s returns, 22 features, Bonferroni)
  found **no feature** separating catastrophic route-only outcomes. That study generated no
  candidate and supports nothing here.
- The only data-derived motivation is the Native Participant Quality V1 result: the frozen selector
  is `KILL`, but HIGH vs LOW showed a large difference in catastrophic-loss rate (15.4% vs 70.6%).
  That result said any follow-up must be a *separately preregistered tail-risk / rejection*
  hypothesis with new independent evidence. This draft is that vehicle. It does not reopen or
  reinterpret the closed selector.
- The primary rule below uses one structural, non-outcome-derived condition (route price impact at a
  fixed notional), not a threshold searched on outcomes.

Frozen statuses this draft leaves untouched: V48 FAIL/CLOSED; V55 COMPLETE/CLEAN and burned for
V68 validation; V68 NOT_EVALUATED; Participant Quality `KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`.

## 2. Hypothesis (one primary, directional)

Among episodes the frozen radar/Signal Plane already selects, an outcome-blind **pre-entry
rejection rule** classifies a REJECTED group whose 900-second route-only catastrophic-loss rate
(<= -80%) is materially higher than the KEPT group's.

The claim is **tail-risk avoidance only**. It is not a profit claim. KEPT may still have
profit factor < 1; that does not affect the verdict, and no profit or edge claim may be made from
it (invariant: route-only return != realized P&L).

## 3. Frozen rule (proposed values)

For each episode, at `research_decision_as_of`, using only the causal entry BUY route quote:

- `impact_ok`: `abs(provider_price_impact_pct_points) <= 2.0`. The 2pp cap is the route-quality
  maximum already frozen elsewhere in the repo (absolute-value semantics; finite signed values are
  valid). At a fixed USD 25 route-only notional, price impact is an outcome-independent structural
  proxy for pool depth relative to trade size.

Classification:

- REJECTED: `abs(impact) > 2.0`.
- KEPT: impact known and `abs(impact) <= 2.0`.
- UNCLASSIFIED: impact missing/non-finite. Never zero-filled, never imputed, never counted as KEPT
  or REJECTED; reported with its own counts.

Hard exclusions (preconditions, not tested rules): mint or freeze authority present, per the
existing hazard evidence. In V55 these flags had zero variation, so they cannot be a tested rule.

Dropped from the earlier draft: a `liquidity_usd >= L` condition. Precondition P0 showed no
persisted route quote carries `liquidity_usd` (0 of 4,532 rows), so it cannot be classified. It may
return only in a future protocol that first proves a causal liquidity source.

Explicitly out of this protocol: Participant Quality (its frozen selector is KILL; adding it
would need an amendment before freeze and could never rescue a failed primary),
`flow60_buy_share_pct`, and any feature that showed nothing in the V55 study.

## 4. Preconditions before freezing (offline, outcome-blind)

- P0 (RESULT: FAILED for liquidity). `python -m research.check_entry_liquidity_coverage_v0` on the
  owner's database: `liquidity_usd` present in 0 rows for every source, buy and sell. Liquidity rule
  removed (section 3).
- P1 (RESULT: PASS for the main source). Price impact present in BUY quotes: metis 2,099/2,129
  (98.6%), okx 97/97, dflow 201/236 (85.2%), jupiterz 5/5. Coverage gate stays >= 80%.
- P1b (RESULT: PASS, outcome-blind, all persisted BUY route quotes, not a single cohort): share with
  `abs(impact) <= 2pp` is metis 1,167/2,099 (55.6%), dflow 87/201 (43.3%), okx 21/97 (21.6%),
  jupiterz 5/5; pooled 1,280/2,402 (53.3%). The dominant source and the pool sit inside the 30-85%
  non-triviality band. okx (n=97) is outside it but is a small share of quotes. These are estimates
  of the KEPT share, not guarantees for a fresh cohort; gate 4 still applies at analysis time.
- P2: V7 Signal Plane -> Research Plane -> route-research bridge is the accepted path; systems gates
  (11/11, 5s thresholds) stay untouched.

## 5. Fresh acquisition

Fresh untouched cohorts only; V55, V68, Participant Quality memory/H1/H2 rows are never reused.

- Cohorts: exactly four, `F1`..`F4` (decided). Sizing check: 40 episodes
  per cohort at ~78% AVAILABLE-at-900s (V55: 62/79) and ~98% impact coverage gives ~30 paired
  outcomes per cohort, i.e. ~92 for 3 cohorts, barely above the 90 gate (INCONCLUSIVE risk) and ~123
  for 4.
- Run keys: `rejection-filter-v0-<YYYYMMDD>-01-F1|F2|F3|F4`.
- Per cohort: 120s acquisition, max 40 selected episodes, min 30 route-research decisions;
  route-only BUY notional USD 25; slippage 100 bps; hazard pacing 650 ms; entry pacing 1000 ms.
- Exact 300/900/3600 schedule accounting; existing 300/900 forward collector must complete.
- A technical/acquisition failure gives INCONCLUSIVE and authorizes no threshold change.

## 6. Primary label

`100 * (900s SELL route quote price / causal entry BUY route quote price - 1)`, only AVAILABLE
non-executable quotes with valid causal clocks. Provider errors, missing quotes, invalid clocks and
invalid prices stay unavailable and remain in coverage accounting; they are never converted to zero
or to loss. Catastrophic loss: label <= -80% (frozen project convention).

## 7. Support gates (before any KEEP/KILL)

1. Rule input coverage (price impact known) >= 80% in every cohort.
2. Aggregate paired classified+900s outcomes >= 90 (expected ~123 with four cohorts).
3. REJECTED >= 15 and KEPT >= 15 paired outcomes aggregate; each >= 5 in every cohort.
4. Aggregate catastrophic outcomes >= 10.

Failure of any gate: `INCONCLUSIVE_REJECTION_FILTER_V0_SUPPORT`. No automatic extra cohort and no
fifth cohort added to reach support.

## 8. Effect gates (all must pass)

Let `cat(G)` be the catastrophic-loss rate of group G on paired 900s outcomes.

1. `cat(REJECTED) - cat(KEPT) >= 15 percentage points` (aggregate).
2. One-sided exact Fisher test, H1: `cat(REJECTED) > cat(KEPT)`, `p < 0.05`. Single primary test,
   so no multiplicity correction; everything else in section 10 is descriptive.
3. `cat(REJECTED) > cat(KEPT)` in each cohort separately.
4. Non-triviality: KEPT is between 30% and 85% of classified episodes (a rule that keeps almost
   nothing or almost everything is not a filter).

## 9. Power and error rates (simulated, exact Fisher + 15pp gate)

Approximate power with group sizes REJECTED/KEPT:

| True cat rates (REJ / KEPT) | 20 / 40 | 30 / 60 | 45 / 45 | **~58 / 65 (expected, 4 cohorts)** |
|---|---|---|---|---|
| 45% / 10% (PQ-sized) | 0.87 | 0.96 | 0.98 | **1.00** |
| 35% / 15% | 0.42 | 0.57 | 0.61 | **0.76** |
| 25% / 18% | 0.10 | 0.12 | 0.14 | **0.15** |
| 18% / 18% (no effect) | 0.02 | 0.02 | 0.03 | **0.02** |

Reading: a false KEEP under no effect is ~2-3%. With the expected four-cohort sample a PQ-sized
effect is detected essentially always and a moderate effect (35% vs 15%) about three times in four;
a small effect (25% vs 18%) is mostly invisible, so KILL/INCONCLUSIVE would not prove absence of a
small effect. Simulation assumes the expected group sizes and independence; real group sizes will differ.

## 10. Descriptive, non-gating reporting

- Per-cohort and aggregate: counts, coverage, UNCLASSIFIED share, catastrophic rates with exact CIs.
- Winner retention: how many episodes with 900s return >= +100% were REJECTED vs KEPT (a filter that
  removes the winners is not useful even if it passes the tail gate).
- Fixed-horizon route-only return distributions of KEPT vs REJECTED at 300/900/3600s (median,
  mean-without-best, profit factor, largest-winner share). No PF requirement.
- Any bankroll illustration uses only these fixed horizons, `simulate_bankroll`, labelled
  "route-only, descriptive, PAPER/RESEARCH/READ-ONLY - not realized P&L nor validated edge".

## 11. Exit policy is out of scope (deliberately)

TP/SL/trailing cannot be evaluated honestly from three checkpoints (touches between them are
invisible; a TP filled at its level is a "threshold-price fantasy fill", excluded by the market-first
exit contract). Testing exits requires a separate protocol that first collects the causal route path
(see `docs/market-first-exit-v58-geometry-protocol-2026-09-08.md`) and only after entry-side
research justifies it. Nothing here selects or arms an exit.

## 12. Verdicts

- All support + all effect gates PASS: `KEEP_REJECTION_FILTER_TAIL_RISK_CANDIDATE`. Authorizes only a
  separately preregistered independent replication. Not edge, not a TAKE/SKIP release, no funded BUY,
  no live money.
- Support PASS, any effect gate FAIL: `KILL_REJECTION_FILTER_TAIL_RISK_CANDIDATE` (closed; no retune).
- Technical or support insufficiency: `INCONCLUSIVE_REJECTION_FILTER_V0_...` with the exact reason.

## 13. Forbidden after fresh starts

- moving the 2pp cap, the -80% threshold, alpha or any gate; adding/removing rules;
- flipping direction, adding cohorts because results are inconvenient, subgroup or feature rescue;
- switching primary horizon to 300s or 3600s;
- reusing burned/consumed rows for validation;
- missing = zero/KEPT, provider error = loss;
- describing KEEP as edge, or using it in live entry score, shadow or funded execution;
- picking the best exit/rule from descriptive tables and calling it validated.

## 14. Human workflow note

The rule is a proxy for what a human SKIP would look like. The real human TAKE/SKIP workflow is a
roadmap item that does not yet exist; this protocol does not implement or validate it.

## 15. Decisions and freeze procedure

Closed: (1) four cohorts F1..F4; (2) primary rule is `abs(impact) <= 2.0pp` only, liquidity removed
(P0 failed); (3) Participant Quality is NOT part of this protocol (default; adding it would require
an amendment before freeze); (4) P1 coverage and P1b KEPT-share (pooled 53.3%) checks passed.

To freeze, the project owner:

1. reviews this file and removes the "FINAL DRAFT" wording, changing nothing else;
2. commits it on its own commit, with the commit hash recorded in the run notes;
3. only after that commit exists, creates the first run key `rejection-filter-v0-...-F1`.

Any edit after step 2 voids the preregistration for the affected runs. This draft is not a
release of acquisition, funded BUY, shadow execution or live money.
