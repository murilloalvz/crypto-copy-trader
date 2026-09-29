# Rejection Filter Prospective Holdout V1 — Preregistration — 2026-09-29

Mode: PAPER / RESEARCH / PROSPECTIVE / NO LIVE MONEY

**STATUS: FROZEN by this commit. Nothing below may move.** Freezing authorizes no provider call and
no funded action by itself; acquisition starts only when the project owner runs it (section 16).

## 1. Why V1 exists (lineage)

- V0 (`docs/rejection-filter-prospective-holdout-v0-preregistration-2026-09-29.md`, frozen at
  `7384c94`) tested this same hypothesis. Its F1 cohort was technically degraded: a console QuickEdit
  freeze stalled the collector ~17 minutes, the overdue backlog then hit the Jupiter gateway limit
  (27 x HTTP 429), and 9 of the 10 available 900s quotes were ~1000s late. F1 has only 4 KEPT paired
  outcomes against a minimum of 5, so V0 cannot end other than
  `INCONCLUSIVE_REJECTION_FILTER_V0_SUPPORT`. V0 is closed as INCONCLUSIVE; no verdict exists.
- V0 had no lateness cap, no availability floor and no replacement rule for a technically degraded
  cohort. V1 adds those **acquisition-quality** mechanisms and changes nothing about the hypothesis,
  the rule, the label, the catastrophic threshold or the effect gates.
- No V0 return value was ever read. V0 F1 rows are consumed and are never used in V1.
- V48 FAIL/CLOSED; V55 COMPLETE/CLEAN and burned for V68 validation; V68 NOT_EVALUATED; Native
  Participant Quality V1 `KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`: all untouched.

## 2. Hypothesis (unchanged from V0)

Among episodes the frozen radar/Signal Plane already selects, an outcome-blind pre-entry rejection
rule classifies a REJECTED group whose 900-second route-only catastrophic-loss rate (<= -80%) is
materially higher than the KEPT group's. Claim: tail-risk avoidance only, not profit
(route-only return != realized P&L). KEPT may still have profit factor < 1.

## 3. Frozen rule (unchanged from V0)

At `research_decision_as_of`, from the causal entry BUY route quote only:

- REJECTED: `abs(provider_price_impact_pct_points) > 2.0`.
- KEPT: impact known and `abs(impact) <= 2.0`.
- UNCLASSIFIED: impact missing or non-finite; never zero-filled or imputed.
- Hard exclusion (precondition, not tested): mint or freeze authority present per hazard evidence.
  Unknown authority is not excluded.

Out of protocol: liquidity (no persisted route quote carries it), Participant Quality, flow features,
any exit policy.

## 4. What changed vs V0 (acquisition quality only)

1. **On-time label.** A 900s outcome is a valid label only if `observed_at - target_at <= 60` seconds
   (60s; V0/PQ 300s lateness p95 was 1s). A later quote stays in coverage accounting as
   `LATE`, is unavailable for pairing and is never converted to zero, loss or an estimate.
2. **Error taxonomy.** From `error_type/error_message` only, never from returns:
   - TECHNICAL: HTTP 429, HTTP 5xx, timeouts, transport errors, any collector stall.
   - STRUCTURAL: HTTP 400 "Failed to get quotes" (no route), a legitimate missing outcome that is
     reported but never triggers replacement.
3. **Cohort technical validity.** A cohort is DEGRADED iff
   `(TECHNICAL errors at 900s + LATE 900s outcomes) / decisions > 20%` (20%).
   (V0 F1 would have scored 36/39 = 92%.) Validity is computed by the runner from statuses and timing
   only, before any return value is read, and written to the acquisition report.
4. **Replacement.** A DEGRADED cohort is excluded from analysis (its rows stay in the database,
   unread). At most two replacements are pre-reserved: `G5`, `G6`. The analysis needs four VALID
   cohorts; a fifth degraded cohort ends the study `INCONCLUSIVE_REJECTION_FILTER_V1_ACQUISITION`.
   Replacement is decided only by the technical criterion above, never by group sizes or outcomes.
5. **Pre-flight (fail-closed, before any provider call).** The runner requires: protocol hash match;
   `JUPITER_API_KEY` set; RPC host not the public default; a bootstrap report with
   `PASS_PUMPSWAP_IDENTITY_BOOTSTRAP_V0`, `valid_bootstrap: true` and `ended_at` within 24 hours
   (24h); QuickEdit disabled and sleep blocked (the runner's console guard); previous
   cohort PASS in order. Any failure aborts before creating data, so the run key is not consumed.
6. **Mandatory non-gating missingness reporting.** Per group (KEPT/REJECTED) and cohort: decisions,
   900s attempted, AVAILABLE on time, LATE, TECHNICAL error, STRUCTURAL no-route. Plus a worst-case
   sensitivity that counts STRUCTURAL no-route 900s outcomes as catastrophic. Rationale: a token with
   no sell route at 900s is plausibly a dead token, so unavailability may be informative and
   differential by group. The primary analysis still never converts missing to loss. If the primary
   passes but the sensitivity reverses the direction, the report must say so verbatim.

## 5. Fresh acquisition

Fresh untouched cohorts only. Run keys: `rejection-filter-v1-<base>-G1..G4`, reserves `G5`, `G6`,
base `rejection-filter-v1-20260929-01` (date fixed at freeze).

Per cohort, unchanged from V0/PQ: 120s acquisition; max 40 selected episodes; min 30 route-research
decisions; route-only BUY notional USD 25; slippage 100 bps; hazard pacing 650 ms; entry pacing
1000 ms; exit pacing 250 ms; exact 300/900/3600 schedule accounting; 300/900 forward collector must
complete. The 3600s outcomes are scheduled but not collected here and are not part of any gate.

## 6. Primary label

`100 * (900s SELL route quote price / causal entry BUY route quote price - 1)`, only AVAILABLE,
non-executable, valid causal clocks **and on time (section 4.1)**. Catastrophic: label <= -80%.

## 7. Support gates (before any KEEP/KILL), over VALID cohorts

1. Price-impact coverage >= 80% in every valid cohort.
2. Aggregate paired classified + on-time 900s outcomes >= 90.
3. REJECTED >= 15 and KEPT >= 15 paired aggregate; each >= 5 in every valid cohort.
4. Aggregate catastrophic outcomes >= 10.

Failure: `INCONCLUSIVE_REJECTION_FILTER_V1_SUPPORT`.

## 8. Effect gates (all must pass; unchanged from V0)

1. `cat(REJECTED) - cat(KEPT) >= 15` percentage points, aggregate.
2. One-sided exact Fisher test `cat(REJECTED) > cat(KEPT)`, `p < 0.05` (single primary test).
3. `cat(REJECTED) > cat(KEPT)` in every valid cohort.
4. KEPT is between 30% and 85% of classified episodes (known impact, no hard exclusion, counted before
   requiring a 900s outcome; owner-confirmed reading).

## 9. Power (simulated, unchanged assumptions)

With four valid cohorts (~27 usable pairs each, ~58 REJECTED / ~65 KEPT): false KEEP under no effect
~2%; detection ~100% for 45% vs 10%, ~76% for 35% vs 15%, ~15% for 25% vs 18%. A KILL or INCONCLUSIVE
does not prove absence of a small effect. The 20% technical threshold is expected to leave >= 4
valid cohorts in normal operation.

## 10. Verdicts

- All support and effect gates PASS: `KEEP_REJECTION_FILTER_V1_TAIL_RISK_CANDIDATE`. Authorizes only a
  separately preregistered independent replication. Not edge, not a TAKE/SKIP release, no funded BUY.
- Support PASS, any effect gate FAIL: `KILL_REJECTION_FILTER_V1_TAIL_RISK_CANDIDATE` (closed).
- Support or acquisition insufficiency: `INCONCLUSIVE_REJECTION_FILTER_V1_...` with exact reason.

## 11. Descriptive, non-gating

Exact 95% CIs on catastrophic rates; winner retention (episodes with 900s return >= +100% by group);
fixed-horizon (300/900) return distributions of KEPT vs REJECTED; the section 4.6 missingness tables
and worst-case sensitivity. Any bankroll illustration uses fixed horizons only and is labelled
"route-only, descriptive, PAPER/RESEARCH/READ-ONLY - not realized P&L nor validated edge".

## 12. Exit policy: out of scope

Unchanged from V0: TP/SL cannot be honestly evaluated from checkpoints (threshold-price fills are
excluded by the market-first exit contract); it needs the causal route path of the V58 geometry
protocol and a separate protocol after entry-side evidence exists.

## 13. Analysis rules

- The analysis refuses any partial or interim run: it requires four VALID cohorts with PASS
  acquisition reports carrying the frozen protocol hash. No optional stopping.
- Cohort validity is read from the acquisition report; the analysis never re-adjudicates it and never
  looks at returns to decide it.
- Primary analysis uses on-time AVAILABLE 900s outcomes only.

## 14. Forbidden after freeze

- moving the 2pp cap, the -80% threshold, the 60s lateness cap, the 20% technical threshold, alpha or
  any gate; adding or removing rules; flipping direction; subgroup or feature rescue;
- deciding degradation or replacement using returns, group sizes or catastrophic counts;
- reading or analyzing V0 F1 return values before the V1 verdict (same hypothesis, so it would be
  peeking); reusing any V0 or burned/consumed rows;
- switching the primary horizon; missing = zero/KEPT; provider error or LATE converted to a loss or
  estimate in the primary analysis;
- describing KEEP as edge or wiring it into live entry score, shadow or funded execution.

## 15. Human workflow note

The rule is a proxy for what a human SKIP would look like. The real human TAKE/SKIP workflow does not
exist yet; this protocol neither implements nor validates it.

## 16. Frozen decisions and freeze procedure

Closed by the owner at freeze: lateness cap 60s; technical-degradation threshold 20%; bootstrap
freshness 24h; base run key `rejection-filter-v1-20260929-01`; at most two replacements (`G5`, `G6`).

Runner `rejection_filter_holdout_v1_collect.py` and analysis `rejection_filter_holdout_v1_analyze.py`
implement this protocol (tested offline on synthetic data). Both refuse to run until the SHA-256 of this
file is recorded in the runner. Sequence: (a) this file is committed alone as the freeze commit;
(b) in a following commit the file's SHA-256 (CRLF-normalized) is set as `PROTOCOL_SHA256` in the
runner and recorded in the V1 run notes; (c) only then may the first V1 acquisition run. Any later
edit of this file voids the preregistration for affected runs. Freezing releases no acquisition,
funded BUY, shadow execution or live money.
