# Rejection Filter V3 — USD 10 Order Size + Buy-Pressure Selection within KEPT — Preregistration — 2026-10-02

Mode: PAPER / RESEARCH / PROSPECTIVE / NO LIVE MONEY

**STATUS: FROZEN by the project owner on 2026-10-02. Nothing below may move.**

## 1. Why V3 exists (lineage)

- The impact filter (`abs(price impact) > 2pp` at a USD 25 route-only BUY) replicated in V1 (`KEEP`) and V2
  (`REPLICATED`): 900s catastrophic-loss rate ~10% KEPT vs ~45% REJECTED. It is a tail-risk filter, **not** an entry
  edge: pooled deduplicated KEPT at 900s has median -0.4%, mean-without-best -9.8%, profit factor 0.72.
- Descriptive analysis on the consumed rows (`docs/kept-group-selection-discovery-v0-result-2026-10-02.md`, order-size
  scaling analysis) found: (a) ~30% of surfaced episodes have impact > 25pp and lose almost everything, so most of the
  filter's separation comes from that cliff; (b) a buy-pressure feature cluster (`flow60_wallet_direction_balance`
  rho +0.28, consistent signs in V1, V2 and the 300s return) that did NOT pass the preregistered Bonferroni
  criterion; (c) every V1/V2 order was USD 25, but the owner's bankroll implies orders of about USD 10-30.
- V3 therefore runs fresh cohorts at **USD 10** and preregisters two claims. It cannot modify, rescue or reinterpret
  V0/V1/V2. V48 FAIL/CLOSED; V55 burned for V68 validation; V68 NOT_EVALUATED; Native Participant Quality V1 `KILL`:
  untouched. Claim P2 is a NEW hypothesis (higher buy-side wallet balance is favourable). It points the opposite way to
  the burned V55 finding and is not a V68 variant: no V68 feature, bin, direction or horizon changes.

## 2. Claims (two primary, evaluated separately)

- **P1 (filter at USD 10).** At a USD 10 route-only BUY, episodes with `abs(price impact) > 2.0pp` show a materially
  higher 900s catastrophic-loss rate (<= -80%) than the others.
- **P2 (selection within KEPT).** Among P1-KEPT episodes, a higher `flow60_wallet_direction_balance` is associated with
  better 900s route-only returns: positive rank association AND better group median, profit factor and
  mean-without-best above vs below the cutoff (section 7).

Each claim gets its own verdict at alpha = 0.025 (Bonferroni over the two claims). No profit or edge claim follows
from either verdict. Route-only return != realized P&L.

## 3. Frozen definitions

- Order size: `research_notional_usd = 10.0`. Everything else in the acquisition is identical to V2 (section 4).
- Rule (P1): at `research_decision_as_of`, from the causal entry BUY route quote at USD 10 only: REJECTED if
  `abs(provider_price_impact_pct_points) > 2.0`; KEPT if known and `<= 2.0`; UNCLASSIFIED if missing/non-finite (never
  zero-filled). Hard exclusion (not tested): mint or freeze authority present.
- Label: 900s route-only return, AVAILABLE, non-executable, valid causal clocks and collected on time
  (`observed_at - target_at <= 60s`); catastrophic = <= -80%. Missing/late/technical/no-route are never converted.
- Feature (P2): `flow60_wallet_direction_balance` exactly as built by the existing V55 causal dataset (unique buy
  wallets minus unique sell wallets in the 60s window at the decision clock). No other feature is tested for any gate.

## 4. Acquisition (V2 machinery; only the order size changes)

Per cohort: 120s acquisition, max 40 selected episodes, min 30 decisions, USD **10** BUY notional, 100 bps slippage,
hazard pacing 650 ms, entry pacing 1000 ms, exit pacing 250 ms, exact 300/900/3600 schedule accounting, 300/900
collector must complete. On-time label 60s; error taxonomy (429/5xx/timeouts TECHNICAL; HTTP 400 "Failed to get
quotes" STRUCTURAL); cohort DEGRADED iff `(TECHNICAL at 900s + LATE) / decisions > 20%`, computed from statuses and
timing only. Pre-flight before any data is created: protocol hash, Jupiter key, non-public RPC, bootstrap PASS with
`ended_at` <= 24h, console guard, V3 day rules.

- Cohorts: ten VALID cohorts `T1..T10`, plus three reserved replacements `T11..T13` for DEGRADED cohorts only; a
  fourth degraded cohort ends the study `INCONCLUSIVE_..._ACQUISITION`.
- Run keys: `rejection-filter-v3-<base>-T1..T13`, base `rejection-filter-v3-<YYYYMMDD>-01` (base date 20261002).
- Independence: valid cohorts span at least three distinct UTC days; at most three cohorts may START on one UTC day.
  Each token counts once across V3 (first episode by decision time); any token
  present in any V0, V1 or V2 run key is excluded (`SEEN_IN_PRIOR_STUDY`). Exclusions are reported, never silent.
- A pre-freeze smoke caveat: quotes at USD 10 have not been collected before. A systematic quote failure at this size
  would show as DEGRADED cohorts and, after the allowed replacements, an `INCONCLUSIVE_..._ACQUISITION` result.

## 5. Support gates (over VALID cohorts after token exclusions)

1. Price-impact coverage >= 80% in every valid cohort (measured before exclusions).
2. P1: paired classified + on-time 900s outcomes >= 120; REJECTED >= 15 and KEPT >= 15; catastrophic outcomes >= 10.
3. P1 direction evaluable in at least 8 valid cohorts (a cohort is evaluable if both groups have >= 3 paired outcomes).
4. P2: KEPT paired outcomes >= 120 with `flow60_wallet_direction_balance` known in >= 80% of them (target >= 150).
5. At least three UTC days among valid cohorts; at most three valid cohorts on one day.

Failure of a claim's gates gives `INCONCLUSIVE_..._SUPPORT` for that claim only.

## 6. P1 effect gates (all required)

1. `cat(REJECTED) - cat(KEPT) >= 15` percentage points, aggregate.
2. One-sided exact Fisher test `cat(REJECTED) > cat(KEPT)`, `p < 0.025`.
3. `cat(REJECTED) > cat(KEPT)` strictly in at least 70% of the evaluable cohorts.
4. KEPT is 30-85% of classified episodes (known impact, no hard exclusion, after token exclusions, counted before
   requiring a 900s outcome). Projected KEPT share at USD 10 is ~57% (linear scaling; an assumption this study checks).

## 7. P2 effect gates (all required; KEPT paired rows, one episode per token)

Group split: HIGH if the feature is above the **median of the feature over the analysis-eligible KEPT episodes**
(computed from feature values only, before any outcome is read); LOW otherwise (ties go to LOW). No cutoff search.

1. One-sided Spearman association between the feature and the 900s return, `rho > 0`, permutation `p < 0.025`
   (20,000 permutations, fixed seed).
2. HIGH group median 900s return > LOW group median.
3. HIGH group profit factor > LOW group profit factor.
4. HIGH group mean-without-best > LOW group mean-without-best.
5. Sign consistency: `rho > 0` in both halves of the study split by cohort start time (first half of valid cohorts vs
   second half).

## 8. Power (simulated)

- **P1:** with ~15 KEPT and ~13 REJECTED pairs per cohort over ten cohorts: power 1.00 for 10% vs 45% catastrophic,
  0.99 for 12% vs 40%, 0.84 for 15% vs 35%, 0.48 for 15% vs 30%, 0.00 for no effect.
- **P2** (n = KEPT paired; true rank correlation rho; the simulation uses a KEPT-like marginal with ~12%
  catastrophic outcomes and rare large winners and assumes a monotone relation, so it is optimistic if the
  relation only exists in the tails): n=120: 0.33 / 0.55 / 0.75 / 0.89 at rho 0.15 / 0.20 / 0.25 / 0.30;
  **n=150: 0.42 / 0.62 / 0.84 / 0.95**; n=200: 0.51 / 0.76 / 0.93 / 0.98; false positive about 2-3% at rho 0.
- The observed 0.27 in the discovery sample is likely inflated by selecting the best of a feature cluster; a true
  effect near 0.20 would be detected about 60% of the time at n=150, so a non-confirmation would not prove absence.
- Expected yield: ~16 KEPT pairs per cohort before token exclusions (40 episodes x projected 57% KEPT x ~70% usable),
  fewer after exclusions of tokens seen in V0-V2 and repeats. Ten valid cohorts target ~150 KEPT pairs; the study
  may end `INCONCLUSIVE_..._SUPPORT` for P2 if exclusions cut yield below 120.

## 9. Verdicts

- **P1:** all support + effect gates: `CONFIRMED_REJECTION_FILTER_AT_USD10`; support PASS and any effect gate FAIL:
  `NOT_CONFIRMED_REJECTION_FILTER_AT_USD10`; otherwise `INCONCLUSIVE_REJECTION_FILTER_V3_P1_...` with the reason.
- **P2:** all support + effect gates: `KEEP_BUY_PRESSURE_SELECTION_CANDIDATE_V3`; support PASS and any gate FAIL:
  `KILL_BUY_PRESSURE_SELECTION_CANDIDATE_V3` (closed, no retune); otherwise `INCONCLUSIVE_..._P2_...`.
- P2 is evaluated regardless of P1; the report states P1's result next to it. A P2 KEEP is **not edge** and
  authorizes only a separately preregistered independent replication on other days plus, after that, an exit-policy
  study using the V58 route-path geometry. It does not authorize TAKE/SKIP, funded BUY, landing/fill, shadow
  execution or live money.

## 10. Non-gating reporting (mandatory)

Per cohort and UTC day: counts, coverage, exclusions; catastrophic rates with exact 95% CIs; missingness per group
(AVAILABLE_ON_TIME, LATE, TECHNICAL, STRUCTURAL) and the worst-case sensitivity counting STRUCTURAL as catastrophic;
catastrophic rate and median by impact bin at USD 10; observed KEPT share vs the 57% projection; 300/900s
distributions for the P2 groups (median, mean-without-best, profit factor, largest-winner share); the other four
buy-pressure features' rho (descriptive, no gate); a descriptive comparison with the USD 25 results (confounded by
time, no claim). Any bankroll illustration uses fixed horizons only and is labelled "route-only, descriptive,
PAPER/RESEARCH/READ-ONLY - not realized P&L nor validated edge".

## 11. Out of scope (deliberate)

Exit policy (TP/SL), position sizing, other order sizes, other features or cutoffs, execution realism (fees,
landing, fill), any live-money step. Not evaluable here and reserved for later protocols.

## 12. Analysis rules

No partial or interim analysis: requires ten VALID cohorts with PASS acquisition reports carrying the frozen protocol
hash. Cohort validity is read from the reports and never re-adjudicated; no return value is used to decide
degradation, replacement, exclusion, day grouping or the P2 cutoff.

## 13. Forbidden after freeze

Moving the 2pp cap, the order size, -80%, the 60s cap, the 20% degradation threshold, alphas, the 15pp gate, the 70%
direction rule, the feature, its direction or the median-split rule; adding or removing rules, features or claims;
flipping direction; subgroup or feature rescue; testing any other feature for a gate; deciding degradation,
replacement, exclusion or day grouping from returns or group sizes; reusing any V0/V1/V2 row for validation; switching
the primary horizon; converting missing/late/technical/no-route into values; describing a verdict as edge; wiring
anything into a live entry score, shadow or funded execution; calling P2 a V68 variant.

## 14. Human workflow note

The impact rule is a proxy for what a human SKIP would look like at about USD 10 per entry. The real human TAKE/SKIP
workflow does not exist yet; this protocol neither implements nor validates it.

## 15. Operational notes

- The V3 runner and analysis will be NEW files (V0-V2 modules stay untouched as provenance), with the V2 machinery
  plus the order size, ten cohorts, three replacements, the P2 analysis and per-claim verdicts.
- Do not run any collection while another process uses the database, Jupiter or the Helius RPC.
- Collection takes about 25 minutes per cohort (a 900s outcome horizon plus the acquisition window); ten cohorts are
  roughly four hours spread over at least three UTC days.

## 16. Resolved decisions and freeze procedure

Resolved by the project owner: (1) USD 10 as the single arm; (2) ten valid cohorts plus three replacements;
(3) alpha 0.025 per claim; (4) P1 direction in >= 70% of evaluable cohorts; (5) P2 feature
`flow60_wallet_direction_balance`, positive direction, study-median cutoff computed outcome-blind; (6) >= 3 UTC days,
<= 3 per day; (7) exclusion of tokens seen in V0-V2; (8) base run key date 20261002.

The V3 runner, analysis and run helper were built and tested offline before freeze (no provider calls). Freeze
sequence: (a) this file is committed under its preregistration name in its own commit; (b) in a following commit its
SHA-256 (CRLF-normalized) is recorded in the V3 runner and run notes; (c) only then may the first V3 acquisition run.
Any later edit voids the preregistration for affected runs. This protocol releases no funded BUY, shadow execution or
live money.
