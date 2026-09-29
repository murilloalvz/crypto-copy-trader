# Participant Quality Tail-Risk Shadow Annotation V0 — Preregistration (DRAFT) — 2026-09-29

Status: **DRAFT — not armed, no code written, no annotation started. Requires operator sign-off
before any implementation begins.**

## Mode

PAPER / RESEARCH / READ ONLY. No signing, no funded execution, no live money. This preregistration
changes **zero** decision, admission, hazard, entry, or execution behavior. It is annotation-only:
every episode continues through the exact same pipeline it goes through today; this only adds a
label that is logged and (optionally, see "Surfacing," below) shown to a human, never acted on
automatically.

## Origin (consumed result, motivating only)

Today (2026-09-29), `docs/participant-quality-tail-risk-rejection-v0-preregistration-2026-09-28.md`
produced a real result: `PASS_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0`, run key
`participant-quality-tail-risk-v0-20260929-04` (logged in
`docs/migration/RESEARCH_STATE_LEDGER_2026-09-27.md`). LOW-group catastrophic-loss rate (900s
return <= -80%) was 88.9% vs. 37.5% for the full population (gap 51.4pp, bar 15pp); excluding LOW
did not harm the kept group's median return.

That result is **not reused as data here** — its sample is burned per its own failure discipline
("the run key/sample is burned once acquired, PASS or not"). It motivates this document only. A
single n=56 result is not enough to justify letting a filter touch anything real; this
preregistration exists to accumulate independent, fresh, prospective confirmation before that
question is even asked.

## What this is

A **shadow annotation** experiment: attach a `participant_quality_group` label (`HIGH` / `LOW` /
`unknown`) to newly admitted market-opportunity episodes as they occur, going forward, using the
same frozen feature
(`native_participant_prior_900_route_quote_return_median_of_wallet_medians_pct`) and the same
outcome-blind-cutoff methodology already proven live
(`participant_quality_native_memory_v1.py`). The label is computed and logged; nothing reads it to
change behavior.

The natural attachment point is alongside the existing systems-readiness record
(`src.opportunity_decision_readiness.OpportunityDecisionReadiness`, which already carries
per-episode `classification`/`blockers`/`hazard_status` — the label would live next to it as a new,
independent, read-only field, not inside it, to keep this dataclass's existing frozen contract
untouched). No design/implementation decision is made by this document; that happens only after
operator sign-off, as its own smallest-diff change.

## What this is not

- not a rescue or reinterpretation of the closed `KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE` result;
- not a reuse of the burned `...-04` tail-risk-rejection sample or its cutoff;
- not a change to admission, hazard, entry, or exit logic;
- not an automated skip — per the product roadmap in `CLAUDE.md`
  (`... -> validated signal -> human TAKE/SKIP -> manual execution -> ...`), any use of this label
  to influence a decision stays a *human* TAKE/SKIP input, never an automated filter, at this
  product stage;
- not funded, not live-money, not an execution-realism claim;
- not a claim that a single confirmation (today's PASS) is sufficient — this is explicitly the
  replication step before any further step is even considered.

## Fresh cutoff, not reused

Each shadow-annotation window computes its own outcome-blind cutoff from its own memory build
(same `participant_quality_native_memory_v1.py` mechanism as every prior run), under its own new
run-key lineage (e.g. `participant-quality-shadow-v0-<date>-...`). It never reads the `-01`
memory's cutoff (`-86.0484432047999`) or the closed selector's cutoff (`-65.65233776856643`).
Reusing either would quietly smuggle burned-sample information into a live-adjacent path.

## Primary measurement (accumulated, not single-shot)

Unlike the burn-once holdout protocols in this repo, this is a **standing, append-only
observational log**: each shadow window's episodes, their `participant_quality_group` label, and
(once matured) their 900s route-only outcome are appended to a durable table. This intentionally
does not "burn" like a holdout, because nothing here informs any decision that could be biased by
having seen the data — it is pure logging of what already happened, computed outcome-blind exactly
as today's live pipeline already does.

Review checkpoint (pre-specified, not adjustable after the fact):

- **minimum accumulated sample before any review**: LOW >= 20 paired outcomes, ALL >= 60 paired
  outcomes (higher than today's single-run minimums, since this is meant to be a genuine
  replication, not a repeat of the same power level)
- at that checkpoint, evaluate with the **same three gates** as the original tail-risk-rejection
  preregistration (LOW tail rate > ALL tail rate; gap >= 15pp; HIGH-only median not worse than
  ALL median), computed fresh on this accumulated shadow data only — never merged with the `-04`
  sample
- classifications: `PASS_PARTICIPANT_QUALITY_TAIL_RISK_SHADOW_ANNOTATION_V0`,
  `FAIL_PARTICIPANT_QUALITY_TAIL_RISK_SHADOW_ANNOTATION_V0`,
  `INCONCLUSIVE_PARTICIPANT_QUALITY_TAIL_RISK_SHADOW_ANNOTATION_V0_SUPPORT`

## Surfacing (deferred, its own decision)

Two independent decisions, **not both authorized by this document**:

1. **Logging the label** (this document, once signed off): always on, invisible to any human
   workflow, zero behavior change. This alone is enough to accumulate the replication sample.
2. **Showing the label to a human** as an advisory note next to an episode (e.g. "this episode's
   admitted wallets score LOW on participant quality; historically LOW correlates with
   catastrophic loss, still your call"): a **separate, later decision**, only worth considering
   after step 1's checkpoint reads PASS. Not part of this preregistration's authorization.

## Failure discipline

Same posture as every other frozen protocol in this repo:

- no cutoff retune, no materiality-bar change, no switching the contrast after seeing interim data;
- no peeking at the accumulated log to decide when to stop early — the checkpoint sample sizes
  above are frozen before any annotation starts;
- a FAIL or INCONCLUSIVE at the checkpoint closes this specific shadow-annotation effort; it does
  not retroactively reopen or weaken the closed KILL result or the `-04` PASS, and does not
  authorize a second checkpoint on the same accumulated data (a genuinely new attempt would need
  its own fresh preregistration);
- this document authorizes step 1 (logging) only, if signed off. Step 2 (surfacing) and any
  eventual skip-gate implementation each require their own explicit, separate operator
  authorization, per `CLAUDE.md`'s rule against auto-promoting hypotheses or broadening scope
  without evidence.

## What a PASS at checkpoint would prove / not prove

Would provide a second, independent, larger-sample confirmation that the participant-quality
feature carries real tail-risk information, gathered under live production conditions rather than
a short synthetic holdout window. Would **not** prove: alpha, executable P&L, or authorize any
automated behavior change — those remain further, separately gated questions.

## Implementation sketch (not authorized yet — for operator review only)

- add one small, additive function that, given an admitted episode and the active shadow-window's
  memory report, computes and returns the `HIGH`/`LOW`/`unknown` label (reusing
  `participant_quality_native_memory_v1`'s existing lookup, not duplicating it);
- log the label plus episode key plus timestamp to a new, narrow durable table (own migration,
  own module, no changes to existing tables);
- a separate, offline, read-only script computes the checkpoint gates from that table when asked —
  never runs automatically, never blocks or slows the live pipeline;
- estimated diff: one new small module (annotation + storage), one new offline evaluator script
  reusing the existing `_metrics_dict`/`_tail_rate` pattern from
  `participant_quality_tail_risk_rejection_v0.py`. No changes to any existing frozen file.
