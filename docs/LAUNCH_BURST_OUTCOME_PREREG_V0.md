# Launch Burst Outcome Preregistration V0

## State

`UNFROZEN_COVERAGE_ONLY`

No Launch Burst economic outcome horizon, entry threshold, profitability threshold, stop, take-profit, or edge criterion is frozen yet.

This file exists to make that absence explicit. Economic evaluation must remain disabled until this document is deliberately advanced to a frozen state after the outcome-blind coverage audit.

## Already frozen before outcome inspection

- Research track: Launch Burst, independent from Market-First and Social/Event-First.
- Strata: `pump_launch` and `pumpswap_liquidity_launch`, evaluated independently.
- Canonical lifecycle/trade venue names: `pump` and `pumpswap`.
- Feature window: 30 seconds.
- Chain T0: `lifecycle.market_started_at`.
- Local availability T0: `lifecycle.observed_at`.
- Decision cutoff for V0 features: `observed_t0 + 30s`.
- Chain feature cutoff: `chain_t0 + 30s`.
- Same-token cross-venue mixing: forbidden.
- Right-censored feature windows: excluded from complete snapshots and counted explicitly.
- Later lifecycle evidence cannot rewrite the first causally observed anchor.
- Automatic BUY/SELL decision: forbidden in V0.

## Must be filled before retrospective economic evaluation

The following fields are intentionally `UNFROZEN`:

- exact outcome horizons;
- exact executable price/quote observation contract;
- allowed observation lateness around each target;
- provider-error and unavailable-outcome treatment;
- entry-price convention;
- fees;
- slippage model;
- transaction/priority-fee model;
- exit convention;
- per-stratum minimum sample requirements;
- primary economic endpoint;
- secondary endpoints;
- success/failure/inconclusive criteria;
- multiplicity policy if more than one hypothesis is tested.

## Freeze gate

This document may move from `UNFROZEN_COVERAGE_ONLY` to a frozen outcome protocol only after all of the following are true:

1. At least one real acquisition has been processed by `launch_burst_coverage_audit_v0`.
2. Sample size and right-censoring are known by stratum.
3. Wallet, transaction, notional, and price availability are known without inspecting return magnitudes.
4. Any required causal enrichment is designed and validated before outcome values are inspected.
5. Outcome horizons are chosen from operational/research objectives, not by maximizing historical P&L.
6. The exact frozen protocol is committed before the first retrospective outcome-analysis commit.

## After freeze

Retrospective outcome data may be used for hypothesis generation only. Any candidate edge selected from retrospective data must then be frozen and evaluated on a fresh prospective cohort before an edge claim is allowed.

## Forbidden shortcuts

- Do not choose horizons by scanning which horizon had the best historical return.
- Do not reuse Market-First +300/+900/+3600 outcomes as Launch Burst evidence without a new explicit contract.
- Do not convert route availability into executable outcome evidence.
- Do not silently drop missing/provider-error outcomes.
- Do not pool Pump and PumpSwap headline results to rescue a failing stratum.
- Do not tune feature thresholds after viewing prospective outcomes.
