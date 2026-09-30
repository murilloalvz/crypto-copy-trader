# Rejection Filter Prospective Holdout V2 (Independent Replication) — Preregistration DRAFT — 2026-09-30

Mode: PAPER / RESEARCH / PROSPECTIVE / NO LIVE MONEY

**STATUS: DRAFT — NOT FROZEN. Authorizes no acquisition, provider call or run.** Items marked
`[DECISION]` must be fixed by the project owner before freeze (section 15). Once frozen, nothing below
may move.

## 1. Why V2 exists (lineage)

- V1 (`docs/rejection-filter-prospective-holdout-v1-preregistration-2026-09-29.md`, frozen at `6132363`)
  returned `KEEP_REJECTION_FILTER_V1_TAIL_RISK_CANDIDATE`: catastrophic-loss rate 40.8% (REJECTED, 31/76)
  vs 12.1% (KEPT, 8/66), difference 28.7pp, one-sided Fisher p = 0.0001, direction held in 4/4 cohorts,
  no reversal under the worst-case treatment of no-route outcomes. Result:
  `docs/rejection-filter-prospective-holdout-v1-result-2026-09-30.md`.
- The V1 result authorizes only a separately preregistered **independent replication**. V2 is that
  replication. It tests the **same claim with the same rule**; it cannot rescue or modify V1.
- Weaknesses of V1 that V2 is designed to close:
  1. **Single regime.** All four V1 cohorts were collected within about a day (2026-09-29/30).
  2. **Possible dependence.** V1 collection logs show the same token mints recurring across adjacent
     cohorts, while the V1 test treated episodes as independent. The consequence for V1 is not
     computed here (non-gating diagnostic, section 12). V2 makes each token count once.
  3. **Winner's curse.** The V1 point estimate (28.7pp) is likely optimistic; V2 keeps the gate at 15pp.
- Untouched: V48 FAIL/CLOSED; V55 COMPLETE/CLEAN and burned for V68 validation; V68 NOT_EVALUATED;
  Native Participant Quality V1 `KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`; V0 closed
  `INCONCLUSIVE` (its F1 return values remain unread).

## 2. Hypothesis (unchanged claim)

Among episodes the frozen radar/Signal Plane already selects, episodes whose entry price impact exceeds
2pp at a USD 25 route-only BUY show a materially higher 900-second route-only catastrophic-loss rate
(<= -80%) than the others. Claim: tail-risk avoidance only. **No profit or edge claim.** The KEPT group
was not profitable in route-only terms in V1 (PF 0.46 at 900s); V2 neither tests nor changes that.

## 3. Frozen rule (unchanged from V0/V1)

At `research_decision_as_of`, from the causal entry BUY route quote only:
REJECTED if `abs(provider_price_impact_pct_points) > 2.0`; KEPT if known and `<= 2.0`; UNCLASSIFIED if
missing/non-finite (never zero-filled). Hard exclusion (precondition, not tested): mint or freeze
authority present. Label: 900s route-only return, AVAILABLE, non-executable, valid causal clocks and
collected on time (`observed_at - target_at <= 60s`); catastrophic = return <= -80%.

## 4. Independence design (what is new vs V1)

1. **Different days.** No V2 cohort may start on 2026-09-29 or 2026-09-30 (UTC). Valid cohorts must span
   at least two distinct UTC calendar days, with at most three valid cohorts on any one day
   `[DECISION: >= 2 days, <= 3 per day]`. Time of day is reported, not gated.
2. **Each token counts once.** Across the whole V2 study, only the first episode per `token_mint` (by
   `research_decision_as_of`, ties by `episode_key`) enters the gates. Later episodes of the same token
   are counted and reported as `REPEAT`, never analyzed for the gates.
3. **No tokens seen before.** Any token whose mint appears in any V0 or V1 run key (`rejection-filter-v0-
   20260929-01-F1`, `rejection-filter-v1-20260929-01-G1..G6`) is excluded from the gates and reported as
   `SEEN_IN_PRIOR_STUDY`.
4. **Five valid cohorts** `H1..H5`, with two pre-reserved replacements `H6`, `H7` for technically
   DEGRADED cohorts only (same criterion as V1: `(TECHNICAL errors at 900s + LATE 900s) / decisions >
   20%`, computed from statuses and timing only). A third degraded cohort ends the study
   `INCONCLUSIVE_REJECTION_FILTER_V2_ACQUISITION`.
5. **Acquisition machinery identical to V1:** on-time label 60s; error taxonomy (429/5xx/timeouts =
   TECHNICAL; HTTP 400 "Failed to get quotes" = STRUCTURAL and never triggers replacement); pre-flight
   before any data is created (protocol hash, Jupiter key, non-public RPC, bootstrap PASS with
   `ended_at` <= 24h, console guard); per cohort 120s acquisition, max 40 episodes, min 30 decisions,
   USD 25, 100 bps, hazard 650 ms, entry 1000 ms, exit 250 ms.

Run keys: `rejection-filter-v2-<base>-H1..H5`, reserves `H6`, `H7`; base
`rejection-filter-v2-<YYYYMMDD>-01` `[DECISION: date at freeze]`.

## 5. Support gates (over VALID cohorts, after token exclusions)

1. Price-impact coverage >= 80% in every valid cohort (before exclusions).
2. Aggregate paired classified + on-time 900s outcomes >= 90.
3. REJECTED >= 15 and KEPT >= 15 paired aggregate; each >= 5 in every valid cohort.
4. Aggregate catastrophic outcomes >= 10.
5. At least two distinct UTC calendar days among valid cohorts; at most three valid cohorts on one day.

Failure: `INCONCLUSIVE_REJECTION_FILTER_V2_SUPPORT`.

## 6. Effect gates (all must pass)

1. `cat(REJECTED) - cat(KEPT) >= 15` percentage points, aggregate (after exclusions).
2. One-sided exact Fisher test, `cat(REJECTED) > cat(KEPT)`, `p < 0.05`. Single primary test; no
   multiplicity correction needed.
3. `cat(REJECTED) > cat(KEPT)` (strictly) in **at least 4 of the 5** valid cohorts
   `[DECISION: 4 of 5; V1 used all 4 of 4]`. Rationale: with about 13-16 pairs per cell, requiring all
   five makes a true effect fail on noise about a third of the time (section 7).
4. KEPT is between 30% and 85% of classified episodes (known impact, no hard exclusion, after token
   exclusions, counted before requiring a 900s outcome).

## 7. Power (simulated: 5 valid cohorts, ~13-16 KEPT and ~15-19 REJECTED pairs per cohort after exclusions)

| True cat rates (KEPT / REJECTED) | all 5 cohorts must agree | >= 4 of 5 agree (chosen) |
|---|---|---|
| 12% / 41% (V1 point estimate) | 0.86 - 0.92 | 0.97 - 0.99 |
| 15% / 35% (20pp) | 0.53 - 0.64 | 0.75 - 0.79 |
| 15% / 30% (15pp) | 0.31 - 0.38 | 0.49 - 0.50 |
| 15% / 15% (no effect) | 0.00 | 0 - 0.01 |

Reading: a false REPLICATED under no effect is ~0-1%. If the true effect is about V1's size, replication
is near-certain; if it shrank to ~20pp it succeeds about three times in four; a ~15pp true effect is
detected about half the time, so a failure would not prove the effect is absent, only that it is not
confirmed at this size. Assumes independence after exclusions and the expected group sizes.

## 8. Verdicts

- All support and effect gates PASS: `REPLICATED_REJECTION_FILTER_V2_TAIL_RISK`. Means: the exact rule has
  passed two independent prospective tests on tail-risk avoidance. It authorizes (a) adopting the filter
  as a documented **research precondition** in paper pipelines, and (b) a separately preregistered study
  of a *selection* hypothesis conditional on KEPT. It is not edge, not a TAKE/SKIP release, no funded BUY,
  no landing/fill, no shadow, no live money.
- Support PASS, any effect gate FAIL: `NOT_REPLICATED_REJECTION_FILTER_V2` — the V1 KEEP is not
  confirmed; the exact rule closes as a candidate; V1's recorded result stands as recorded.
- Support or acquisition insufficiency: `INCONCLUSIVE_REJECTION_FILTER_V2_...` with the exact reason.

## 9. Analysis rules

Refuse any partial or interim run: requires five VALID cohorts with PASS acquisition reports carrying
the frozen protocol hash. Cohort validity is read from the reports and never re-adjudicated; no return
value is used to decide degradation, replacement, exclusion or day grouping. Token exclusions follow
section 4.2-4.3 mechanically.

## 10. Descriptive, non-gating (mandatory)

Per cohort and per UTC day: counts, coverage, exclusions (`REPEAT`, `SEEN_IN_PRIOR_STUDY`), catastrophic
rates with exact 95% CIs; missingness tables per group (AVAILABLE_ON_TIME, LATE, TECHNICAL, STRUCTURAL);
worst-case sensitivity counting STRUCTURAL as catastrophic (report verbatim if the direction reverses);
winner retention (900s return >= +100%); 300/900s return distributions of KEPT vs REJECTED (median,
mean-without-best, profit factor, largest-winner share); a pooled V1+V2 estimate labelled descriptive.
Any bankroll illustration uses fixed horizons only and is labelled "route-only, descriptive,
PAPER/RESEARCH/READ-ONLY - not realized P&L nor validated edge".

## 11. Out of scope (deliberate)

Exit policy (TP/SL) and position sizing: not evaluable from checkpoints and reserved for a later protocol
after entry-side evidence. Profit expectancy of KEPT: not tested here. Other notionals: the 2pp cap is
defined at USD 25; a size-scaling study would be a different protocol. Selection features within KEPT: a
separate hypothesis, never tuned on V1 or V2 rows used to validate it.

## 12. Pre-freeze diagnostics (offline, read-only, non-gating)

Before freezing, the owner may run a read-only script (to be built) that reports, from V1 rows, the
count of distinct tokens vs episodes per cohort and across cohorts (outcome-blind), and V1 with token
deduplication as a descriptive robustness check. Its output cannot change any V2 gate; it exists to say
how much V1's independence assumption mattered.

## 13. Forbidden after freeze

- moving the 2pp cap, -80%, 60s cap, 20% degradation threshold, alpha, the 15pp gate or the 4-of-5 rule;
  adding or removing rules; flipping direction; subgroup or feature rescue;
- deciding degradation, replacement, exclusion or day grouping from returns, group sizes or catastrophic
  counts; dropping or reordering cohorts after seeing results;
- collecting on 2026-09-29/30; reusing any V0/V1 or burned/consumed rows; switching the primary horizon;
- missing/late/technical/no-route converted to a value in the primary analysis;
- describing REPLICATED as edge, or wiring it into live entry score, shadow or funded execution.

## 14. Human workflow note

The rule is a proxy for what a human SKIP would look like; the real human TAKE/SKIP workflow does not
exist yet. This protocol neither implements nor validates it.

## 15. Open decisions and freeze procedure

Open: (1) 5 valid cohorts; (2) 4-of-5 direction rule; (3) >= 2 days and <= 3 per day; (4) token
exclusion rules 4.2-4.3; (5) two replacements (`H6`, `H7`); (6) base run key date.

To build and test offline before freeze (no provider calls): V2 runner (V1 machinery plus 5 required
cohorts, replacements H6/H7, UTC start-date recording and day rules) and V2 analysis (token exclusions,
day grouping, 4-of-5 rule, V2 verdict names, per-day tables), plus the section 12 diagnostic. V1
modules stay untouched as provenance; V2 modules are new files.

Freeze sequence: (a) the owner commits this file renamed to
`docs/rejection-filter-prospective-holdout-v2-replication-preregistration-2026-09-30.md`, DRAFT wording
removed, decisions resolved, nothing else changed, in a commit of its own; (b) in a following commit the
file's SHA-256 (CRLF-normalized) is recorded in the V2 runner and run notes; (c) only then may the first
V2 acquisition run. Any later edit voids the preregistration for affected runs. This draft releases no
acquisition, funded BUY, shadow execution or live money.
