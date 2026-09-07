# Route Research v48 — Prospective Flow60 Holdout Protocol

Date: 2026-09-06
Amended: 2026-09-07 after prospective v53 systems validation
Mode: **PAPER / RESEARCH / READ ONLY**

## Purpose

v48 is a fresh prospective holdout for exactly one hypothesis discovered descriptively in v47 and stress-tested by the v47 robustness review.

v46 A/B and every v47 output are discovery data. They are **not** validation data for this hypothesis.

No detector threshold, economic hypothesis, route notional, slippage, horizon, provider pacing, official decision, signing, execution, or live-money behavior is changed by v48.

## Frozen primary hypothesis

Feature: `flow60_event_count`

Feature clock: value causally observable at `research_decision_as_of`.

Frozen bins, copied from the v47 value-only grouping and registered before fresh data:

- LOW: `flow60_event_count <= 25`
- MID: `26 <= flow60_event_count <= 47`
- HIGH: `flow60_event_count > 47`

Primary horizon: **900 seconds**.

Primary contrast: **LOW vs HIGH**. MID is reported but is not part of the primary validation contrast.

Hypothesis:

> In fresh detector-population data, LOW flow60 episodes have better 900s route-only returns than HIGH flow60 episodes in both independent subcohorts, and the LOW segment has positive route-only economic shape rather than being an aggregate rescued by one outlier.

This is a route-only market-opportunity hypothesis. It is not a trading rule, fill result, realized P&L claim, or live-money gate.

## Frozen acquisition design

The **cohort/economic protocol remains the v46 dual-subcohort design**:

- two sequential fresh subcohorts A and B;
- cap 40 / minimum 30 research decisions per subcohort;
- hazard start interval 650ms;
- entry start interval 1000ms;
- exit start interval 250ms;
- horizons remain 300 / 900 / 3600 seconds;
- route-only BUY remains USDC -> token, US$25, 100bps, no taker/signing/submission;
- SELL remains exact entry output amount;
- each subcohort must pass its existing systems/collector/lineage gates independently.

### Systems scheduling amendment frozen before economic holdout collection

The first fresh v48 attempt was aborted before forward collection because its systems gate failed. Subsequent v49-v53 work was systems-only and generated **no Flow60 economic verdict**.

On 2026-09-07 the prospectively defined v53 systems-only run `route-research-systems-stability-20260907-53` passed the unchanged 11-gate systems profile with:

- systems result `11/11`;
- radar coverage 100.0%;
- true backlog 0.047%;
- Pump p95 1867.4ms;
- PumpSwap p95 2540.6ms;
- zero worker errors, drops, hydration budget skips and reservation superset violations;
- complete v50 causal attribution;
- no forward economic collector.

Therefore the acquisition implementation for the still-uncollected v48 economic holdout is amended to use the **validated v53 systems scheduling profile** underneath the unchanged v46/v44/v43 cohort protocol.

Frozen systems-profile changes inherited by v48 acquisition:

- Pump prepare workers = 20 (measured v49 capacity profile);
- v51 stateful-ready priority over already-proven audit-only continuation work;
- v52 existing 3s PumpSwap RPC timeout enforced as hedge decision wall deadline without hidden network oversubscription;
- v53 speculative ingress prefetch is opportunistic-only and cannot queue behind a busy same-pool lock or saturated expensive-resolution semaphore;
- global reservation ordering, same-asset FIFO, replay semantics, detector semantics and causal clocks remain unchanged.

This amendment changes **systems scheduling only**. It does not change:

- detector version or thresholds;
- Flow60 feature definition;
- LOW/MID/HIGH cutoffs;
- 900s primary horizon;
- LOW-vs-HIGH primary contrast;
- support minimums;
- provider pacing;
- cohort cap/minimum;
- route notional/slippage;
- forward outcome definition;
- v48 primary evaluator.

The v48 runner installs the v53 acquisition entry point only for the v46 acquisition call and restores the original globals afterward. Regression tests must enforce that restoration and the frozen economic constants above.

A run key must be fresh. Existing persisted outcomes under either `-A` or `-B` cause fail-closed preflight rejection.

## Causal requirements

The holdout feature dataset is rebuilt with the existing v47 causal builder.

Required:

- zero lineage violations;
- zero missing decisions;
- zero missing episodes;
- zero missing hazard attempts;
- zero missing entry quotes;
- zero official decision mutations;
- `flow60_event_count` observed for 100% of admitted feature rows;
- no future feature, quote, hazard, or retroactive backfill.

Any causal violation invalidates the economic interpretation.

## Primary support gate

At 900s, each fresh subcohort must contain at least:

- 5 AVAILABLE LOW labels; and
- 5 AVAILABLE HIGH labels.

If support is insufficient, classification is `INCONCLUSIVE_V48_PRIMARY_SUPPORT`. Do not alter the frozen bins to rescue support.

## Primary replication gate

All of the following must hold using the frozen 900s LOW/HIGH groups:

1. `median(LOW) > median(HIGH)` in A;
2. `median(LOW) > median(HIGH)` in B;
3. `median(LOW) > median(HIGH)` in aggregate;
4. LOW median return > 0 in A and B;
5. LOW profit factor > 1 in A and B;
6. aggregate LOW profit factor > 1;
7. aggregate LOW `mean_without_best` > 0.

The final condition protects against a single extreme winner creating the apparent edge.

If every item passes, classification is:

`PASS_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS`

If support is adequate but directional/economic criteria fail, classification is:

`FAIL_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS`

A FAIL is a valid scientific result. Do not tune the bins or switch to another v47 candidate on the same v48 sample.

## Secondary diagnostics

The same frozen LOW/MID/HIGH groups are reported at 300s and 3600s, plus MID at 900s, for interpretation only.

They are **not** part of the primary pass/fail gate and must not be used to rescue a failed 900s hypothesis.

## What v48 can establish

A PASS would establish prospective replication of one **route-only descriptive economic hypothesis** on fresh data.

It would still not establish:

- funded executable assemblability;
- transaction landing;
- fills;
- realized slippage;
- realized P&L;
- shadow readiness;
- live-money readiness.

Those remain separate future gates.
