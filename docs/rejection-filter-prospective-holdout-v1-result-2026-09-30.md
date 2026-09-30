# Rejection Filter Prospective Holdout V1 — Result — 2026-09-30

Mode: PAPER / RESEARCH / PROSPECTIVE / NO LIVE MONEY

## Final classification

`KEEP_REJECTION_FILTER_V1_TAIL_RISK_CANDIDATE`

Protocol (frozen at `6132363e65143d6e308548240a81807f9b310067`, SHA-256
`b2fc2ae9861cbcf5bfdef26cbc1bafe72e71250cf9127ca6f641d479ff31a568`):
`docs/rejection-filter-prospective-holdout-v1-preregistration-2026-09-29.md`.
Analysis report hash lineage: the report records the same protocol hash; `scientific_thresholds_modified: false`.

Valid cohorts: `rejection-filter-v1-20260929-01-G1..G4` (no replacements used). Every cohort had a
technical-unusable share of 0.0-2.6% (limit 20%). Integrity counters all zero.

## Frozen rule tested

REJECTED if `abs(entry price impact) > 2.0pp` at a USD 25 route-only BUY; KEPT otherwise; label = 900s
route-only return, on-time (<= 60s late) AVAILABLE only; catastrophic = return <= -80%. Missing,
late, technical and no-route outcomes were never converted to values.

## Support (all gates passed)

- Episodes 159 (G1 39, G2-G4 40 each); impact coverage 100% in every cohort; no authority exclusions.
- Paired 900s outcomes: 142 (KEPT 66, REJECTED 76); KEPT >= 5 and REJECTED >= 5 in every cohort.
- Catastrophic outcomes: 39 (>= 10 required).
- KEPT share of classified episodes: 44.7% (band 30-85%).

## Effect (all gates passed)

| Group | n | Catastrophic | Rate | Exact 95% CI |
|---|---|---|---|---|
| KEPT | 66 | 8 | 12.1% | 5.4% - 22.5% |
| REJECTED | 76 | 31 | 40.8% | 29.6% - 52.7% |

Difference 28.7 percentage points (>= 15 required); one-sided exact Fisher p = 0.000101 (< 0.05,
single primary test). REJECTED > KEPT in every cohort:

| Cohort | KEPT | REJECTED |
|---|---|---|
| G1 | 2/15 = 13.3% | 6/20 = 30.0% |
| G2 | 4/21 = 19.0% | 10/15 = 66.7% |
| G3 | 1/14 = 7.1% | 7/22 = 31.8% |
| G4 | 1/16 = 6.3% | 8/19 = 42.1% |

Per-cohort intervals are wide (n = 14-22 per cell); the consistency of direction, not any single
cohort, carries the result.

## Non-gating reporting required by the protocol

- Missingness at 900s: LATE 0. TECHNICAL 3 (KEPT 2, REJECTED 1). STRUCTURAL no-route: KEPT 3 of 71
  episodes (4.2%), REJECTED 11 of 88 (12.5%). No-route outcomes are more frequent in REJECTED.
- Worst-case sensitivity (no-route 900s counted as catastrophic): KEPT 15.9%, REJECTED 48.3%.
  `direction_reverses_under_worst_case: false`.
- Winner retention (900s return >= +100%): KEPT 1, REJECTED 2 of 142 paired outcomes. Large winners
  are too rare here (3) for any retention claim.
- Fixed-horizon 900s route-only distribution: KEPT median -0.06%, mean-without-best -12.3%, profit
  factor 0.46, largest winner 22.8% of gross profit. REJECTED median -58.5%, mean-without-best
  -48.1%, profit factor 0.31, largest winner 57.1% of gross profit. 300s: KEPT PF 0.21, REJECTED PF 0.19.

## Interpretation

Price impact above 2pp at USD 25 identified, prospectively and on fresh data, a group with a much higher
rate of catastrophic route-only loss. The result held in all four cohorts and did not reverse under the
worst-case treatment of no-route outcomes (which would, if anything, widen the gap since no-route is
commoner in REJECTED).

What it does NOT show:

- **No positive expectancy.** The KEPT group is not profitable in route-only terms (PF 0.46 at 900s,
  mean without the best outcome -12%). The rule removes the worst tail; it does not create an entry edge.
- **Likely a liquidity/execution-cost effect.** At a fixed USD 25 notional, impact above 2pp marks
  shallow pools, where the round trip (entry impact plus exit impact) is mechanically expensive. This is
  a real cost for a trader of that size but it is not evidence that the market is predictable. The
  effect is notional-dependent; it may shrink at smaller sizes.
- **One short collection window.** All cohorts were collected within roughly a day (2026-09-29/30), a
  single market regime.
- Route-only return != realized P&L; no fees beyond route quote, no landing/fill, no slippage model.

## Disposition

- `KEEP` promotes this exact rule only to an **independent replication candidate**, to be
  separately preregistered on fresh data collected on different days. It is not mature edge.
- Not authorized: TAKE/SKIP release, funded BUY, landing/fill, shadow execution, live money, wiring
  into any live entry score, exit-policy selection, or any change to the frozen rule (2pp cap, -80%,
  900s, 60s lateness cap).
- The consumed V1 rows may be used for descriptive diagnostics and for generating a *new* hypothesis,
  never to validate a rule derived from them. V0 F1 return values remain unread.
- V48 FAIL/CLOSED; V55 COMPLETE/CLEAN and burned for V68 validation; V68 NOT_EVALUATED; Native
  Participant Quality V1 `KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`: untouched.
