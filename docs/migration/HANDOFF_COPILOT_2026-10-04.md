# HANDOFF — V68 Flow60 Buy-Share Prospective Holdout — 2026-10-04 (rev. 3)

## Who this is for

Written for whoever (human or another AI assistant, e.g. GitHub Copilot) picks up
this work next, with zero prior context from the Claude Code session that produced
it. Read this file, then `docs/migration/START_HERE_CLAUDE_2026-09-27.md`,
`BRANCH_AUTHORITY_MAP_2026-09-27.md`, `CODEBASE_MAP_2026-09-27.md`,
`RESEARCH_STATE_LEDGER_2026-09-27.md`, and the root `CLAUDE.md` before touching
anything. This project runs under strict scientific/process discipline (frozen
thresholds, burn-once run-keys, no live money) — follow it exactly, do not
improvise around it.

This is **rev. 3**. Rev. 1 (`57275d1`) was written while `v68-09` was still running.
Rev. 2 (`fb7091e`) recorded `v68-09`'s result as a new, not-yet-root-caused failure
signature. **Rev. 3 closes that question**: the operator supplied real timing
evidence and the root cause is now confirmed, not just hypothesized, and a
fail-closed detector for it exists in a separate, unmerged branch.

## Branch / commit authority right now

- Branch: `research/rust-signal-plane-live-shadow-v0`, currently at `6f40f9f`. This
  is the systems-authority branch per `CLAUDE.md`. All work below happened here.
- `research/v68-09-fase-a-prereg` and `research/v68-a4-per-attempt-timestamps`
  (both on `origin`, based on this branch's `57275d1`): the externally-produced
  Fase A work (see rev. 2 for the full breakdown — unchanged since).
- `research/v68-forward-collection-stall-guard` (on `origin`, based on this
  branch's `6f40f9f`, commit `22d9713`): **new this revision.** A fail-closed
  stall detector for the exact mechanism that caused `v68-09-A` (see "Fase B"
  below). Not merged into this lineage — merging it is the operator's explicit
  call, not automatic (see "Leva pra mim").
- Do **not** merge the divergent `research/post-transition-pullback-reacceleration-v0`
  line into this for convenience — it is intentionally separate.

## What V68 is

Frozen prospective holdout on feature `flow60_buy_share_pct` (favorable LOW,
opposite HIGH), horizons 300s/900s/3600s, primary horizon 900s. Economic contract:
`('flow60_buy_share_pct', 57.1429, 65.7143, 'LOW', 'HIGH', 900, 5)`.

Control flow: `route_research_prospective_flow60_buy_share_holdout_v68_signal_plane_v0.py`
→ `run_signal_plane_v68_v0()` → two sequential subcohorts (A, then B) via
`run_signal_plane_forward_cohort_v0` (`src/signal_plane_forward_cohort_v0.py`) →
each cohort's forward-outcome capture via `collect_route_research_forward_v43`
(`src/route_research_forward_collection_v43.py`). Both cohorts together ARE the
frozen preregistered sample for an attempt — not a dry run. The outer wrapper
returns `FAIL_V68_SIGNAL_PLANE_SUBCOHORT` on the first failed subcohort, so
`build_early_opportunity_dataset_v55` / `primary_gate_v68` (where any LOW/HIGH
economic number gets computed, using `robust_return_metrics_v47`) is only ever
reached if BOTH A and B pass their systems gates. No LOW/HIGH economic number has
been computed in any attempt so far (v68-04 through v68-09).

Subcohort pass requires ALL of: bridge PASS, `decision_count >=
SUBCOHORT_MIN_DECISIONS=30` (frozen, cap 40), collection classification PASS,
`lateness_p95 <= target_lateness_p95_max_seconds=2` (frozen), `lineage_violations
== 0`, `ready_horizons == 3`. `_strict_run_keys_fresh` requires both `{base}-A`
and `{base}-B` keys fresh simultaneously — a passed A cannot be banked with a
later fresh B; a failed attempt burns both keys together.

## Session history, v68-04 through v68-09 (root cause now closed)

1. **v68-04**: `PROVIDER_ERROR` attrition from transient Jupiter errors → fixed
   with a bounded 3-attempt/0.5s retry, commit `2e847c7`.
2. **v68-05/v68-06**: failed the decision-count gate (admission-volume/time-of-day
   variance, not a code defect). Recommended a 12h-19h BRT run window.
3. **v68-07**: HTTP 429 burst → fixed with a 429-specific 3.0s backoff, commit
   `5ead9ee`. **Revised this revision**: see item 10 below — the recorded cause
   (Jupiter's own sustained rate-limit window) is now a candidate alternative to
   a console-stall explanation, not reopened or overwritten.
4. **v68-08**: cleared the decision-count gate but failed `lateness_p95=6s > 2` on
   cohort B — a direct, mathematically-guaranteed side effect of the 3.0s backoff
   itself. Chose `1.5s` → commit `f865745`.
5. **A2 done** (`c583e17`): protocol-compliance note on `2e847c7`/`5ead9ee`/
   `f865745`. (a)/(b)/(c) hold; **(d) does not hold as a guarantee** — disclosed,
   not a new violation.
6. Rev. 1 of this handoff committed (`57275d1`) while `v68-09` was running live.
7. **`v68-09` finished: `FAIL_V68_SIGNAL_PLANE_SUBCOHORT`.** Preflight/promotion
   re-confirmed clean beforehand.
8. **Fase A (A1-A6) completed out-of-band** and imported via git bundle (see
   branch list above) — full breakdown unchanged from rev. 2, repeated below.
9. **Root cause confirmed** (this revision, `6f40f9f`): the operator confirmed the
   machine did not sleep and supplied PowerShell `Get-History` timing plus
   `QuickEdit=1`. Code read of
   `src/route_research_forward_collection_v43.py` (pre-fix) confirms the exact
   mechanism: `deadline = time.monotonic() + runtime_seconds` is computed
   immediately before the function's one `print()` call, and the poll loop's own
   `while time.monotonic() < deadline` only runs after that print returns.
   Windows console "QuickEdit" text-selection mode blocks a process's `print()`
   until released; if that block lasted longer than the derived ~59.6-minute
   window, the loop's very first condition check already reads past the
   deadline -- zero iterations, zero submissions, zero captures, zero errors,
   exactly matching `v68-09-A`'s real data. `Get-History` corroborates the order
   of magnitude: the real run (id 100) took 7458s wall-clock against an expected
   ~3693s with no stall -- a ~3765s excess comparable to the ~59.6-minute window
   itself.
10. **`v68-07`'s root cause revised to a candidate hypothesis, not reopened**: the
    same freeze, if it happened mid-collection instead of before the loop
    started, fits the `v68-07` evidence at least as well -- already-submitted
    Jupiter calls run on worker threads unaffected by the frozen main thread, so
    newly-due outcomes would silently queue unsubmitted and then burst-submit the
    instant the console unblocked, plausibly producing both the observed 429
    storm and the ~1-hour 900s-horizon lateness without Jupiter itself
    sustaining an hour-long throttle. `v68-07` stays `FAIL_V68_SIGNAL_PLANE_SUBCOHORT`,
    burned, closed, exactly as before -- this is recorded as an alternative
    explanation, not a re-classification.
11. **Stall-detection guard implemented** (`research/v68-forward-collection-stall-guard`,
    commit `22d9713`, **not merged**): `src/route_research_forward_collection_v43.py`
    now takes its monotonic baseline before the risky `print()`, and the poll
    loop checks the gap since the last tick before doing anything else. A gap
    over `FORWARD_COLLECTION_V43_STALL_GAP_SECONDS=30.0` (new constant; normal
    iterations take well under a second) fails closed as the new, distinct
    `FAIL_ROUTE_ONLY_FORWARD_COLLECTION_STALL_DETECTED` classification instead of
    silently landing on `INCONCLUSIVE_NO_AVAILABLE_ROUTE_OUTCOME` (indistinguishable
    from a genuine zero-availability provider outage). Detector only -- cannot
    prevent the console behavior itself. No frozen parameter touched; both new
    `ForwardCollectionV43Summary` fields default to prior behavior, so no
    existing construction site breaks. Tests: `python -m unittest
    tests.test_route_research_forward_cohort_v43 tests.test_signal_plane_forward_cohort_v0
    -v` -> OK, 17/17, no regressions.

## Fase A — status (unchanged from rev. 2; all items done or in a separate branch)

- **A1 — DONE.** `docs/v68-09-preregistered-decision-tree-2026-10-04.md`, on
  `research/v68-09-fase-a-prereg`. Written before `v68-09`'s result existed.
- **A2 — DONE** (`c583e17`, this branch).
- **A3 — DONE.** `docs/v68-no-peeking-certification-v68-04-to-08-2026-10-04.md`.
  Certifies no LOW/HIGH economic number was computed in v68-04 through v68-08.
  Recommendation adopted: reports on attempts that didn't reach the primary gate
  show system fields only.
- **A4 — DONE, NOT MERGED.** `research/v68-a4-per-attempt-timestamps`. Per-`order()`-try
  telemetry, observation-only. **Confirmed this revision: its merge condition
  ("lateness again, fix must be measurement-based") is not met by `v68-09`'s
  actual root cause (a pre-loop stall, not a retry/backoff issue) -- A4 stays
  unmerged**, same conclusion as rev. 2, now on firmer footing.
- **A5 — DONE.** Registry entries E10/E11/E12, plus the two corrections already
  folded in (rev. 2): the V68 gate's PF function is `robust_return_metrics_v47`,
  not `route_research_evaluation.py::_metrics()`; Pine Analytics reports ~1.75%
  of launches matching its pattern, not a "~98% false-negative rate".
- **A6 — DRAFTED, awaits operator sign-off.** v60 and Bundle Bot Detection V0
  preregistrations on `research/v68-09-fase-a-prereg`. Unchanged.

## Fase B — root-caused and closed this revision

`v68-09` did not reach `primary_gate_v68`. Per the no-peeking recommendation (A3),
reports on such attempts show only system fields, never return fields -- this was
honored throughout.

**Confirmed root cause** (see session-history items 9-10 above for the full
mechanism and evidence): a Windows console QuickEdit stall in the collector's
pre-loop `print()`, not a provider/network/retry issue. Full detail in
`docs/migration/RESEARCH_STATE_LEDGER_2026-09-27.md`'s `v68-09` entry.

## Fase C — the decision tree, fully applied

Full text: `docs/v68-09-preregistered-decision-tree-2026-10-04.md`. `v68-09`
routed to **branch 1** (systems/acquisition failure): logged, `v68-09-A`/`-B`
burned, root-caused (now done, see above), **no `v68-10` run unilaterally**.
Infra budget per the operator's own rule: at most one more cycle, and only if the
next fix is measurement-based; otherwise a dedicated hardening sprint first. The
stall-detection guard (item 11 above) is exactly that kind of fix, but whether it
satisfies the "measurement-based" bar for authorizing a next cycle -- and whether
to spend that cycle now -- is the operator's call, not assumed here.

## Fase D — still not started

Unchanged from rev. 2: technically unblocked (v68-09 is classified), but no
go-ahead was given this round either. `--sync-onchain` is a real network action;
don't start it unprompted.

## "Leva pra mim" — do not decide alone, surface to operator

- The pending "Participant Quality Tail-Risk Shadow Annotation V0" draft
  (commit `52c9c21`), awaiting sign-off. Unchanged.
- A6's two draft preregistrations, awaiting sign-off. Unchanged.
- **Whether/when to merge `research/v68-forward-collection-stall-guard`** into
  this lineage -- new this revision. It's a detector, not a prevention, and
  doesn't by itself make a future attempt more likely to pass; folding it in is
  the operator's explicit call.
- `research/v68-a4-per-attempt-timestamps` stays unmerged (confirmed, see A4
  above) unless a future failure is actually the lateness repeat it targets.
- The `v68-10` infra-budget decision (per the operator's own adopted rule in the
  decision tree) -- root cause is now known, but running a next cycle is still
  his to decide, not automatic.
- Whether to start Fase D now.

### Guardrails (never violate)
- No closed FAIL/KILL/INCONCLUSIVE result is ever reopened.
- No frozen economic threshold is ever touched (`V68_LOW_MAX`, `V68_MID_MAX`,
  the 9 PASS gates, `SUBCOHORT_MIN_DECISIONS`,
  `target_lateness_p95_max_seconds`).
- Nothing proceeds to a live or shadow signal plane without a written economic
  verdict first.

## Open questions awaiting the operator's answer (as of this revision)

1. Merge `research/v68-forward-collection-stall-guard` into this lineage now, or
   hold it until (and if) a next attempt is authorized?
2. Is a `v68-10` attempt authorized at all right now, given the root cause is an
   operational/environment issue (console QuickEdit) rather than a code defect --
   the stall guard only detects a repeat faster next time, it does not prevent one?
3. Whether to start Fase D now.

## Immediate next action for whoever continues this

Do not run `v68-10`, merge either unmerged branch, or start Fase D's on-chain sync
without the operator's explicit go-ahead on the three open questions above. If the
operator authorizes a next cycle, confirm with them whether it should run on top
of the merged stall guard (so a repeat stall is classified immediately and
distinctly) or on the current lineage as-is.
