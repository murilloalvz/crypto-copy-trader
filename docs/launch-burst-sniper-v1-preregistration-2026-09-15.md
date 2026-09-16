# Launch Burst Sniper V1 — prospective preregistration

Date: 2026-09-15
Status: PREREGISTERED / NO OUTCOME-BEARING RUN YET
Active profile: Solana mainnet / Pump.fun
Policy: `SNIPER-HIGH-PRECISION-V1`
Policy hash: `017873aad04d6d1bede1ef4e0df86c82ccd3dc4634079c8ea2c4543bc46ba8cd`
Frozen route contract hash: `3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d`

## Objective

Test whether a stricter, causal, high-precision subset of the already-frozen Launch Burst selector improves route-shadow economics by rejecting bursts that look too sparse, two-way/churn-heavy, concentrated in one wallet, or insufficiently identified.

This is a selector experiment, not a change to the Launch Burst detector or V4 route-paper contract.

The frozen baseline remains:

- `pump_launch`;
- 5 second evidence window;
- `signed_flow_over_event_reserve >= 0.08`;
- +2 second inherited entry latency;
- US$25 notional;
- frozen route costs/price-impact contract;
- fixed +60 second exit as the primary economic benchmark.

SMART-LADDER-25 remains exploratory exit evidence only.

## Why this experiment exists

The frozen baseline intentionally used one feature. That makes it scientifically clean, but it can admit a large move caused by very few events or a highly concentrated buyer.

The Sniper V1 hypothesis is narrower:

> among launches that already satisfy the frozen `>=0.08` flow rule, bursts with enough early event density, strongly directional flow, broad wallet participation, low single-wallet flow concentration, and adequate identity coverage may form a higher-quality subset.

The experiment prioritizes precision over recall. Fewer selections are acceptable. A zero/small sample is inconclusive; it is not permission to relax thresholds after seeing outcomes.

## Canonical wallet-field repair

The current Carbon Pump trade decoder already emits the trade user as canonical field `wallet`.

The historical Launch Burst shadow envelope searched older aliases (`wallet_address`, `user`, `user_address`, `signer`) and therefore the original feature-only preregistration reported 0% Pump wallet identity coverage.

Sniper V1 adds a runtime enrichment wrapper that reads the existing canonical `wallet` field and places it into the already-existing `AdaptedEnvelope.wallet_key` field.

Guardrails:

- no RPC/API lookup is added to the signal hot path;
- no historical wallet identity is backfilled;
- no future event is used;
- the frozen baseline selector is unchanged;
- enrichment is only used by the preregistered Sniper post-processing layer;
- the snapshot remains frozen before provider quotes.

## Primary selector

Every predicate below must pass inside the frozen 5 second snapshot:

1. `signed_flow_over_event_reserve >= 0.08`
2. `event_count >= 5`
3. `directional_flow_efficiency >= 0.50`
4. `wallet_identity_coverage_pct >= 80%`
5. `wallet_gross_flow_coverage_pct >= 80%`
6. `unique_wallet_count >= 3`
7. `top_wallet_gross_flow_share_pct <= 60%`
8. `transaction_identity_coverage_pct >= 80%`
9. `unique_transaction_count >= 3`

Definitions:

- `directional_flow_efficiency = signed_flow_over_event_reserve / gross_turnover_over_event_reserve`; when defined it is bounded to the natural signed/gross range.
- `wallet_gross_flow_coverage_pct` measures how much frozen-window gross `abs(flow/reserve)` belongs to wallet-identified events. Event-count coverage alone is insufficient because unidentified events could contain most of the flow.
- `top_wallet_gross_flow_share_pct` measures the largest wallet's share of identified gross `abs(flow/reserve)` in the frozen window.

Missing required data is `INSUFFICIENT_EVIDENCE`, never zero/imputed evidence.

## Diagnostic selector

A separate diagnostic-only selector uses:

1. `signed_flow_over_event_reserve >= 0.08`
2. `event_count >= 5`
3. `directional_flow_efficiency >= 0.50`

It is never allowed to replace the primary selector after outcomes are observed. Its only purpose is to distinguish:

- `primary n=0 because wallet/identity gates were unavailable or too strict`, from
- `primary n=0 because even the non-wallet burst quality was weak`.

No economic promotion may be based on the diagnostic selector.

## Prospective comparison design

One live acquisition collects provider evidence exactly as the frozen baseline does.

Sniper V1 does **not** suppress provider calls during the run. Instead:

1. frozen baseline determines which episodes receive route-shadow evidence;
2. feature snapshots are already frozen before provider quotes;
3. after collection, the preregistered Sniper rule is applied to that same baseline universe;
4. baseline and Sniper therefore share the same acquisition, provider conditions, costs, entry timing, and exit observations.

This makes the primary selector a strict counterfactual subset rather than a separate live experiment with different infrastructure conditions.

## Reported economics

Primary benchmark: fixed +60 second route-paper result.

Report at minimum:

- baseline selected count;
- primary Sniper selected count;
- selection rate vs baseline;
- provider/usable-entry coverage for both;
- trade count;
- deployed-capital ROI;
- mean/median/P10/P90 return;
- positive-trade share;
- profit factor;
- worst/best trade;
- sequential PnL max drawdown;
- mean return with best trade removed;
- share of positive PnL contributed by the best winner;
- skipped trade PnL;
- avoided losing-trade count and loss magnitude;
- missed winning-trade count and profit;
- rejection reason counts by frozen predicate.

SMART-LADDER-25 is reported separately as exploratory evidence.

## Sample gates

The first command uses a 900 second screening acquisition.

Frozen sample interpretation:

- `<10` usable primary route results: `INSUFFICIENT_PRIMARY_SAMPLE`;
- `10–29`: directional descriptive read is allowed, replication is not armed;
- `>=30`: sample size is eligible to justify a fresh independent replication run, but still does not establish edge;
- independent replication remains mandatory;
- thresholds must not be retuned using screening or replication outcomes.

These gates address sample size only. Passing them is not a profitability verdict.

## Systems / scientific / economic separation

### SYSTEMS

Must retain the existing V4 acquisition/decoder/watermark/provider accounting gates. Sniper enrichment must not add network calls to the signal path.

### SCIENTIFIC

PASS means:

- policy hash validates;
- frozen baseline universe is preserved;
- Sniper is a strict subset of the baseline;
- snapshots were frozen before provider quotes;
- missing features stay missing;
- no threshold changed after outcomes.

### ECONOMIC

Route-shadow results remain simulation/proxy evidence. They are not landed fills or realized PnL and do not change the official V4 funded-taker economic verdict.

## Robinhood Chain / Pons portability boundary

The selector implementation consumes a normalized feature snapshot rather than Solana-native object types. That is intentional.

Existing project components already reusable for Robinhood Chain include:

- `multichain_market_contract_v59`;
- `robinhood_pons_adapter_v62` for launch/trade/wallet/transaction/lifecycle normalization;
- `pons_curve_state_progress_v64` for exact causal curve reserve/progress state;
- `pons_launch_quality_evidence_v67` for Pons-specific launch facts.

Robinhood activation is deliberately blocked until an adapter proves parity for the Sniper feature semantics.

In particular, the Solana primary feature `signed_flow_over_event_reserve` is event-reserve normalized. Pons trade normalization currently exposes exact quote amounts and separate causal curve-state observations, but the same event-level reserve semantics must not be assumed without proof.

Therefore:

- Chain ID/profile: planned `eip155:4663`;
- reuse normalized feature names and comparison/accounting framework;
- do not reuse Solana thresholds automatically;
- freeze a fresh Pons-specific preregistration after feature-parity/replay evidence;
- keep Market-First, Social/Event-First, and Launch/Sniper tracks independent until explicit convergence evidence exists.

## Non-goals

Sniper V1 does not:

- guarantee profit;
- execute real transactions;
- alter official V4 economic status;
- use social buzz as a blocking gate;
- wait for post-entry social evidence;
- use future wallet history;
- assign a weighted black-box score;
- tune thresholds on the first live outcomes;
- assume Solana thresholds transfer to Robinhood Chain.
