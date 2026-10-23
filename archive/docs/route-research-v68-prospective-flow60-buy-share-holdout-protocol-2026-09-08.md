# Route Research v68 — Prospective Flow60 Buy-Share Holdout Protocol — 2026-09-08

## Mode

**PAPER / RESEARCH / READ ONLY**

No signing, transaction submission, shadow/live execution, label-optimized thresholding, or candidate switching is permitted.

## Origin

v55 completed one fresh causal discovery sample with 79 rows (A=39, B=40) and exactly one eligible 900s descriptive hypothesis candidate under the pre-registered candidate-selection bridge.

Selected rank #1:
- feature: `flow60_buy_share_pct`
- family: `direction`
- discovery comparison: HIGH-minus-LOW
- delta median A: -10.660 pp
- delta median B: -8.360 pp
- delta median ALL: -8.639 pp
- favorable discovery extreme: LOW
- opposite extreme: HIGH

The v55 sample is discovery-only and burned for validation.

## Frozen feature definition

`flow60_buy_share_pct = 100 * buy_count / event_count`

for the causal 60-second flow window reconstructed at `research_decision_as_of` by the already-implemented v55 feature builder.

No label participates in feature construction.

## Frozen bins

The canonical published value-only tertile cutpoints from v55 are frozen exactly as:
- LOW <= 57.1429
- MID >57.1429 and <=65.7143
- HIGH >65.7143

No threshold recalculation is permitted on v68 data.

## Frozen primary hypothesis

Among episodes already admitted by the unchanged market-opportunity radar:

> the LOW `flow60_buy_share_pct` extreme will have superior route-only 900-second outcomes to the HIGH extreme, and LOW will be economically positive/robust under the full pre-registered gate.

This is a hypothesis about conditional opportunity quality after detection. It is not a claim that sell pressure is bullish or that LOW should be bought automatically.

## Primary horizon and contrast

- primary horizon: 900 seconds
- favorable group: LOW
- opposite group: HIGH
- primary contrast: LOW vs HIGH
- minimum available support per subcohort: LOW >=5 and HIGH >=5

MID is diagnostic only.

300s and 3600s are diagnostic only.

Neither MID nor another horizon may rescue a failed 900s primary gate.

## Acquisition

Fresh untouched base key only, with `-A` and `-B` appended.

Frozen acquisition semantics:
- existing v46 independent A/B cohort path;
- validated v54 demand-only systems profile;
- Pump prepare workers remain the validated value;
- same detector thresholds;
- same episode semantics;
- same hazard semantics;
- same provider pacing 650/1000/250ms by default;
- same route-only US$25 notional;
- same 100 bps slippage;
- same horizons 300/900/3600;
- same at-most-once missingness semantics;
- no retry/backfill to improve economics.

A systems/acquisition failure produces no economic hypothesis verdict.

## Causal holdout audit

Before economics, require:
- A >=30 causal rows;
- B >=30 causal rows;
- lineage violations = 0;
- missing decisions = 0;
- missing episodes = 0;
- missing hazard attempts = 0;
- missing entry quotes = 0;
- official decision mutations = 0;
- v55 deterministic feature augmentation failures = 0;
- feature clock violations = 0.

Any failure stops before the primary economic gate.

## Feature observability

For the primary evaluator, `flow60_buy_share_pct` must be present and finite for every causal holdout row. A missing primary feature is `FAIL_V68_FEATURE_OBSERVABILITY`; it is not assigned to LOW/MID/HIGH.

## Primary PASS gate

After minimum support is satisfied, PASS requires **all**:

1. LOW median > HIGH median in A;
2. LOW median > HIGH median in B;
3. LOW median > HIGH median in ALL;
4. LOW median >0 in A;
5. LOW median >0 in B;
6. LOW profit factor >1 in A;
7. LOW profit factor >1 in B;
8. aggregate LOW profit factor >1;
9. aggregate LOW `mean_without_best` >0.

This intentionally rejects a result where LOW is merely less bad than HIGH.

## Classifications

Possible primary outcomes include:
- `PASS_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS`
- `FAIL_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS`
- `INCONCLUSIVE_V68_PRIMARY_SUPPORT`
- `FAIL_V68_FEATURE_OBSERVABILITY`

Acquisition/causal-audit failures are separately classified and are **not** economic FAILs.

## Failure discipline

If v68 FAILS or is INCONCLUSIVE:
- do not change the cutpoints on this sample;
- do not select MID;
- do not promote 300s/3600s;
- do not switch to another v55 feature;
- do not combine v55 features to rescue the result;
- do not inspect only a favorable subcohort;
- do not reuse the v68 sample for a replacement validation.

The run key/sample is burned once acquired.

## What PASS would prove

PASS would provide prospective evidence that one simple, preselected, causal market-flow feature can identify a route-only subset with more robust 900-second opportunity economics than the opposite extreme.

PASS would still **not** prove:
- executable transaction assembly;
- landing/fill probability;
- realistic slippage/priority-fee net P&L;
- exit-policy profitability;
- shadow execution profitability;
- live-money edge.

Those remain later gates.
