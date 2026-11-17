# Participant Quality Tail-Risk Rejection V0 — Preregistration (DRAFT) — 2026-09-28

Status: **DRAFT — not armed, no acquisition started, requires operator sign-off before any fresh run key is opened.**

## Mode

PAPER / RESEARCH / READ ONLY. No signing, no funded execution, no live money.

## Origin (consumed data, motivating only)

`docs/native-participant-quality-holdout-v1-result-2026-09-24.md` closed the exact-selector
candidate `KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`. That result is CLOSED and is
**not** reopened, retuned, or validated by this document. This preregistration only reuses the
descriptive shape of the consumed H1/H2 sample to motivate a **different question**, per that
result's own interpretation section:

> "A future, separately preregistered hypothesis may study Participant Quality specifically as a
> tail-risk / rejection dimension rather than an entry-alpha selector."

Consumed aggregate (H1+H2, for motivation only, not evidence for this hypothesis):

- HIGH catastrophic-loss rate (900s return <= -80%): 15.38%
- LOW catastrophic-loss rate: 70.59%
- HIGH profit factor: 0.443728, LOW profit factor: 0.465290 (both < 1; PF did not separate)

The prior selector asked "does HIGH beat LOW on profit factor" (an alpha question) and failed. This
draft asks a different, narrower question: "does the LOW group carry a materially worse
catastrophic-loss rate than the unconditional population, independent of whether HIGH generates
positive alpha." That is a risk-filter question, not a directional-edge question, and requires its
own fresh evidence.

## What this is not

- not a rescue of `KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`;
- not a cutoff retune, direction flip, or horizon substitution of that selector;
- not authorization to integrate anything into a live entry score;
- not a claim that HIGH has positive edge.

## Reused infrastructure (no new code required to acquire data)

- `participant_quality_native_memory_v1.py` — builds the outcome-blind wallet-quality memory
  (already proven live: produced the M1-M4 coverage audit and outcome-blind cutoff used by the
  closed H1/H2 result).
- `participant_quality_native_holdout_v1.py` — runs the acquisition cohort and already computes
  `catastrophic_loss_rate_pct` and `profit_factor` per group natively; no new metric code needed.
- Both already ran live successfully (H1: 40 episodes, H2: 40 episodes, bridge/forward-900
  lateness p95 = 1s). This is the only hypothesis in the migration package whose acquisition
  pipeline has a proven live track record as of 2026-09-28.

## Frozen feature and grouping

Same feature as the closed selector, unchanged:

`native_participant_prior_900_route_quote_return_median_of_wallet_medians_pct`

Same outcome-blind cutoff methodology (recomputed fresh from the new sample's own M1-M4 memory
build — never reused from the consumed H1/H2 cutoff). HIGH / LOW grouping by that fresh cutoff.

## Frozen primary hypothesis

> Among episodes admitted by the unchanged market-opportunity radar, the LOW participant-quality
> group has a catastrophic-loss rate (900s route-only return <= -80%) materially higher than the
> full (HIGH+LOW) population's catastrophic-loss rate.

This is a rejection-filter claim: if true, skipping LOW-flagged episodes is a defensible fail-closed
gate regardless of whether HIGH itself has positive alpha.

## Primary horizon and contrast

- primary horizon: 900 seconds (unchanged, matches existing route-only infra)
- primary contrast: LOW vs ALL (not LOW vs HIGH — this is deliberately different from the closed
  selector's contrast, because the question is "how bad is LOW alone" not "is HIGH better than LOW")
- minimum support: LOW >= 15 paired outcomes, ALL >= 40 paired outcomes (higher than the closed
  selector's minimums, since a rejection-filter claim about a subgroup needs its own adequately
  powered subgroup, not just enough for a two-group comparison)

## Primary PASS gate

PASS requires **all**:

1. LOW catastrophic-loss rate > ALL catastrophic-loss rate (LOW is worse than the population it's
   drawn from — internally consistent, not circular, because ALL includes LOW);
2. LOW catastrophic-loss rate exceeds ALL catastrophic-loss rate by >= 15 percentage points
   (materiality bar — a filter that saves 2pp of tail risk isn't worth the added missed-opportunity
   cost; 15pp is conservative relative to the 55pp gap observed in the consumed, non-evidentiary
   H1/H2 sample);
3. excluding LOW does not make the remaining (HIGH-only) population's median return worse than the
   ALL population's median return (the filter must not be actively harmful to the group it keeps).

Classifications: `PASS_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0`,
`FAIL_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0`,
`INCONCLUSIVE_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0_SUPPORT`.

## Failure discipline

Same as every other frozen protocol in this repo:

- no cutoff retune on this sample if it fails or is inconclusive;
- no materiality-bar lowering after seeing the result;
- no switching the contrast back to LOW-vs-HIGH after the fact;
- the run key/sample is burned once acquired, PASS or not;
- a PASS here authorizes a **fail-closed skip gate only** — never a live entry score, never funded
  execution, never a claim of positive alpha for HIGH.

## What PASS would prove / not prove

PASS would provide prospective evidence that a cheap, already-built wallet-quality check can act as
a downside-risk filter in a memecoin route-only context. It would **not** prove: alpha for the kept
group, executable slippage/fee-adjusted P&L, landing/fill probability, or live-money edge. Those
remain later, separately gated questions — same posture as every other result in this repo.

## Acquisition plan (not started)

Two fresh independent run keys (e.g. `participant-quality-tail-risk-v0-20260928-01-{H1,H2}`), each
through: memory build (`participant_quality_native_memory_v1.py`) -> holdout acquisition
(`participant_quality_native_holdout_v1.py`) -> this document's evaluator (to be added, small,
computing the 3 gates above from the holdout report's existing per-group stats — no new acquisition
code, only a small new evaluator reading fields the holdout script already emits).

**Requires operator sign-off on this document before any run key opens**, since acquisition burns
the sample the same way every other frozen protocol in this repo does.
