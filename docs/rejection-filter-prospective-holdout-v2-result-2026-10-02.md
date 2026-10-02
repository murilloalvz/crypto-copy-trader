# Rejection Filter Prospective Holdout V2 (Independent Replication) — Result — 2026-10-02

Mode: PAPER / RESEARCH / PROSPECTIVE / NO LIVE MONEY

## Final classification

`REPLICATED_REJECTION_FILTER_V2_TAIL_RISK`

Protocol (frozen at `6e1c81457f1098cb69d99d08ec6c9f3e686152d5`, SHA-256
`c775a1a38d056ab356f4128f8c6fddf5b61940ebf7f8bca7369f5482dba905a3`):
`docs/rejection-filter-prospective-holdout-v2-replication-preregistration-2026-09-30.md`.
The analysis report records the same protocol hash; `scientific_thresholds_modified: false`.

Valid cohorts: `rejection-filter-v2-20260930-01-H1..H5` (no replacements). Started on UTC days 2026-10-01
(H1-H3) and 2026-10-02 (H4-H5); none on the V1 collection days. Acquisition technical-unusable share was
0.0-5.0% per cohort (limit 20%). Integrity counters all zero. Primary RPC for V2: `mainnet.helius-rpc.com`
(disclosed in the run notes; V1 had used the RPC configured then).

## Support (all passed)

Episodes 199; after token exclusions 166 (31 `REPEAT`, 2 `SEEN_IN_PRIOR_STUDY`). Impact coverage 100% in
every cohort. Paired 900s outcomes 146 (KEPT 53, REJECTED 93); each >= 5 in every cohort; catastrophic
outcomes 50; two UTC days, at most three cohorts per day.

## Effect (all passed)

| Group | n | Catastrophic (<= -80%) | Rate | Exact 95% CI |
|---|---|---|---|---|
| KEPT | 53 | 5 | 9.4% | 3.1% - 20.7% |
| REJECTED | 93 | 45 | 48.4% | 37.9% - 59.0% |

Difference 39.0 percentage points (>= 15 required); one-sided exact Fisher p = 6.4e-7 (single primary test);
REJECTED > KEPT in 5 of 5 cohorts (>= 4 required); KEPT share of classified episodes 33.1% (band 30-85%,
so close to its lower bound).

| Cohort | UTC day | KEPT | REJECTED |
|---|---|---|---|
| H1 | 2026-10-01 | 2/15 = 13.3% | 12/22 = 54.5% |
| H2 | 2026-10-01 | 1/7 = 14.3% | 3/17 = 17.6% |
| H3 | 2026-10-01 | 0/7 = 0.0% | 12/21 = 57.1% |
| H4 | 2026-10-02 | 2/13 = 15.4% | 11/19 = 57.9% |
| H5 | 2026-10-02 | 0/11 = 0.0% | 7/14 = 50.0% |

Per UTC day: 2026-10-01 KEPT 10.3% (3/29) vs REJECTED 45.0% (27/60); 2026-10-02 KEPT 8.3% (2/24) vs
REJECTED 54.5% (18/33). H2 shows an almost flat contrast (3.3pp) on very small cells (KEPT n=7); the other
four cohorts show 38-58pp.

## Non-gating reporting required by the protocol

- Missingness at 900s: LATE 0. TECHNICAL 4 (KEPT 2, REJECTED 2). STRUCTURAL no-route: KEPT 0 of 55
  episodes, REJECTED 16 of 111 (14.4%).
- Worst-case sensitivity (no-route counted as catastrophic): KEPT 9.4%, REJECTED 56.0%;
  `direction_reverses_under_worst_case: false` (the gap widens).
- Winner retention (900s return >= +100%): KEPT 2 of 53, REJECTED 4 of 93 (3.8% vs 4.3%); winners are rare
  and not concentrated in KEPT.
- Route-only distributions, KEPT: 900s median -0.03%, mean-without-best -7.1%, profit factor 1.02, largest
  winner 35.2% of gross profit; 300s median -0.3%, mean-without-best -1.3%, profit factor 1.31.
  REJECTED: 900s median -68.2%, mean-without-best -49.6%, profit factor 0.30.
- Pooled V1+V2 (descriptive only; token sets disjoint): KEPT 13/119 = 10.9%, REJECTED 76/169 = 45.0%.

## Interpretation

The V1 result replicated on fresh cohorts collected on different UTC days, with each token counted once and
the tests pre-specified: episodes whose entry price impact exceeds 2pp at a USD 25 route-only BUY show a
much higher 900s catastrophic-loss rate (48% vs 9%). The result held in 5 of 5 cohorts and on both days and
did not reverse under the worst-case treatment of no-route outcomes.

What it does NOT show:

- **No demonstrated entry edge.** KEPT is roughly break-even in route-only terms at 900s (profit factor 1.02,
  median about 0%, mean without the best outcome -7%); in V1 it was below 1 (0.46). n=53, and the figures
  rest on a few winners. Route-only return != realized P&L (no fees beyond the route quote, no landing/fill,
  no slippage model).
- **Likely a liquidity/execution-cost effect.** At a fixed USD 25 notional, impact above 2pp marks shallow
  pools whose round trip is mechanically expensive. It is a real cost for that size but not evidence that the
  market is predictable, and it is notional-dependent.
- **Narrow time window.** V1 and V2 cover 2026-09-29 to 2026-10-02: independent days, but consecutive ones and
  one market period. Generalization to other weeks is untested.
- **Weak spots disclosed:** H2 had essentially no contrast on tiny cells, and the KEPT share (33.1%) sat close to
  the lower non-triviality bound after token exclusions.

## Disposition

- The exact rule (impact-cap at 2pp, USD 25 notional, 900s, -80%) has passed two independent prospective
  tests for tail-risk avoidance.
- Authorized by this result: (a) adopting the filter as a documented **research precondition** in paper
  pipelines, and (b) a separately preregistered study of a *selection* hypothesis conditional on KEPT
  (fresh data for confirmation; V1 and V2 rows may only generate hypotheses, never validate them).
- Not authorized: TAKE/SKIP release, funded BUY, landing/fill, shadow execution, live money, wiring into any
  live entry score, exit-policy selection, or any change to the frozen rule. No edge claim.
- V48 FAIL/CLOSED; V55 COMPLETE/CLEAN and burned for V68 validation; V68 NOT_EVALUATED; Native Participant
  Quality V1 `KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`: untouched.
