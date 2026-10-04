# HANDOFF — V68 Flow60 Buy-Share Prospective Holdout — 2026-10-04

## Who this is for

Written for whoever (human or another AI assistant, e.g. GitHub Copilot) picks up
this work next, with zero prior context from the Claude Code session that produced
it. Read this file, then `docs/migration/START_HERE_CLAUDE_2026-09-27.md`,
`BRANCH_AUTHORITY_MAP_2026-09-27.md`, `CODEBASE_MAP_2026-09-27.md`,
`RESEARCH_STATE_LEDGER_2026-09-27.md`, and the root `CLAUDE.md` before touching
anything. This project runs under strict scientific/process discipline (frozen
thresholds, burn-once run-keys, no live money) — follow it exactly, do not
improvise around it.

## Branch / commit authority right now

- Branch: `research/rust-signal-plane-live-shadow-v0`
- Head at handoff time: `c583e17` (pushed to origin)
- This is the systems-authority branch per `CLAUDE.md`. All work below happened here.
- Do **not** merge the divergent `research/post-transition-pullback-reacceleration-v0`
  line into this for convenience — it is intentionally separate.

## Live operation currently in flight — hard constraints

The operator ("Murillo") is running **v68-09** live, right now, on his own
machine (not this checkout), using the `1.5s` 429-backoff fix (`f865745`). While
v68-09 is unresolved:

- **Do not start any new run** (v68-10, soak, probe). No Jupiter calls, no
  on-chain sync. The 429 limit is account/IP-level — any extra load worsens the
  in-flight run's `lateness_p95`.
- **Do not checkout/merge/rebase/pull** on the tree where v68-09 runs. Any code
  change goes in a separate branch/worktree and only merges after v68-09 is
  classified.
- **SQLite reads are read-only only.**

## What V68 is

Frozen prospective holdout on feature `flow60_buy_share_pct` (favorable LOW,
opposite HIGH), horizons 300s/900s/3600s, primary horizon 900s. Economic contract:
`('flow60_buy_share_pct', 57.1429, 65.7143, 'LOW', 'HIGH', 900, 5)`.

Control flow: `route_research_v68_release.py` → `run_signal_plane_v68_v0()` →
two sequential subcohorts (A, then B) via `run_signal_plane_forward_cohort_v0`
(`src/signal_plane_forward_cohort_v0.py`). Both cohorts together ARE the frozen
preregistered sample for an attempt — not a dry run. The outer wrapper returns
`FAIL_V68_SIGNAL_PLANE_SUBCOHORT` on the first failed subcohort, so
`build_early_opportunity_dataset_v55` / `primary_gate_v68` (where any LOW/HIGH
economic number gets computed) is only ever reached if BOTH A and B pass their
systems gates. No LOW/HIGH economic number has been computed or seen in any
aborted attempt (v68-04 through v68-08) as a result.

Subcohort pass requires ALL of: bridge PASS, `decision_count >=
SUBCOHORT_MIN_DECISIONS=30` (frozen, cap 40), collection classification PASS,
`lateness_p95 <= target_lateness_p95_max_seconds=2` (frozen), `lineage_violations
== 0`, `ready_horizons == 3`. `_strict_run_keys_fresh` requires both `{base}-A`
and `{base}-B` keys fresh simultaneously — a passed A cannot be banked with a
later fresh B; a failed attempt burns both keys together.

## What happened this session, in order

1. **v68-04**: `PROVIDER_ERROR` attrition from transient Jupiter errors → fixed
   with a bounded 3-attempt/0.5s retry, commit `2e847c7`.
2. **v68-05/v68-06**: failed the decision-count gate. Root-caused as pure
   admission-volume/time-of-day variance, not a code defect. Recommended a
   12h-19h BRT run window (grounded via WebSearch on Pump.fun launch clustering).
3. **v68-07**: HTTP 429 burst (confirmed via `error_message`: "[API Gateway] Too
   many requests", 57/59 of that run's errors) → fixed with a 429-specific 3.0s
   backoff, commit `5ead9ee`.
4. **v68-08**: cleared the decision-count gate (time window fix worked) but
   failed `lateness_p95=6s > 2` on cohort B — a direct, mathematically-guaranteed
   side effect of the 3.0s backoff itself. Real retry-bucket counts hand-
   reconstructed from stored outcomes: 76 needed 0 retries, 16 needed exactly 1,
   13 needed exactly 2, 15 exhausted all attempts. Chose `1.5s` (dominates `1.0s`
   by covering the full "needs ≤3.0s" group with certainty) → commit `f865745`.
   Explicitly flagged, unresolved risk: the 300s horizon projects to exactly the
   30-per-horizon floor with zero margin, and `lateness_p95` is not guaranteed to
   clear 2s even at 1.5s.
5. Operator started **v68-09** live with the 1.5s fix. While it was running, the
   operator issued a large multi-phase work order (Fase A/B/C/D, detailed below).
6. **A2 done**: wrote and committed
   `docs/v68-jupiter-retry-backoff-protocol-compliance-note-2026-10-04.md`
   (commit `c583e17`, pushed). Verifies `2e847c7`/`5ead9ee`/`f865745` against the
   frozen pacing/missingness/no-economic-retry invariants. Result: (a) holds in
   substance but "only HTTP error class" is an imprecise description of a wider
   `JupiterOrderError` trigger set, still blind to price; (b) holds; (c) holds
   (confirmed via `git show --stat`, none of the three commits touch
   `signal_plane_forward_cohort_v0.py`); **(d) does NOT hold as a guarantee** —
   the retry is bounded by its own constants (`MAX_ATTEMPTS`, backoff), not
   provably within `target_lateness_p95_max_seconds=2`. This was already a
   disclosed residual risk in `f865745`'s own comment, not a new violation.

## The full Fase A/B/C/D work order from the operator (verbatim intent)

Context cited by the operator: a program-state audit exists in "seção 10 de
claude/copytrader-memecoin-research-landscape.md (projeto Copytrader)" —
**confirmed NOT to exist anywhere in this git repo** (no `claude/` directory, no
file by that name). It is almost certainly content in a separate Claude.ai
Project knowledge base. Whoever continues this cannot assume its contents —
ask the operator to paste "seção 10" if it matters to how Fase A should read.

### Rules while v68-09 runs
See "Live operation" constraints above — unchanged.

### FASE A (write offline, commit before v68-09's result exists)
- **A1** — PENDING. A pre-registered decision tree for v68-09, as a new doc in
  `docs/`, content exactly matching FASE C below.
- **A2** — DONE (`c583e17`, see above).
- **A3** — PENDING. "No-peeking" certification: confirm from logs/harness code
  that no aborted attempt (v68-04–v68-08, especially v68-08 cohort A which
  passed systems gates) ever computed/displayed a LOW/HIGH economic number. The
  control-flow argument above (outer wrapper short-circuits on first failed
  subcohort) already supports this; A3 should make it a formal, citable
  certification.
- **A4** — PENDING. In a **separate, unmerged branch**: add per-attempt
  timestamp persistence to the retry logic in `src/jupiter_research_exit_route.py`
  (currently only the final attempt's timestamp is persisted, via
  `complete_provider_attempt`'s `completed_at` / the outcome's `observed_at` —
  nothing captures each individual attempt's start/end). Without this, lateness
  cannot be bounded with real data; if v68-09 fails again on lateness, the next
  fix must be measurement-based, not another guessed constant.
- **A5** — PENDING, zero-cost/offline. Register three external-evidence items in
  `docs/research-evidence-registry-v1-2026-09-02.md` and
  `docs/external-evidence-reuse-map-v1.md` (note: filenames carry a date suffix
  the operator's shorthand omits) using the existing A–E format: "Freeze
  Authority Abuse" (arXiv 2603.24625), "Bundle Bot Detection" (arXiv 2601.08641,
  ACM WWW 2026), and a downgrade of "Pine Analytics — Exit Liquidity Machines"
  (non-peer-reviewed Substack, ~98% admitted false-negative rate). **These three
  citations are unverified** — flagged to the operator, no answer yet on whether
  to WebSearch-verify them or mark them explicitly as operator-supplied/
  unverified. Also: read-only, extract `largest_winner_share_gross_profit_pct`
  from `docs/native-participant-quality-holdout-v1-result-2026-09-24.md` and
  document whether the profit-factor gate that drove its KILL verdict was an
  outlier artifact (without reopening the KILL), and whether the same
  `_metrics_dict` function (in `participant_quality_tail_risk_rejection_v0.py`,
  repo root) computes profit-factor for the V68 gates too — note
  `route_research_evaluation.py::_metrics()` is V68's actual profit-factor
  computation (lines 82-157); confirm/contrast against `_metrics_dict` before
  answering this.
- **A6** — PENDING, draft only, touches no data. A v60 preregistration, and a
  "Bundle Bot Detection V0" preregistration with a paired placebo control baked
  in from the first discovery pass (pattern name "RED-COHORT-2026-v1").

### FASE B — as soon as v68-09 finishes
Report the official classification and system numbers (`ready_horizons`,
`lineage_violations`, `lateness_p95` per cohort, availability per horizon)
**before any other action.** Use `evaluate_route_research_run()` in
`src/route_research_evaluation.py` and the same manual
`load_route_research_outcomes` diagnostic pattern used for v68-08.

### FASE C — the decision tree (this exact content must become A1's doc)
- Systems/acquisition/causal-audit failure (not economic verdict): log, burn
  the key, root-cause. Do not run v68-10 unilaterally. Operator's own
  suggestion: "at most 1 more cycle, and only if the fix comes from measurement
  (A4); otherwise a dedicated hardening sprint before any new attempt."
- `INCONCLUSIVE_V68_PRIMARY_SUPPORT`: sample burned, no auto-rerun — retrying
  after seeing economic data needs a written, pre-approved stopping rule from
  the operator first.
- `FAIL_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS` or
  `FAIL_V68_FEATURE_OBSERVABILITY`: V68 closes permanently (no MID, no other
  horizon, no other v55 feature, no subcohort cherry-picking). Path moves to
  v60 + Bundle Bot Detection (A6).
- `PASS_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS`: first
  prospective signal, explicitly **not** an edge. Required next steps, in
  order, none skippable: (1) descriptive robustness report — n per bin per
  subcohort, mean/median, profit factor, result excluding top winner and top-3,
  top-winner's share of gross profit, coverage/missingness (Gate 3 list in
  `docs/live-readiness-gates-v1.md`); (2) Gate 2 causal replay with real costs
  over the LOW subset — stop and report if not net-positive before spending a
  replication; (3) pre-register and run a confirmatory replication, fresh key,
  larger target n; (4) only then LOW becomes a TAKE/SKIP candidate, then Gate 4
  shadow. No real money at any point.

### FASE D — after v68-09 is classified, regardless of outcome
- Run v60 for real: `wallet_strategy_lab.py --sync-onchain` on the 8 candidate
  wallets → frozen manifest via `build_wallet_cohort_manifest_v65`
  (`src/wallet_cohort_manifest_v65.py`) → convergence evidence via
  `src/opportunity_wallet_convergence_v60.py` over already-captured
  `StoredMarketTrade` data. Confirm the 8 wallets' data coverage first.
- Separately reviewed branch, outside the frozen V68 lineage: fix
  `live_shadow.py`'s RPC fallback using `SOLANA_RPC_FALLBACK_URLS`; persist the
  `creator` field `src/pump_bonding_stream.py` already decodes but doesn't
  persist.
- Hard constraint: "same episode semantics" is frozen under V68 — none of these
  Fase D changes may alter how any V68 attempt acquires episodes.

### "Leva pra mim" — do not decide alone, surface to operator
- The pending "Participant Quality Tail-Risk Shadow Annotation V0" draft
  (commit `52c9c21`, confirmed real, title "Draft Participant Quality Tail-Risk
  Shadow Annotation V0 prereg" — branch location not yet determined), awaiting
  operator sign-off.
- Any conflict found while doing A2 or A3. (A2's item (d) finding was already
  surfaced — operator has not yet responded on whether to proceed.)
- The V68 infra-budget decision if v68-09 fails.

### Guardrails (never violate)
- No closed FAIL/KILL/INCONCLUSIVE result is ever reopened.
- No frozen economic threshold is ever touched (`V68_LOW_MAX`, `V68_MID_MAX`,
  the 9 PASS gates, `SUBCOHORT_MIN_DECISIONS`,
  `target_lateness_p95_max_seconds`).
- Nothing proceeds to a live or shadow signal plane without a written economic
  verdict first.

## Open questions awaiting the operator's answer (as of handoff)

1. A2 found item (d) ("retry bounded by the lateness gate") does not hold as a
   guarantee — disclosed, not a new violation. Operator asked whether to
   proceed into A1/A3/A4/A5/A6 given this, or weigh in on (d) first. **Not yet
   answered.**
2. A5's three external citations are unverified. Operator asked whether to
   WebSearch-verify them or write them in explicitly marked
   operator-supplied/unverified. **Not yet answered.**

## Immediate next action for whoever continues this

Do not resume Fase A execution (A1/A3/A4/A5/A6) until the two open questions
above are answered by the operator — they were raised under the operator's own
explicit "para e me avisa" instruction, which takes precedence over the
"commit everything before the result lands" instruction once something doesn't
cleanly hold. If the operator has answered elsewhere (e.g. directly to Copilot)
and that answer isn't reflected in this file, treat this file as stale on that
point and defer to the operator's latest word.

If v68-09's result arrives before the above is resolved: Fase B (report the
classification + system numbers) is not blocked by the open questions and
should happen immediately regardless, per the operator's explicit ordering.
