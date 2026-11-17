# Route-Only Forward Economic Cohort v43 — Frozen Protocol

Date: 2026-09-06
Mode: PAPER / RESEARCH / READ ONLY

## Purpose

v43 is the first integrated forward economic cohort runner after the v42 same-run systems latency PASS. It exists to collect a fresh, causal, funding-free descriptive sample of route-only market opportunity outcomes without manual handoff between acquisition and forward collection.

It does **not** prove executability, landing/fill, realized wallet P&L, profitability after costs, or live readiness.

## Frozen lineage

The v43 runner preserves the existing lineage:

`fresh market episode -> v37 on-chain hazard -> route-only Jupiter BUY -> research_decision_as_of -> exact +300/+900/+3600 schedule -> route-only Jupiter SELL -> descriptive evaluation`

Frozen detector and market semantics are inherited from v42. v43 does not change:
- detector thresholds;
- episode window;
- first-persisted trigger canonicality;
- replay/no-retroactive-enrollment rules;
- v42 scheduler/hydration worker profile;
- route-only BUY/SELL semantics;
- $25 research notional;
- 100 bps slippage parameter;
- official decision/outcome tables.

## Cohort admission

Default predeclared research cap: 40 episodes.
Minimum clean research decisions required to begin forward collection: 30.

The cap is intentionally larger than the minimum so explicit provider/hazard failures do not cause post-hoc threshold changes.

Every admitted research decision must have exactly three persisted PENDING schedules: 300s, 900s and 3600s. If fewer than 30 research decisions freeze, or schedule lineage is incomplete, the run is preserved as undersized and the forward collector does not start.

## Same-run systems gate

Before forward collection begins, v43 audits the v42 output using the unchanged 11-point systems gate:
1. worker errors = 0;
2. drops = 0;
3. reference asset episodes = 0;
4. radar coverage >=95%;
5. true backlog `(received - radar_processed) / received` <=5%;
6. Pump radar p95 <=5s;
7. PumpSwap causal pipeline p95 <=5s;
8. hydration budget skips = 0;
9. wallet/flow bundles non-empty;
10. continuation replay/audit writer has no fatal error;
11. reservation superset violations = 0.

If the same-run systems gate is not 11/11, v43 fails closed and does not start economic forward collection.

## Forward collection

The collector starts immediately after the 120s acquisition/research phase. Because the first scheduled horizon is +300s from each research decision, the fresh schedule exists before its first target is due.

The collector derives its stop deadline from the latest persisted target plus a bounded grace interval rather than relying on a hard-coded 3700-second assumption.

Rules:
- only PENDING outcomes at or after exact target are eligible;
- SELL input amount is the exact route-only BUY output amount;
- token -> USDC;
- taker=None;
- no signing / execute / transfer;
- valid route quote remains executable=False;
- provider failures remain explicit;
- no candle substitution or later backfill.

Target lateness is measured as `exit_quote.observed_at - outcome.target_at`.
Frozen descriptive observability criterion: target lateness p95 <=2s.

## Final descriptive review gate

`READY_FOR_DESCRIPTIVE_RESEARCH_REVIEW` requires all of:
- same-run systems 11/11;
- >=30 fresh research decisions;
- exact 300/900/3600 schedules for every decision;
- forward collection terminal complete;
- target lateness p95 <=2s;
- lineage violations = 0;
- >=30 AVAILABLE route-only outcomes at each horizon.

This classification means the sample is large and causal enough for descriptive research review. It is **not** a profitability PASS and must not release shadow/live money.

## Reported economics

For each horizon v43 reports:
- scheduled / available / pending / provider error;
- coverage;
- positive share;
- mean and median route quote return;
- Profit Factor;
- best / worst;
- mean without best;
- largest winner share of gross positive return.

The return remains:

`100 * (SELL route price / BUY route price - 1)`

It does not include signing, landing/fill risk, gas/tips or realized execution costs.

## No tuning rule

The detector, hazard features, wallet/flow features and thresholds remain frozen during this cohort. v43 results may be used for descriptive review and later predeclared time-split/ablation work, but not to retroactively tune the cohort that generated them.
