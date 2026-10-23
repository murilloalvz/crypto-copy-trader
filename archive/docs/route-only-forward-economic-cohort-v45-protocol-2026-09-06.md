# Route-Only Forward Economic Cohort v45 — Protocol

Date: 2026-09-06
Mode: PAPER / RESEARCH / READ ONLY

## Why v45 exists

v44 removed provider throttling as the dominant admission blocker and produced 39 fresh research decisions. Its forward collector completed cleanly, but legitimate Jupiter `HTTP 400 Failed to get quotes` missingness left only 29 AVAILABLE outcomes at both +900s and +3600s, one below the predeclared descriptive minimum of 30.

The persisted v44 diagnostic showed the forward errors were route-unavailable evidence, not Jupiter 429 throttling. Therefore v45 does **not** change SELL pacing, retry behavior, detector thresholds, economic definitions or provider semantics. It increases only the predeclared cohort size to absorb legitimate route missingness.

## Frozen v45 cohort

- selected research episode cap: **50**
- minimum clean research decisions before collector starts: **40**
- acquisition duration: **120s**
- detector: unchanged `market_opportunity_radar_v1_1_tx_aware`
- same-run systems gate: unchanged 11/11
- hazard provider: unchanged v37 on-chain Mint evidence
- hazard start pacing: **650ms**
- route-only BUY start pacing: **1000ms**
- route-only SELL start pacing: **250ms**
- route-only notional: **US$25**
- slippage parameter: **100bps**
- exact horizons: **300 / 900 / 3600 seconds**
- no taker, signing, submission or fund movement
- no retry after terminal provider failure
- no backfill or later substitute quote
- official market episode `decision_as_of` remains untouched

## Admission and collection rules

1. Acquire a fresh market-first cohort under the frozen v42 systems path.
2. Select at most 50 first-time episodes prospectively.
3. Require the same-run systems gate to pass 11/11.
4. Require at least 40 frozen route-research decisions with exact three-horizon schedules.
5. If either gate fails, preserve the run and do not start forward collection.
6. If admitted, collect each scheduled route-only SELL at/after its exact target.
7. Provider failures remain explicit missingness and are never retried or replaced.
8. Evaluate descriptive route returns only from AVAILABLE causal route observations.

## Descriptive readiness

A horizon needs at least **30 AVAILABLE** outcomes for descriptive review. The overall cohort is ready only when all three horizons satisfy the existing v43 lineage/observability rules, including:

- same-run systems 11/11
- clean admission/schedules
- terminal forward collection
- target lateness p95 <= 2s
- lineage violations = 0
- >=30 AVAILABLE outcomes at 300s, 900s and 3600s

`READY_FOR_DESCRIPTIVE_RESEARCH_REVIEW` is not a profitability, executable-fill, shadow or live-money PASS.

## What v45 cannot justify

v45 must not be used to tune detector thresholds, wallet/hazard/flow features, route failure handling or exit horizons from the observed economics. Its purpose is only to reach the already-defined minimum causal sample despite legitimate route missingness.
