# Evidence-Based Signal Research Universe v1 — 2026-09-02

## Status

**RESEARCH PLAN / PAPER / READ ONLY.**

This document expands Opportunity Intelligence beyond any preferred venue or source. Pump.fun, X, wallets, Wave and any future provider are candidate information channels, not assumptions about where edge must exist.

The research question is:

> Which information available at decision time adds stable, incremental, economically capturable value after costs, latency, missingness, dependence and execution constraints?

No channel receives a permanent place in the strategy without out-of-sample evidence.

## Research principles

1. **Prediction is not execution.** A return signal is useful only if the move remains capturable after detection lag, quote drift, price impact, slippage, fees, landing probability and exit constraints.
2. **No favorite feature.** Wallet, Pump.fun, X/social, Wave and every other signal may be promoted, demoted or removed.
3. **Causal snapshots only.** Features must be frozen using information actually observed by decision time.
4. **Incremental evidence.** Each feature family must beat the simpler baseline through ablation tests.
5. **Out-of-sample first.** In-sample explanatory power is insufficient for promotion.
6. **Economic metrics first.** Net executable return, drawdown, MFE/MAE, tail loss, coverage, concentration and stability matter more than raw classification accuracy.
7. **Dependence is explicit.** Multiple buys from one wallet/token cluster do not create independent sample size.
8. **Failure/rejection signals matter.** A feature that prevents catastrophic trades may be more valuable than a feature that predicts upside.
9. **Complexity must earn its cost.** More features/models are not automatically better.
10. **No live promotion from this research plan.** Shadow/live remain gated separately.

## Evidence-backed candidate families

### Tier A — highest research priority

These families currently have the strongest combination of market-mechanism plausibility, external evidence and relevance to the project's forward data.

### 1. Order flow / microstructure

Candidate features:

- buy/sell imbalance;
- aggressive buy arrival rate;
- unique buyer arrival rate;
- acceleration/deceleration of buyer flow;
- trade count velocity;
- signed volume and signed notional;
- median/tail trade size;
- repeated buyer share;
- new-wallet versus recurrent-wallet flow;
- short-window reversal versus continuation;
- price response per unit of signed flow;
- flow concentration among a few actors;
- flow persistence across 10s/30s/1m/5m windows.

Research goal: determine whether wallet events become useful primarily when supported by informative contemporaneous flow.

### 2. Liquidity / tradability / execution surface

Candidate features:

- available route count;
- quoted output and price impact for multiple notionals;
- quote deterioration 0/15/30/60/120s;
- pool depth and depth change;
- liquidity additions/removals;
- route fragmentation across venues;
- expected versus realized/proxy slippage;
- failed quote rate;
- landing probability proxy;
- priority-fee environment;
- network congestion;
- detection -> quote -> build -> submit -> land latency when executable shadow exists;
- exit liquidity at the same notional used for entry.

This family is both a predictor candidate and a feasibility gate. A signal that exists only in assets that cannot be traded economically is not an actionable edge.

### 3. Wallet action intelligence

Candidate features should describe the **specific action**, not merely a global wallet score:

- wallet behavioral archetype;
- historical holding-time distribution;
- scale-in/reentry tendency;
- full versus staged exit tendency;
- recent activity regime;
- size of current entry relative to wallet's typical entry;
- size relative to observable liquidity;
- entry after previous profitable/loss sequence;
- wallet/token familiarity;
- wallet venue preference;
- independent multi-wallet convergence;
- time spacing between independent wallet entries;
- source-wallet exit behavior and source inventory evolution.

Research goal: identify when a wallet action contains transferable information rather than assuming that a profitable wallet is copyable.

### 4. Token risk / fraud / manipulation defense

Candidate features:

- holder concentration;
- creator/deployer concentration;
- creator selling or liquidity withdrawal;
- mint/freeze/state risks where applicable;
- wallet funding lineage;
- tightly connected wallet clusters;
- synchronized related-wallet trading;
- circular/self-like flow indicators;
- abnormal concentration of early supply;
- abrupt liquidity removal;
- abnormal early price/volume trajectory;
- suspicious repeated launch/deployer patterns;
- token age and survival state.

This family may be more valuable as a rejection model than as an upside predictor.

### 5. Market and regime context

Candidate features:

- SOL short-horizon return/momentum/volatility;
- BTC/ETH risk regime where relevant;
- broad Solana memecoin activity regime;
- market-wide buy/sell pressure;
- cross-token spillovers;
- launch/activity intensity;
- realized volatility regime;
- liquidity regime;
- congestion/fee regime;
- time-of-day/day-of-week only if it survives forward validation.

Research goal: prevent a token-level model from treating the same local signal identically in materially different market states.

## Tier B — strong candidates that must prove incremental value

### 6. Price / momentum / reversal state

Candidate features:

- returns over multiple causal windows;
- acceleration rather than level only;
- realized volatility;
- distance from local high/low;
- draw-up before wallet entry;
- momentum exhaustion;
- volume-adjusted momentum;
- price response to flow;
- short-horizon reversal state.

The goal is not generic technical analysis. These variables are controls and interaction terms for flow, liquidity and wallet actions.

### 7. Launch/lifecycle intelligence — venue agnostic

Pump.fun is one implementation of this family, not the family itself.

Candidate features:

- launch age;
- venue/launch mechanism;
- bonding-curve state when relevant;
- progress/velocity through the launch mechanism;
- migration/listing event state;
- initial liquidity formation;
- early buyer dispersion;
- creator behavior;
- post-migration liquidity quality;
- transition from launch venue to general DEX liquidity.

If Pump.fun-specific variables add no incremental value outside Pump.fun, they remain venue-specific rather than becoming core model inputs.

### 8. Graph / relationship intelligence

Candidate features:

- shared funder relationships;
- repeated co-trading clusters;
- wallet communities;
- creator -> buyer relationships;
- historical co-occurrence of wallets across tokens;
- whether apparent multi-wallet convergence is truly independent;
- connected-component concentration among early holders/traders.

This layer is especially important to avoid mistaking coordinated wallets for independent confirmation.

### 9. Social / attention / information novelty

Candidate features:

- abnormal mention velocity;
- unique-author velocity;
- author concentration;
- original-post versus repost share;
- ticker/contract-address mentions;
- novelty of information;
- first-observed timing relative to price/flow;
- engagement acceleration;
- credible/source archetype;
- saturation/late-attention state;
- disagreement/dispersion rather than sentiment alone;
- cross-source confirmation when legally and technically available.

Social is not assumed bullish. It may indicate early attention, volatility, saturation or pump risk.

### 10. Event / narrative intelligence

Candidate features:

- new listing/migration;
- protocol announcement;
- exploit/security event;
- influencer/news event;
- ecosystem-level event;
- token-specific event novelty;
- time since event;
- whether market/on-chain flow confirms or contradicts the event.

Event text should be resolved to the correct mint/contract before use.

## Tier C — optional / later research

These are allowed but should not displace higher-value data collection without evidence:

- Google Trends or broader web attention;
- Telegram/Discord attention where access is lawful/stable;
- NLP sentiment models;
- image/meme semantic features;
- macroeconomic data;
- developer/GitHub activity for tokens where it is meaningful;
- generalized LLM narrative scoring;
- alternative datasets with high licensing/API cost.

The expected bar for Tier C is high because latency, coverage, provider dependence or engineering cost may dominate the incremental signal.

## Exit intelligence — first-class research problem

Entry prediction alone cannot make the system economically successful.

Candidate exit-state features:

- source-wallet reduction/full exit;
- momentum deterioration;
- flow reversal;
- buyer-arrival collapse;
- sell-flow acceleration;
- liquidity deterioration/removal;
- quote deterioration;
- holder/creator dump event;
- volatility explosion;
- MFE/MAE path;
- time-in-trade hazard;
- trailing state;
- regime transition.

Future experiments should compare source-copy exits against independent risk-managed exits without hindsight selection.

## Execution research — eventual shadow prerequisites

When the project reaches executable shadow, measure rather than assume:

- transaction build success;
- simulation success;
- priority fee required;
- compute units;
- broadcast route;
- submit-to-land latency;
- blockhash expiry;
- landing/failure probability;
- realized input/output;
- realized slippage;
- retry cost;
- adverse price movement while waiting;
- entry and exit separately.

Proxy quotes remain useful research evidence but are not fills.

## Modeling ladder

Do not jump directly to a large neural model.

1. deterministic baselines;
2. univariate feature studies;
3. simple logistic/linear models where appropriate;
4. regularized models;
5. tree boosting / ranking models;
6. survival/hazard models for token failure and exits;
7. regime-aware models;
8. graph features/models if relationship evidence warrants them;
9. ensembles only after simpler models establish complementary errors.

Every model is compared against simpler baselines using time-separated data.

## Required ablation ladder

A provisional comparison ladder is:

1. wallet only;
2. + execution/liquidity;
3. + order flow/microstructure;
4. + token-risk rejection;
5. + market regime;
6. + price-state controls;
7. + launch/lifecycle features where available;
8. + graph independence features;
9. + social/attention;
10. + event/narrative.

The order can change when evidence changes. A family that adds no stable out-of-sample value is removed even if it is intuitively attractive.

## Evaluation targets

Prediction targets should include more than direction:

- net executable return by horizon;
- probability of exceeding a cost-adjusted return threshold;
- probability of severe drawdown/rug-like loss;
- MFE;
- MAE;
- time-to-peak;
- time-to-failure/drawdown;
- exit liquidity;
- source-exit return;
- copyable return;
- landing/fill probability once measurable.

Primary economic evaluation:

- median and mean net return;
- tail loss/CVaR-like measures;
- max drawdown;
- profit factor;
- win rate with uncertainty;
- coverage;
- turnover;
- concentration by wallet/token/cluster;
- performance by regime;
- stability across independent forward windows;
- sensitivity to realistic costs and delays.

## Research evidence incorporated into this plan

External literature reviewed before this plan supports several priorities while also warning against overfitting:

- 2026 Journal of Financial Markets evidence reports that order flow contains economically valuable return-predictive information in cryptocurrency markets.
- 2024 cross-sectional ML evidence finds limited gains from model complexity and identifies price, past alpha, illiquidity and momentum among important predictors; much of the apparent alpha is concentrated in hard-to-trade coins.
- 2025 interaction evidence finds strong interactions among liquidity, risk and past-return characteristics.
- 2024 evidence documents cross-cryptocurrency return predictability consistent with slow diffusion of common shocks.
- 2024-2026 attention research is mixed: abnormal social/search attention can relate to returns, volume or volatility, but other out-of-sample work finds attention variables can fail as return predictors; Twitter is also implicated in pump-and-dump dynamics. Social therefore remains a hypothesis, not a core assumption.
- 2026 Solana-specific rug-pull research finds early on-chain/market behavior and organized wallet behavior useful for detecting fraudulent tokens; recent large-scale work reports strong early detection using the first minutes of trading data and improved robustness from multi-source data.
- Pump.fun research finds structural/behavioral launch features improve prediction of graduation conditional on launch state, but graduation is not equivalent to executable return and venue-specific evidence must not be generalized automatically.
- Solana/Jupiter execution documentation confirms that slippage, priority fees, compute budget and broadcasting/landing mechanics materially affect execution.

## Current project decision

The current Wallet Forward v2 replication remains frozen and unchanged.

After Run 2, use the corrected quantity-aware wallet baseline to decide the next data-collection gate. Do not add dozens of features at once. Prefer adding the highest-value causal feature family while preserving a clean baseline, then test incremental value.

## Research north star

The desired system is not the model that predicts the most pumps in hindsight.

It is the system that, using only information actually available at the time, identifies a small set of opportunities whose **risk-adjusted, cost-adjusted and realistically executable forward outcomes** remain favorable across independent market windows.
