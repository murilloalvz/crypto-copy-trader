# Launch Burst Research Protocol V0

## Status

Independent research track. This protocol does not modify Market-First/V68 and does not combine with Social/Event-First.

## Objective

Test whether causally observable launch/liquidity-activation structure contains short-horizon predictive information. V0 is feature-only and cannot emit an automatic trade decision.

## Live venue contract and strata

The live Market-First pipeline persists lifecycle and trade venues as `pump` and `pumpswap`. Launch Burst uses those canonical stored values directly; it does not introduce aliases.

The following strata are evaluated independently:

1. `pump_launch` — lifecycle venue `pump`.
2. `pumpswap_liquidity_launch` — lifecycle venue `pumpswap`.

No pooled headline result is allowed until each stratum has independent evidence.

## Frozen causal clocks

For each token + venue stratum:

- `chain_t0 = lifecycle.market_started_at`.
- `observed_t0 = lifecycle.observed_at`.
- Default V0 feature window = 30 seconds.
- `decision_as_of = observed_t0 + 30s` on the local observation clock.
- `chain_window_end = chain_t0 + 30s` on the chain clock.

The clock domains are never subtracted from one another.

A trade can enter the V0 snapshot only when:

- its token matches the lifecycle token;
- its venue exactly matches the lifecycle venue;
- `trade.observed_at <= decision_as_of`;
- `chain_t0 <= trade.chain_time <= chain_window_end`.

Venue equality is mandatory. A token that graduates from Pump to PumpSwap inside the same 30-second chain window cannot leak PumpSwap trades into the Pump snapshot or vice versa.

The first causally observed lifecycle row for a token + venue is the immutable candidate anchor. Later lifecycle evidence never rewrites a candidate snapshot. A later-observed row that claims an earlier `market_started_at` is retained as audit evidence.

## V0 features

Only fields already supported by the canonical market observation store are used:

- event count;
- buy/sell count and count buy share;
- unique wallet count and wallet identity coverage;
- unique transaction count and transaction identity coverage;
- known buy/sell notional and known-notional buy share when available;
- notional coverage;
- price coverage;
- first/last price and within-window return only when price coverage is complete;
- first trade delay inside the chain clock;
- first trade delay inside the local observation clock;
- explicit data-quality flags.

The current canonical Carbon market-trade adapter intentionally does not infer USD notional or USD price, so current live acquisitions are expected to expose count/wallet/transaction structure before notional/price structure. The coverage audit must measure this explicitly rather than pretending those feature families are available.

No liquidity amount, holder concentration, bonding-curve progress, market cap, route quality, social score or other field is inferred when it is not present in the canonical store.

## Censoring

A lifecycle anchor is right-censored when the acquisition run does not contain local evidence through `decision_as_of`. Right-censored anchors are not emitted as complete snapshots and remain counted explicitly.

## Outcome-blind coverage audit

Before any economic outcome protocol is frozen, `launch_burst_coverage_audit_v0` measures only:

- anchor/sample counts;
- right-censoring;
- per-stratum sample counts;
- event-count availability;
- first-trade delay availability;
- wallet identity coverage;
- transaction identity coverage;
- notional coverage;
- price coverage;
- data-quality flag prevalence.

The coverage audit must not report:

- future outcome values;
- within-window return values;
- notional magnitudes;
- buy-share magnitudes;
- profitability-ranked candidates.

Its purpose is to determine what the acquisition can measure, not what would have made money.

## No threshold fitting in V0

V0 emits every complete supported launch anchor. It does not define:

- BUY/SELL thresholds;
- minimum event count for profitability;
- minimum buy share;
- wallet breadth threshold;
- return target;
- stop loss;
- take profit.

Those values must not be selected by looking at V0 future returns.

## Outcome progression

1. Run the outcome-blind V0 coverage audit on available acquisitions.
2. Measure sample size, censoring, field coverage and per-stratum data availability only.
3. Decide whether missing feature families need new causal enrichment before economic testing.
4. Freeze a short-horizon outcome protocol using coverage/operational evidence, before examining economic returns for hypothesis selection.
5. Use retrospective outcomes only for hypothesis generation and feature prioritization after the outcome protocol is frozen.
6. Freeze one or more candidate Burst hypotheses.
7. Validate them on a fresh prospective cohort.
8. Only a prospective result can support an edge claim.

Existing Market-First +300/+900/+3600 official outcome schedules are not silently reused as Launch Burst evidence because they answer a different decision problem and are episode-bound.

## Convergence rule

Market-First, Launch Burst and Social/Event-First remain independent research tracks. Cross-track convergence is a new hypothesis and can only be tested after the component tracks have their own evidence.
