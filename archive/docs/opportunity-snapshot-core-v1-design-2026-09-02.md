# Opportunity Snapshot Core v1 — design freeze

## Status

**RESEARCH INFRASTRUCTURE / PAPER / READ ONLY.**

This design is prepared while Wallet Forward v2 Run 2 is still running. It does not change the frozen cohort, runtime, quote delays, enrollment/follow-up windows or economic interpretation of that experiment.

The purpose is to make the next research layer technically ready without pre-committing to any trading rule.

## Research object

For each candidate opportunity at decision time `T0`, build a score-free snapshot containing only information that the system had actually observed by `T0`.

The snapshot is intended to support later ablation such as:

1. wallet-only baseline;
2. + execution/liquidity;
3. + order flow/microstructure;
4. + risk/rejection context;
5. + market/regime context;
6. later optional lifecycle, graph, social and event families.

No family is guaranteed promotion.

## Causal contract

Every raw observation must carry an availability timestamp.

- chain event: `chain_time` + `observed_at`;
- market quote: `market_time` + `observed_at`;
- future social/event adapters: source creation time + `observed_at`;
- Wave: `detected_at` already acts as the causal availability time.

A feature for `as_of=T0` may use a raw observation only when its availability timestamp is `<= T0`.

Historical backfill may describe behavior but cannot reconstruct historical live awareness unless the real observation time was persisted.

## Core implementation staged in this branch

`src/opportunity_snapshot_core.py` introduces a provider-agnostic causal contract for two high-priority families that can already reuse project concepts:

### Flow observations

`FlowTradeObservation` stores:

- token mint;
- side;
- chain time;
- observed time;
- optional wallet identity;
- optional USD notional;
- optional price.

The builder creates descriptive windows (default 10s / 30s / 60s / 300s):

- event counts;
- buy/sell counts;
- unique buy/sell wallets;
- buy/sell notional when coverage is complete;
- signed notional and normalized imbalance;
- repeated-wallet event share;
- causal within-window price return when prices exist;
- median chain-to-observation lag;
- explicit missingness/coverage flags.

It does not infer missing notionals or prices.

### Execution surface

The contract reuses `CausalQuoteObservation` instead of defining a second quote type.

At `T0` it summarizes only quotes with `observed_at <= T0`:

- buy/sell quote availability;
- executable-vs-proxy coverage;
- latest causal buy/sell price;
- persisted liquidity when available;
- persisted provider price-impact metadata when available;
- router metadata;
- quality flags such as `proxy_quotes_only`.

A proxy quote remains research evidence, not a fill.

## Explicit non-goals

The staged module does **not**:

- create an Opportunity Score;
- choose BUY/SELL;
- add thresholds;
- change Wave eligibility;
- call external providers;
- write to the active Run 2 database;
- reconstruct future information;
- label coordination/manipulation from aggregate counts;
- estimate executable fills from proxy quotes;
- train any ML model.

## Why order flow is prioritized

External peer-reviewed evidence in cryptocurrency markets shows that order flow contains explanatory and out-of-sample predictive information for returns, with nonlinear interactions adding value in that setting. Transfer to second/minute Solana DEX flow is not assumed; it justifies collecting and testing the feature family.

At our horizon, flow must be studied jointly with short-term return because temporary price pressure/reversal can coexist with more persistent information. This is one reason the core stores both flow and price-state information instead of using `buy_count` as a bullish rule.

## Why execution is part of the predictive dataset

Crypto return studies repeatedly show that apparent alpha can concentrate in small/illiquid assets. DEX/AMM research also emphasizes adverse selection, liquidity fragmentation and price impact. Solana transaction priority and cost additionally depend on network scheduling/fees/compute constraints.

Therefore the target is not just `future_return`.

Later labels should distinguish at least:

- market return;
- quoteable/capturable return;
- severe adverse excursion / hazard;
- eventual executable shadow return once landing telemetry exists.

## Missingness is data

The builder deliberately returns `None` plus quality flags instead of inventing values.

Examples:

- no quote at T0;
- proxy-only quote;
- missing USD notional for one event;
- incomplete wallet identity;
- missing price observations;
- no flow events in a window.

This matters because data availability itself may correlate with token quality/liquidity. Imputing silently could hide exactly the condition we need to model.

## Data-source strategy

No provider is frozen by this design.

Preferred order:

1. reuse causal data already persisted by the project;
2. derive from raw Solana/on-chain data when reliable and affordable;
3. use stable external providers for missing market-wide context;
4. preserve raw provider payload/provenance so the provider can later be changed without changing feature semantics.

The first implementation should not depend on X/social, Pump.fun-specific fields, Google Trends or LLM sentiment.

## Validation requirements before integration

The staged contract must pass:

- future-observed chain event excluded from past snapshot;
- windows based on `observed_at`, not `chain_time`;
- future quote excluded;
- incomplete inputs flagged rather than imputed;
- no `score` or decision output;
- invalid causal timestamps rejected;
- full repository unit tests and compileall.

Passing these tests means only that the feature contract is causally safe. It does not prove predictive value.

## Promotion rule

Do not merge this research branch into the main research branch merely because the tests pass.

After Run 2, first execute the preregistered combined audit. Then decide whether the next gate is indeed causal context collection. If Run 2 reveals a more fundamental acquisition or infrastructure blocker, keep this branch staged until that blocker is resolved.
