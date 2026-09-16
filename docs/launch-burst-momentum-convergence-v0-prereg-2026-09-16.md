# Launch Burst Momentum Convergence V0 — preregistration — 2026-09-16

## Purpose

Transfer the most promising historical Wave V2 momentum idea into the current causal Launch Burst route-shadow pipeline, while preserving contradictory evidence instead of treating momentum as already proven. The old provider volume windows are not reused, and the negatively screened Sniper V1 wallet/concentration gates are not promoted into the new primary selector.

## Historical evidence state: MIXED_REPLICATION

The initial `wave_v2_momentum` study produced 64 completed 5-minute outcomes with mean return +5.18%, median +5.11%, win rate 82.8%, profit factor 6.61 and max drawdown US$4.41. Its preregistered volume-acceleration cohort `>=2.00x` had 58 completed 5-minute outcomes with mean +5.63%, win rate 84.5% and profit factor 7.75. At 15 minutes the same initial cohort had n=53, mean +13.30%, win rate 86.8% and profit factor 15.97.

However, a later monitor did not reproduce that effect at the same magnitude. For `>=2.00x`, the later 5-minute cohort had n=45, mean +0.10%, win rate 35.6% and PF 1.04; at 15 minutes it had n=41, mean +2.35%, win rate 46.3% and PF 1.48.

The initial historical data also carried an integrity warning: 35/65 snapshots had inconsistent cumulative 5m/1h/24h volume windows. Therefore this protocol does **not** reuse the old provider acceleration metric, does **not** claim momentum is proven, and does **not** claim metric parity. It transfers only the pre-existing acceleration concept and its `2.0x` threshold into a fresh causal analogue computed from the local stream, where it must earn new evidence.

## Frozen baseline

The control remains the existing Launch Burst selector:

- stratum: `pump_launch`
- evidence window: 5 seconds
- `signed_flow_over_event_reserve >= 0.08`
- entry latency: +2 seconds after causal cutoff
- notional: US$25
- frozen route costs and +2.0 percentage-point provider price-impact upper bound unchanged
- Fixed +60s route-paper remains the primary economic benchmark

## Momentum V0 primary selector

The primary selector is a strict subset of the frozen Burst baseline:

1. `signed_flow_over_event_reserve >= 0.08`
2. `gross_flow_acceleration_second_half_over_first_half >= 2.0`

The acceleration feature is computed only from the same frozen five-second evidence window:

- first half: `[0.0s, 2.5s)`
- second half: `[2.5s, 5.0s]`
- gross flow: `sum(abs(flow / event_reserve))`
- acceleration: `second_half_gross_flow / first_half_gross_flow`

A missing/zero first-half denominator is insufficient evidence and fails closed. No external provider call is required to compute the feature.

This is a **prospective transfer hypothesis**, not a claim that a local 2.5s/2.5s ratio is mathematically identical to the historical 5m-vs-1h provider metric.

## Diagnostics frozen before outcomes

The same fresh capture will report, without selecting the primary hypothesis after seeing outcomes:

- Burst baseline
- Momentum V0 primary
- Sniper V1 primary selector as diagnostic only
- Momentum V0 ∩ Sniper V1 as a separate convergence diagnostic
- event-rate acceleration `>=2x` diagnostic
- buy-flow acceleration `>=2x` diagnostic

Sniper V1 is not promoted because its first 900-second screening produced a worse economic subset than the Burst baseline.

## Horizons

- **Primary:** Fixed +60s, unchanged, for direct comparability with the current route-paper contract.
- **Exploratory historical alignment:** independent route-only exact-quantity SELL mark at +300s, because the strongest initial momentum evidence was measured at five minutes.

The +300s mark does not change the +60s benchmark or SMART-LADDER-25. Missing collector evidence at +300s is an integrity error, not an automatic economic loss. An explicit provider/unroutable observation at +300s uses the frozen unexitable return policy.

## Screening

First fresh screening duration is frozen at 900 seconds. Thresholds must not be changed after seeing this sample.

- directional read: >=10 primary usable route results
- replication eligibility: >=30 primary usable route results
- independent fresh replication remains required

If the primary sample is too small, the response is more fresh data under a separately preregistered extension/replication, not threshold relaxation on the same outcomes.

## Interpretation boundaries

This is no-capital route-shadow research. It does not claim landed fills, realized PnL, production profitability, or an official V4 economic PASS. Public control addresses are used only for read-only Jupiter assembly; no transaction is signed or submitted.

## Robinhood portability

The selector consumes normalized feature snapshots so the architecture can later be reused on Robinhood Chain/Pons. Solana thresholds are not automatically portable. Robinhood activation requires equivalent causal flow/reserve and acceleration semantics plus a fresh chain-specific preregistration.

## Frozen run command

```powershell
python -m benchmarks.launch_burst_control_taker_sim_v0.run_v4_momentum_v0 --duration-seconds 900
```

The process may continue beyond the 900-second acquisition period while +300-second exploratory route marks for late entries finish. That tail is intentional and must not be interrupted merely because the acquisition window has ended.
