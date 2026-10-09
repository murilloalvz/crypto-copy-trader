# Route-Only Forward Research v40 — Protocol

Date: 2026-09-04

Mode: **PAPER / RESEARCH / READ ONLY**

## Why v40 exists

The project needs forward economic evidence before risking money, but a true executable SELL assembly for a specific taker normally requires that taker to possess the token being sold.

Our funded BUY gate currently assembles but does not execute a transaction. Therefore the taker does not receive the token, and pretending that a later SELL is executable would create false evidence.

v40 solves the circularity by creating a separate causal research track:

`fresh market episode -> on-chain hazard -> route-only BUY -> research_decision_as_of -> route-only SELL at +5/+15/+60 -> descriptive forward evaluation`

This track does **not** replace the official executable/shadow gate.

## Clock separation

`market_opportunity_episodes.decision_as_of` remains reserved for the official funded/executable protocol.

v40 introduces:

`research_decision_as_of`

in a separate store. It is immutable and cannot satisfy the funded executable-entry gate.

A research decision freezes only after:

1. fresh market episode exists;
2. v37 on-chain hazard is terminal AVAILABLE with Mint core;
3. fresh Jupiter route-only BUY is AVAILABLE;
4. BUY quote is non-executable and observed after required causal evidence.

`research_decision_as_of = max(T0, hazard clocks, BUY route clocks)`

No historical run can be enrolled retroactively. A route quote captured after an old episode is not valid v40 entry evidence for that old T0.

## Entry route

Provider: `jupiter_swap_v2_order`

Purpose: `entry_route_only_research_v1`

Frozen research sizing:

- USDC input;
- US$25 notional;
- 100 bps slippage parameter;
- `taker=None`;
- no signing;
- no `/execute`;
- no transfer;
- no private key.

Token decimals come from the already-observed v37 on-chain Mint evidence.

A valid v40 BUY quote MUST have:

`executable=False`

An unexpected assembled transaction is a protocol/normalization error, not a hidden upgrade.

## Research decision and schedule

Each accepted fresh episode gets exactly one immutable research decision and three scheduled outcomes:

- +300s;
- +900s;
- +3600s.

Targets are exact:

`target_at = research_decision_as_of + horizon_seconds`

No automatic fallback between horizons is allowed.

## Exit route

Provider: `jupiter_swap_v2_order`

Purpose per horizon:

`forward_exit_route_only_research_<horizon>s_v1`

The SELL amount is exactly the raw researched-token amount quoted by the frozen v40 BUY route:

`SELL amount_raw = BUY output_amount_raw`

The forward call uses:

- researched token input;
- USDC output;
- `taker=None`;
- no signing/execute/transfer.

A valid route research SELL quote MUST remain `executable=False` and satisfy:

`SELL observed_at >= exact target_at`

Target lateness is reported explicitly.

## Storage isolation

v40 writes only route-research decisions/outcomes, route-only provider attempts and causal quote artifacts.

It does not complete `opportunity_forward_outcomes` and does not freeze the official market episode `decision_as_of`.

This gives two distinct evidence families:

- route-only paper economic evidence;
- future funded/executable/shadow evidence.

They must never be silently merged.

## Evaluation label

For AVAILABLE route-only outcomes:

`route_quote_return_pct = 100 * (SELL route price / BUY route price - 1)`

This is a causal quote-to-quote opportunity outcome.

It is NOT:

- realized wallet PnL;
- landed/fill PnL;
- proof the BUY could land;
- proof the SELL could assemble for a real position;
- net profitability after priority fees, tips, failed transactions, MEV or execution drift.

## Descriptive metrics

For each horizon report at minimum:

- scheduled / AVAILABLE / pending / failed coverage;
- positive-outcome share;
- mean and median route return;
- Profit Factor where defined;
- best/worst;
- mean without largest winner;
- largest winner share of gross positive return;
- lineage violations.

Samples below 30 AVAILABLE observations remain `INCONCLUSIVE_SAMPLE_LT_30`.

No threshold or strategy promotion is allowed from a tiny smoke sample.

## v40 fresh-run plumbing classification

`PASS_ROUTE_ONLY_RESEARCH_DECISION_PLUMBING` requires:

- fresh selected sample >0;
- terminal entry-route coverage 100%;
- >=1 route-only BUY AVAILABLE;
- no config missing;
- no reused entry attempts in fresh run;
- no research worker errors;
- no quote marked executable;
- no research decision clock violation;
- no official `decision_as_of` mutation;
- exact 300/900/3600 schedules for each frozen research decision.

This is an infrastructure/research-causality PASS only.

## Final validation order remains unchanged

v40 allows paper economic research to advance while funding is unavailable. It does not waive later validation:

1. funded executable BUY readiness/gate;
2. official decision freeze;
3. executable/shadow exit behavior;
4. landing/fill and cost audit;
5. robust forward evidence;
6. only then any live-money consideration.
