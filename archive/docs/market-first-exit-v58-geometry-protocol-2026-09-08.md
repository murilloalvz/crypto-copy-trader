# Market-First Exit Geometry v58 — causal measurement protocol

Date: 2026-09-08
Mode: PAPER / RESEARCH / READ ONLY

## Purpose

Define provider-neutral post-entry route-path geometry for the market-first architecture without collecting new live data, choosing an exit policy, or changing v55.

The existing `exit_engine_v1` remains a legacy Wave laboratory and is not the lineage authority for current market-first route research.

## Reference clock

The path begins at frozen `research_decision_as_of`.

Return at the reference clock is 0%. Every path observation must be known strictly after that clock. At current second-resolution storage, an observation in the exact same second is rejected conservatively.

## AVAILABLE route-point semantics

An AVAILABLE point requires:

- a causal non-executable BUY quote known by `research_decision_as_of`;
- a later causal non-executable SELL quote;
- the same token identity;
- BUY then SELL direction;
- when raw token amounts are available, SELL input raw amount must equal the exact raw token output from BUY;
- route-only return remains `100 * (sell_route_price / buy_route_price - 1)`.

This measures route-only opportunity economics. It is not a landed transaction, fill, or realized wallet PnL.

## Missingness

Supported path statuses are `AVAILABLE`, `UNAVAILABLE`, and `PROVIDER_ERROR`.

Missing provider observations stay in the coverage denominator and are never converted to zero, forward-filled, backfilled, interpolated, or used to infer an intragap threshold crossing.

## Descriptive geometry

v58 may report:

- route-path coverage;
- first and last available offsets;
- MFE and time to observed MFE;
- MAE and time to observed MAE;
- last observed route return;
- peak-to-last giveback;
- percentage of observed MFE retained at the last point when MFE > 0;
- maximum gap between available observations.

These are descriptive measurements only.

## Explicitly not defined by v58

v58 does not choose:

- stop loss;
- take profit;
- trailing stop;
- maximum holding time;
- sampling cadence;
- winner policy;
- economic PASS gate.

No exit parameter may be reverse-engineered from the currently running v55 sample.

## Future dense-path collector prerequisites

A separate protocol must be frozen before spending live provider budget. At minimum it must define the target cohort, observation cadence, maximum horizon, provider semantics, exact BUY-output-to-SELL-input quantity lineage, missingness handling, latency gates, and sample independence.

## Scientific boundary

Entry selection and exit research stay separate. A good post-entry path does not validate an entry hypothesis, and a good entry hypothesis does not validate an exit rule.