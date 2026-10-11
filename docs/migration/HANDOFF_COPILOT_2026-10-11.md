# HANDOFF — SIG-FAST H2 (SIG-FAST-POSTMIG) discovery + coverage-gate fix — 2026-10-11

## Who this is for

Written for whoever (human or another AI assistant, e.g. GitHub Copilot) picks up
this work next, with zero prior context from the Claude Code session that produced
it. Read this file, then `docs/migration/START_HERE_CLAUDE_2026-09-27.md`,
`BRANCH_AUTHORITY_MAP_2026-09-27.md`, `CODEBASE_MAP_2026-09-27.md`,
`RESEARCH_STATE_LEDGER_2026-09-27.md`, the root `CLAUDE.md`, and
`docs/research-hypothesis-registry-v1-2026-10-04.md` before touching anything.
This is a **different lineage** from `HANDOFF_COPILOT_2026-10-04.md` (that one is
about V68/`flow60_buy_share_pct`; this one is about H1/H2 inside
`SIG-FAST-DISC-V0`) — do not conflate the two, do not reopen either one for the
other's sake. Same discipline applies: frozen thresholds, burn-once run-keys,
no live money, never retune a rule after seeing the data it produced.

## Branch / commit authority right now

- Branch: `research/rust-signal-plane-live-shadow-v0`, currently at `16939ac`.
  Systems/Signal Plane/Research Plane authority per `CLAUDE.md`. All work below
  happened here.
- Source of truth for H1/H2 protocol:
  `docs/sig-fast-disc-v0-batch-preregistration-DRAFT-2026-10-08.md` (rev. 4 +
  several addenda, most recent: "Addendum — correção de implementação do gate de
  cobertura" and "Resultado real da Fase 3 CORRIGIDA").
- Running status log for the whole autonomous mandate (verbose, chronological,
  in Portuguese): `docs/sig-fast-AUTONOMOUS-STATUS.md`.
- Final result docs: `docs/sig-fast-h2-RESULTADO-2026-10-10.md` (original
  INCONCLUSIVE_SYSTEM), plus the DRAFT's "Resultado real da Fase 3 CORRIGIDA"
  section (2026-10-11, the re-run after the gate fix below).
- Hypothesis registry row: `docs/research-hypothesis-registry-v1-2026-10-04.md`,
  table row `SIG-FAST-DISC-V0 (H2)`.

## What H1/H2 are

Two candidate entry hypotheses inside the `SIG-FAST-DISC-V0` batch
(K=2, each with its own discovery + holdout 70/30 + separate confirmation):

- **H1 — SIG-FAST-COPY-G**: copy-trading a smart-money wallet cohort (design E11).
  Depends on a **live** collection (cohort can only be formed from fresh data with
  derivable price, never from old memory). Pre-registered, signed off, **no live
  session has started** — see `docs/sig-fast-h1-live-collection-plan-v0-2026-10-10.md`
  for the consolidated plan (prerequisites, what code is still missing, what stays
  the operator's call).
- **H2 — SIG-FAST-POSTMIG**: MemeTrans-style post-migration survival filter (enter
  only tokens still >=40% of migration price at the +20min marker, with >=20 trades
  in the last 5min). Pivoted (rev. 4) to a **sealed historical discovery+confirmation**
  instead of a live session, since the data already exists on-chain.

Both share the same price-path instrument (`src/opportunity_path_metrics_v0.py` /
`src/opportunity_path_baseline_v0.py`, F2/F3 — causal AMM entry/exit, fixed exit
library, paired baseline) and the same PASS criteria (edge >=10pp, EV net>0 and
PF>1 on the best of 6 fixed exit rules selected on train, both sustained on
holdout AND on a separate fresh confirmation, never retuned after the first look).

## Session history (this handoff's scope)

1. **Autonomous mandate (pre-authorized by the operator before traveling)**
   ran Fases 0-6 of H2's historical discovery block end to end: bias fix in the
   baseline sampler (Fase 0a — baseline must sample ALL classified migrations,
   survivors+non-survivors, never only non-survivors); AMM entry/exit pricing
   wiring (Fase 0b, confirmed F2/F3 already did this, no new code needed);
   Helius-free enumeration with real parity validation against the pilot's
   known ground truth (Fase 1, `h2_enumeration_no_helius_v0.py`); real download +
   sealing with a count-based stopping rule (Fase 2, `h2_block_seal_v0.py`) —
   **202 migrations found, 76 survivors / 126 non-survivors (37.6%), 126 tokens
   sealed in Stage2, 0 system errors, hash-committed before any coverage number**.
2. **Coverage gate (Fase 3) failed** against the fixed 7 criteria:
   `avg_pct_buckets_resolved_stage2 = 44.76%` and
   `avg_pct_decoded_with_reserves_and_fee = 59.41%`, both `< 95%`. Classified
   `INCONCLUSIVE_SYSTEM` (a systems-gate failure before the economic gate, not a
   FAIL/KILL — per `CLAUDE.md`, this does **not** close H2 and does **not** spend
   a hypothesis-registry attempt). Fase 4 never ran. Root-caused both failures
   (direct DB queries, no code change — would have been a forbidden retune) and
   reported them transparently: full writeup in
   `docs/sig-fast-h2-RESULTADO-2026-10-10.md`.
3. **3 reserve tasks completed** while waiting for the operator (self-check only,
   no live network, no money): `benchmarks/sig_fast_v0/live_paper_log_v0.py`
   (stage-3 "log signal, measure outcome, never trade" infra),
   `docs/sig-fast-h1-live-collection-plan-v0-2026-10-10.md` (H1's consolidated
   live-collection runbook, no session started), and expanded self-checks on
   `h2_coverage_gate_v0.py`/`h2_discovery_evaluation_v0.py` (no frozen logic
   touched).
4. **Operator's decision on the `INCONCLUSIVE_SYSTEM` result**: both Fase 3
   failures were **gate implementation bugs**, not wrong thresholds — nothing in
   the frozen protocol (90%/95%/5%/30 limits) should change. Decision documented
   in the DRAFT **before** any recomputation ("Addendum — correção de
   implementação do gate de cobertura"):
   - (a) buckets: the denominator should be buckets with **>=1 successful tx**
     (an empty bucket just carries the previous price forward — already a
     pre-registered rule, never a coverage failure), checked **>=95% in total
     AND in each group (signal/baseline) separately**, pooled (sum of resolved /
     sum of with-tx), never an average of per-token percentages (which would
     divide by zero for a dead baseline token with zero transactions in the
     whole 80-minute grid).
   - (b) reservas+fee: the denominator should exclude tokens that correctly
     **never attempted** to decode a price (non-survivors, by the already-frozen
     survivor rule), counted separately instead of contributing 0%.
   - (c) the only information seen before deciding this was the already-published
     coverage numbers (44.76%/59.41%) — no return/EV/barrier was ever computed.
5. **Hash check**: sha256 of the sealed `discovery.db` confirmed identical to the
   hash `seal_block` wrote *before* the original Fase 3/4 ever ran. Confirmed
   again immediately before the real recomputation below. **MATCH both times —
   the sealed dataset was never altered.**
6. **Code fix implemented and committed BEFORE running against real data**
   (commit `ce2e8ff`): `Stage2SealResult` gained `n_buckets_with_tx` /
   `n_buckets_carried_forward`; `seal_block`'s aggregates became pooled, split by
   group; `h2_coverage_gate_v0.py`'s single bucket criterion became three
   (`pct_stage2_buckets_resolved_total/_signal_group/_baseline_group`, each
   `>=95%`, `None` fail-closed); new module `h2_coverage_recount_v0.py` recovers
   the one piece of data the old `Stage2SealResult` never stored (how many
   buckets had >=1 successful tx) via a **read-only** `getSignaturesForAddress`
   call against the already-sealed pools/windows — no new pool, no new window,
   no new price, no `getTransaction`/decode call for anything already resolved.
   All self-checks (synthetic, no network) passed before running for real.
7. **Real recomputation ran** (commit `16939ac`): 4,133 read-only RPC credits
   against the 126 already-sealed Stage2 pools. Result:

   | Critério | Antes | Depois | Limite |
   |---|---|---|---|
   | reservas+fee | 59.41% | **100.0%** | >=95% ✅ |
   | buckets — total | 44.76% | **95.36%** | >=95% ✅ |
   | buckets — signal group | — | **96.53%** | >=95% ✅ |
   | buckets — baseline group | — | **94.37%** | >=95% ❌ |

   Only 1 of 9 criteria now fails (was 2 of 7, with huge margins before). A
   bounded, read-only diagnostic (268 more credits, `getTransaction` on 6
   unresolved buckets of the worst-offending baseline pool) found the unresolved
   transactions carry no decoded Carbon event at all; their top-level
   instructions include a known Solana swap aggregator (`Prism8hsRo...`) and one
   unidentified program ID. Plausible, **not exhaustively confirmed**, root
   cause: swaps routed through an aggregator via CPI, which the current Carbon
   decoder doesn't decode (it reads the top-level instruction, not
   `innerInstructions`).
8. **Final classification: `INCONCLUSIVE_SYSTEM` again** — per the operator's own
   explicit instruction for this exact branch ("if it still fails: INCONCLUSIVE_SYSTEM
   again, with root cause, without touching any limit, and stop"), **execution
   stopped here**. Fase 4 never ran. No return/EV/barrier was computed at any
   point in this correction. H2 remains open (not closed/KILL — a systems failure
   before the economic gate never spends a registry attempt).

## Guardrails (never violate)

- No frozen economic threshold changed (90%/95%/5%/30 coverage limits; edge
  >=10pp; EV>0/PF>1; the 6 fixed exit rules; Δ=32s for H2, Δ=30s for H1; barrier
  +50%/-30%; W=900s; size 0.15 SOL; terminal 1%/leg).
- No closed FAIL/KILL/INCONCLUSIVE result reopened. H2 stays `INCONCLUSIVE_SYSTEM`,
  not re-decided to anything else.
- The Rust Signal Plane hot path was never touched.
- No live money, no private key, no funded execution, anywhere in this session.
- `discovery.db`/`checkpoint.json` (the sealed Stage1/Stage2 data) were never
  rewritten — only read, hash-verified twice, and supplemented by a separate
  manifest (`artifacts/sig_fast_h2_discovery_v0/bucket_denominator_recount_v0.json`,
  gitignored, local only).

## "Leva pra mim" — do not decide alone, surface to operator

- **Whether to extend the Carbon decoder to cover aggregator-routed swaps
  (`innerInstructions`)** to try to close the remaining 0.63pp gap on the
  baseline-group bucket criterion. This is a decoder-coverage question, not a
  gate-implementation bug — it needs its **own fresh pre-registration** before
  any new attempt against this (or any) sealed block, per the same
  never-retune-after-seeing-the-number discipline just exercised.
- **H1's live collection**: pre-registered and signed off, but no run keys
  assigned, no session started. See
  `docs/sig-fast-h1-live-collection-plan-v0-2026-10-10.md` for the full
  prerequisite checklist (Passo 0, cohort-loader code still to be written, run
  keys, Helius budget check) — none of it is this handoff's call to start.
- Whether H2 is worth pursuing further at all right now, given it's come this
  close twice without ever reaching the economic gate — purely the operator's
  call; nothing here implies an answer either way.

## Immediate next action for whoever continues this

Do not start H1's live collection, do not modify the Carbon decoder to chase the
remaining 0.63pp gap, and do not re-run Fase 3/4 against this sealed block again
without the operator's explicit go-ahead on the open question above. If a new
attempt is authorized, it needs its own pre-registration (same discipline as the
gate-implementation fix in this handoff) before touching any code or data.
