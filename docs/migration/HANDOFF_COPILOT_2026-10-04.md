# HANDOFF — V68 Flow60 Buy-Share Prospective Holdout — 2026-10-04 (rev. 2)

## Who this is for

Written for whoever (human or another AI assistant, e.g. GitHub Copilot) picks up
this work next, with zero prior context from the Claude Code session that produced
it. Read this file, then `docs/migration/START_HERE_CLAUDE_2026-09-27.md`,
`BRANCH_AUTHORITY_MAP_2026-09-27.md`, `CODEBASE_MAP_2026-09-27.md`,
`RESEARCH_STATE_LEDGER_2026-09-27.md`, and the root `CLAUDE.md` before touching
anything. This project runs under strict scientific/process discipline (frozen
thresholds, burn-once run-keys, no live money) — follow it exactly, do not
improvise around it.

This is **rev. 2** of this file. Rev. 1 (committed as `57275d1`) was written while
`v68-09` was still running live. `v68-09` has since finished (`FAIL_V68_SIGNAL_PLANE_SUBCOHORT`)
and the Fase A work order (A1-A6) was completed out-of-band, in a separate Claude.ai
Project session, delivered as a git bundle and imported here. This revision reflects
that current state — treat rev. 1's "while v68-09 runs" constraints as historical.

## Branch / commit authority right now

- Branch: `research/rust-signal-plane-live-shadow-v0`
- This is the systems-authority branch per `CLAUDE.md`. All work below happened here.
- Two additional branches now exist on `origin`, both based on commit `57275d1` of
  this branch, imported from an externally-produced git bundle (see "Fase A" below):
  `research/v68-09-fase-a-prereg` (docs only) and `research/v68-a4-per-attempt-timestamps`
  (code, not merged into this lineage).
- Do **not** merge the divergent `research/post-transition-pullback-reacceleration-v0`
  line into this for convenience — it is intentionally separate.

## What V68 is

Frozen prospective holdout on feature `flow60_buy_share_pct` (favorable LOW,
opposite HIGH), horizons 300s/900s/3600s, primary horizon 900s. Economic contract:
`('flow60_buy_share_pct', 57.1429, 65.7143, 'LOW', 'HIGH', 900, 5)`.

Control flow: `route_research_prospective_flow60_buy_share_holdout_v68_signal_plane_v0.py`
→ `run_signal_plane_v68_v0()` → two sequential subcohorts (A, then B) via
`run_signal_plane_forward_cohort_v0` (`src/signal_plane_forward_cohort_v0.py`). Both
cohorts together ARE the frozen preregistered sample for an attempt — not a dry run.
The outer wrapper returns `FAIL_V68_SIGNAL_PLANE_SUBCOHORT` on the first failed
subcohort, so `build_early_opportunity_dataset_v55` / `primary_gate_v68` (where any
LOW/HIGH economic number gets computed, using `robust_return_metrics_v47` — see the
correction below) is only ever reached if BOTH A and B pass their systems gates. No
LOW/HIGH economic number has been computed in any attempt so far (v68-04 through
v68-09).

Subcohort pass requires ALL of: bridge PASS, `decision_count >=
SUBCOHORT_MIN_DECISIONS=30` (frozen, cap 40), collection classification PASS,
`lateness_p95 <= target_lateness_p95_max_seconds=2` (frozen), `lineage_violations
== 0`, `ready_horizons == 3`. `_strict_run_keys_fresh` requires both `{base}-A`
and `{base}-B` keys fresh simultaneously — a passed A cannot be banked with a
later fresh B; a failed attempt burns both keys together.

## Session history, v68-04 through v68-09

1. **v68-04**: `PROVIDER_ERROR` attrition from transient Jupiter errors → fixed
   with a bounded 3-attempt/0.5s retry, commit `2e847c7`.
2. **v68-05/v68-06**: failed the decision-count gate (admission-volume/time-of-day
   variance, not a code defect). Recommended a 12h-19h BRT run window.
3. **v68-07**: HTTP 429 burst → fixed with a 429-specific 3.0s backoff, commit `5ead9ee`.
4. **v68-08**: cleared the decision-count gate but failed `lateness_p95=6s > 2` on
   cohort B — a direct, mathematically-guaranteed side effect of the 3.0s backoff
   itself. Chose `1.5s` (dominates `1.0s` by covering the full "needs ≤3.0s" group
   with certainty) → commit `f865745`. Flagged, unresolved risk at the time: the
   300s horizon projects to exactly the 30-per-horizon floor with zero margin, and
   `lateness_p95` is not guaranteed to clear 2s even at 1.5s.
5. **A2 done** (`c583e17`): protocol-compliance note on commits `2e847c7`/`5ead9ee`/
   `f865745` against the frozen pacing/missingness/no-economic-retry invariants.
   (a)/(b)/(c) hold; **(d) ("bounded by the lateness gate") does not hold as a
   guarantee** — bounded only by its own constants, not provably within the frozen
   2s gate. Disclosed, not a new violation; already flagged in `f865745`'s own comment.
6. Rev. 1 of this handoff committed (`57275d1`) while `v68-09` was running live.
7. **`v68-09` finished: `FAIL_V68_SIGNAL_PLANE_SUBCOHORT`.** Preflight and promotion
   both re-confirmed clean (`PASS_V68_RELEASE_READINESS_V1`, `PASS_V68_SIGNAL_PLANE_PROMOTION_V0`
   pinned to `git_head=f865745`, live pubsub health PASS). At least one cohort reached
   real forward collection (one `[v43-forward] scheduled=120...` header = a full
   40-episode cohort). **Root cause not yet known** — see "Fase B" below.
8. **Fase A (A1-A6) completed out-of-band** (a separate Claude.ai Project session,
   not this one) and delivered as a git bundle based on this branch's `57275d1`.
   Imported read-only (`git fetch <bundle> <refspec>:<refspec>` — creates local
   branch refs only, no checkout, no merge) and pushed to origin. See breakdown below.

## Fase A — status (all items done or landed in a separate branch)

- **A1 — DONE.** `docs/v68-09-preregistered-decision-tree-2026-10-04.md`, on
  `research/v68-09-fase-a-prereg`. Written and committed at ~22:05 UTC on 2026-10-04,
  before `v68-09`'s result existed (anteriority = the branch's push timestamp).
  Content matches Fase C below exactly.
- **A2 — DONE** (`c583e17`, this branch). See history item 5 above.
- **A3 — DONE.** `docs/v68-no-peeking-certification-v68-04-to-08-2026-10-04.md`, on
  `research/v68-09-fase-a-prereg`. Certifies, from control-flow evidence, that no
  LOW/HIGH economic number was ever computed in v68-04 through v68-08 (the gate
  code path requires both subcohorts to pass first, and none did). Important
  finding: `_descriptive_readiness()` (`src/signal_plane_forward_cohort_v0.py`)
  *does* compute full aggregate return statistics (mean/median/PF/best/worst) via
  `evaluate_route_research_run()` for every subcohort that reaches the readiness
  check, as part of normal harness operation — computed in memory, never printed
  or persisted by the harness itself. Residual, disclosed uncertainty: the cert
  cannot fully rule out that a *manual* diagnostic (run on the operator's machine,
  not in this repo) printed the full aggregate object rather than selected fields.
  Recommendation adopted here: any report on an attempt that didn't reach the
  primary gate shows system fields only, never return fields.
- **A4 — DONE, NOT MERGED.** Branch `research/v68-a4-per-attempt-timestamps`
  (pushed to origin). Adds per-`order()`-try wall-clock telemetry (`try`,
  `started_at`, `ended_at`, `result`, `status_code`, `backoff_seconds`) into the
  existing `details` dict in `src/jupiter_research_exit_route.py`. Diff reviewed:
  observation-only, does not change retry/backoff/pacing logic or any frozen
  threshold. **Merges into this lineage only if `v68-09`'s pending root-cause
  analysis lands on "lateness again, next fix must be measurement-based"** — the
  exact condition in the A1 decision tree's branch 1. Not merged yet.
- **A5 — DONE.** Registry entries E10 (arXiv 2603.24625, Solana rug-pull taxonomy,
  grade C), E11 (arXiv 2601.08641, ACM WWW 2026, Pump.fun bundle/sniper/bump-bot
  detection, grade A/B), E12 (Pine Analytics "Exit Liquidity Machines", grade E) in
  `docs/research-evidence-registry-v1-2026-09-02.md`, plus matching entries in
  `docs/external-evidence-reuse-map-v1.md`, both on `research/v68-09-fase-a-prereg`.
  Also `docs/participant-quality-v1-pf-gate-outlier-check-2026-10-04.md` (same
  branch): does not reopen the Participant Quality KILL; finds the outlier-share
  number (`largest_winner_share_gross_profit_pct`) is not in the repo (artifacts/
  is gitignored) and gives the operator a read-only command to extract it from his
  own machine; separately confirms the correction below.
  - **Correction 1 (to rev. 1 of this doc):** the V68 primary gate's profit-factor
    computation is `robust_return_metrics_v47` (`src/route_research_feature_robustness_v47.py`,
    the same function used by the Native Participant Quality Holdout), used inside
    `primary_gate_v68` (`src/route_research_prospective_flow60_buy_share_v68.py`).
    `route_research_evaluation.py::_metrics()` is **not** the gate's PF — it is used
    only by `_descriptive_readiness()` for subcohort-readiness classification,
    whose economic numbers are discarded (see A3 above).
  - **Correction 2 (to rev. 1 of this doc):** the Pine Analytics "Exit Liquidity
    Machines" source does **not** state a "~98% false-negative rate". The real
    reported figure: its narrow same-block, direct-funded-sniper pattern covers
    ~1.75% of Pump.fun launches (registry E12). Rev. 1's characterization was an
    internal misreading; corrected in the registry itself, not just here.
- **A6 — DRAFTED, awaits operator sign-off.** Both on `research/v68-09-fase-a-prereg`:
  `docs/v60-wallet-convergence-discovery-v0-preregistration-DRAFT-2026-10-04.md` and
  `docs/bundle-bot-detection-v0-preregistration-DRAFT-2026-10-04.md` (the latter
  bakes in an activity-matched placebo, pattern name `RED-COHORT-2026-v1`, from the
  first discovery pass). No engineering priority before sign-off.

## Fase B — executed, incomplete pending operator action

Per the no-peeking recommendation (A3) and the operator's own explicit instruction,
any report on an attempt that didn't reach `primary_gate_v68` shows **only** system
fields (`scheduled`, `available`, `pending`, `unavailable_or_error`, `coverage_pct`,
`classification`, `lateness_p95`, `lineage_violations`) — never return fields
(`mean`/`median`/`profit_factor`/`positive_share`/`largest_winner_*`).

`v68-09` did not reach `primary_gate_v68` (`FAIL_V68_SIGNAL_PLANE_SUBCOHORT`). The
CLI's `main()` (confirmed by reading
`route_research_prospective_flow60_buy_share_holdout_v68_signal_plane_v0.py` lines
249-273) never prints the per-cohort system-field object for this classification —
it only prints `version` and `classification`, exactly what the operator's pasted
terminal output shows. The real per-cohort numbers exist only in already-persisted
SQLite rows on the operator's machine, not in any stdout log or artifact file, and
not in this checkout (the sandbox's local `data/copytrader.db` is stale, dated
before `v68-09` ran, with zero `v68-09` rows — confirmed by a read-only query).

A read-only diagnostic (reusing existing functions —
`_cohort_schedule_audit`/`_descriptive_readiness` from
`src/signal_plane_forward_cohort_v0.py`, `evaluate_route_research_run` from
`src/route_research_evaluation.py` — no new Jupiter calls, no write) was handed to
the operator to run against `v68-09-A` and `v68-09-B` and paste back. Root cause is
**pending that output** — do not guess it from the partial stdout alone.

## Fase C — the decision tree (verbatim location, now applied)

Full text: `docs/v68-09-preregistered-decision-tree-2026-10-04.md` on
`research/v68-09-fase-a-prereg`. `v68-09`'s result routes to **branch 1**
(systems/acquisition failure, not an economic verdict):
log it, burn `v68-09-A`/`v68-09-B` (done, see ledger), root-cause it (pending, see
Fase B), **do not run `v68-10` unilaterally**. Infra budget, per the operator's own
rule in that document: at most one more cycle, and only if the next fix is derived
from measurement (A4); otherwise a dedicated hardening sprint first. The other three
branches (`INCONCLUSIVE_V68_PRIMARY_SUPPORT`, the two closing-FAIL classifications,
and the PASS branch with its ordered Gate 2/3/4 sequence) are unchanged from rev. 1
and did not fire this time.

## Fase D — now technically unblocked, not started

The original work order said Fase D (real v60 analysis via `wallet_strategy_lab.py
--sync-onchain` → `build_wallet_cohort_manifest_v65` → the convergence evidence in
`src/opportunity_wallet_convergence_v60.py`; plus, in a separate reviewed branch,
fixing `live_shadow.py`'s RPC fallback and persisting `pump_bonding_stream.py`'s
`creator` field) starts "after v68-09 is classified, regardless of outcome." It is
now classified (FAIL). **Not started** — the operator's latest instructions were
scoped to Fase B/C and the two corrections, not a go-ahead for Fase D's on-chain
sync, which is a real network action with real cost/time and wasn't explicitly
re-authorized this round. Flag this to the operator rather than starting it
unprompted. Hard constraint if/when it starts: "same episode semantics" is frozen
under V68 — none of these changes may alter how any V68 attempt acquires episodes.

## "Leva pra mim" — do not decide alone, surface to operator

- The pending "Participant Quality Tail-Risk Shadow Annotation V0" draft
  (commit `52c9c21`, confirmed real), awaiting operator sign-off. Unchanged.
- A6's two draft preregistrations (above), awaiting sign-off.
- Whether to merge `research/v68-a4-per-attempt-timestamps` — gated on the
  pending root-cause result, per Fase C branch 1.
- Whether to start Fase D now that `v68-09` is classified.

### Guardrails (never violate)
- No closed FAIL/KILL/INCONCLUSIVE result is ever reopened. (The Participant
  Quality PF-gate outlier check, A5, explicitly does not reopen that KILL.)
- No frozen economic threshold is ever touched (`V68_LOW_MAX`, `V68_MID_MAX`,
  the 9 PASS gates, `SUBCOHORT_MIN_DECISIONS`,
  `target_lateness_p95_max_seconds`).
- Nothing proceeds to a live or shadow signal plane without a written economic
  verdict first.

## Open questions awaiting the operator's answer (as of this revision)

1. `v68-09`'s exact per-cohort root cause — pending the read-only diagnostic
   output requested in Fase B.
2. Whether `research/v68-a4-per-attempt-timestamps` merges into this lineage —
   gated on (1), per the decision tree.
3. Whether to start Fase D now.

## Immediate next action for whoever continues this

Wait for the operator's diagnostic output for `v68-09-A`/`v68-09-B` (system fields
only). On receipt: complete the ledger entry's root-cause section with the real
numbers, decide the A4-merge question per Fase C branch 1's exact condition, and
report back before taking any other action. Do not start `v68-10`, any new Jupiter
call, or Fase D's on-chain sync without the operator's explicit go-ahead.
