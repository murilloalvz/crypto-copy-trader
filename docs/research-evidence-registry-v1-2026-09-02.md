# Research Evidence Registry v1 — 2026-09-02

## Status

**RESEARCH PLAN / PAPER / READ ONLY.**

This registry records external evidence that may justify, deprioritize or reject candidate signal families for Crypto Copy Trader. It does not define a trading rule and does not change the frozen Wallet Forward v2 replication.

The goal is to avoid two opposite errors:

1. implementing attractive ideas with no evidence;
2. over-trusting evidence that does not transfer to short-horizon Solana memecoin execution.

## Evidence grades

### Grade A — peer-reviewed and directly useful mechanism

Peer-reviewed cryptocurrency evidence with a mechanism relevant to our research question. Still requires Solana/memecoin forward validation before promotion.

### Grade B — peer-reviewed but indirect transfer

Useful crypto evidence, but the market, horizon, venue or target differs materially from our system.

### Grade C — recent Solana-specific preprint / working paper

Highly relevant domain evidence but not yet peer-reviewed. Useful for feature hypotheses and collection design, not sufficient for strategy promotion.

### Grade D — official protocol / execution documentation

Authoritative for how Solana/Jupiter execution works, but not evidence of predictive alpha.

### Grade E — intuition / practitioner idea

Allowed in the hypothesis backlog but receives no engineering priority without stronger evidence or very low collection cost.

## Evidence table

### E1 — Order flow and cryptocurrency returns

- Grade: **A**.
- Source: Anastasopoulos, Gradojevic, Liu, Maynard, Tsiakas — *Journal of Financial Markets*, 2026, “Order flow and cryptocurrency returns”.
- Scope: cross-section of 84 cryptocurrencies; daily/weekly horizons; world order flow; out-of-sample ML.
- Main result: order flow has explanatory and predictive information for crypto returns; nonlinear ML conditioned on order flow outperformed linear/economic-fundamental baselines out of sample.
- What transfers to our project: signed demand imbalance and flow persistence deserve very high research priority.
- What does **not** transfer automatically: their world fiat-denominated order flow is not the same as second/minute-level DEX flow in Solana memecoins.
- Project action: prioritize causal buy/sell imbalance, buyer arrival, signed volume, flow acceleration and price response to flow.

### E2 — Machine learning and the cross-section of cryptocurrency returns

- Grade: **A/B**.
- Source: Cakici, Shahzad, Będowska-Sójka, Zaremba — *International Review of Financial Analysis*, 2024, “Machine learning and the cross-section of cryptocurrency returns”.
- Scope: cross-sectional crypto return prediction with multiple ML models.
- Main result: model complexity brought limited incremental benefit; simple characteristics such as price, past alpha, illiquidity and momentum drove much of the predictability; apparent alpha concentrated in small, illiquid, volatile coins.
- What transfers: start with simple baselines and high-quality causal features; liquidity must be part of both prediction and feasibility.
- Critical warning: the places with the strongest apparent alpha may be the hardest to trade. Prediction and capturability must be separate targets.
- Project action: do not jump to deep learning; require execution-adjusted evaluation.

### E3 — Cross-sectional interactions in cryptocurrency returns

- Grade: **A/B**.
- Source: Mercik, Będowska-Sójka, Karim, Zaremba — *International Review of Financial Analysis*, 2025, “Cross-sectional interactions in cryptocurrency returns”.
- Scope: interactions among 40 crypto characteristics across more than 500 coins/tokens.
- Main result: strongest interactions involved liquidity, risk and past-return measures; out-of-sample interaction strategies had economic value, while liquidity constraints also helped explain anomaly persistence.
- What transfers: a future Opportunity Model should test interactions such as flow × liquidity × price state instead of relying only on additive scores.
- Project action: collect interaction-ready features, but delay nonlinear modeling until sample size and time splits support it.

### E4 — Cross-cryptocurrency return predictability

- Grade: **A/B**.
- Source: Guo, Sang, Tu, Wang — *Journal of Economic Dynamics and Control*, 2024, “Cross-cryptocurrency return predictability”.
- Scope: Binance cryptocurrencies; lagged returns of other coins predict focal coin returns; out-of-sample tests.
- Main result: evidence consistent with common shocks and slow information diffusion across cryptocurrencies.
- What transfers: token-level decisions may benefit from broader Solana/SOL/memecoin-cluster regime and lead-lag context.
- What does not transfer automatically: daily/centralized-exchange relationships may not persist at second/minute Solana horizons.
- Project action: create a market/regime family rather than evaluating every token in isolation.

### E5 — Cryptocurrency anomalies and economic constraints

- Grade: **A/B**.
- Source: Fieberg, Liedtke, Zaremba — *International Review of Financial Analysis*, 2024, “Cryptocurrency anomalies and economic constraints”.
- Scope: crypto anomalies under economic restrictions.
- Main result: economic constraints materially alter apparent predictability; some effects concentrate in microcaps or bull regimes and can be eroded by trading costs.
- What transfers: every candidate edge must be stress-tested by costs, regime and tradability.
- Project action: prohibit promotion based on gross returns alone.

### E6 — Social media-based attention and crypto returns

- Grade: **A/B**.
- Source: Maître, Pugachyov, Weigert — *Journal of Banking & Finance*, 2025, “Social media-based attention and the cross-section of cryptocurrency returns”.
- Scope: abnormal Twitter attention from 2018–2022.
- Main result: abnormal attention was associated with contemporaneous and one-day-ahead performance; predictability came from investor ticker-tweets rather than official project tweets.
- What transfers: abnormal attention and author/source type are more defensible features than generic sentiment.
- What does not transfer automatically: one-day cross-sectional attention does not establish second/minute alpha in memecoins.
- Project action: social remains a later incremental family, with first-observed timestamps and no assumption that more attention is bullish.

### E7 — Twitter and cryptocurrency pump-and-dumps

- Grade: **A/B**.
- Source: Ardia, Bluteau — *International Review of Financial Analysis*, 2024, “Twitter and cryptocurrency pump-and-dumps”.
- Scope: Twitter promotion around crypto pump-and-dump events.
- Main result: social attention can precede/participate in pump dynamics and investors relying on Twitter can sell late after the dump.
- What transfers: social attention can be an anti-signal, saturation signal or manipulation-risk feature.
- Project action: never implement `social_positive => buy`; measure timing relative to on-chain flow and price.

### E8 — Early Solana memecoin rug prediction

- Grade: **C**.
- Source: Li, Kuznetsov, Yanovich, Nott-Whaley, Vodolazov — arXiv 2608.20271, 2026, “Catching the Rug: Early Prediction of Fraudulent Memecoins on Solana via Machine Learning”.
- Scope: reported dataset of 6.4 million Solana memecoins across seven months; PumpFun and Raydium; first five minutes used to forecast one-hour rug-like outcomes.
- Main result: classic tree models, especially gradient boosting, reportedly detect rug-like outcomes using early trading/liquidity behavior; cross-platform distribution shift is material and multi-source fusion improves robustness.
- Why highly relevant: same chain, memecoin domain and short early horizon.
- Why not Grade A: recent preprint; target is rug-like failure, not executable positive return; definitions and platform distributions require independent scrutiny.
- Project action: elevate **token-risk rejection** and early market/liquidity dynamics; do not copy the paper's labels or thresholds blindly.

### E9 — Solana execution mechanics

- Grade: **D**.
- Source: official Solana fee and compute-budget documentation.
- Main facts relevant to us: transaction priority depends on fee/cost mechanics; priority fees can affect scheduling; compute-unit limits and requested resources affect cost; failed transactions can still incur fees.
- What transfers: executable shadow must measure build/simulate/submit/land latency, priority fees, compute budget, failure probability and realized slippage rather than treating a quote as a fill.
- Project action: execution becomes a modeled surface, not a constant fee assumption.

## Current evidence-weighted ranking

This ranking is provisional and can change as our own forward evidence accumulates.

### Priority 1 — collect/test first

1. **Execution / liquidity / tradability**
2. **Order flow / microstructure**
3. **Token-risk / manipulation rejection**
4. **Wallet action intelligence and independence**
5. **Market/regime context**

Reason: strongest combination of external mechanism, relevance to our current pipeline, relatively causal observability and direct economic impact.

### Priority 2 — collect when the causal core exists

6. **Price/momentum/reversal state**
7. **Launch/lifecycle features, venue-agnostic**
8. **Graph/relationship intelligence**

Graph can move into Priority 1 if apparent multi-wallet convergence becomes important, because related wallets would invalidate independence assumptions.

### Priority 3 — expensive/optional until incremental value is plausible

9. **Social/attention**
10. **Event/narrative/NLP**
11. **alternative attention sources**

This is not a claim that social is weak. It is a cost/causality decision: much of the market state may already be visible on-chain before a stable social collector adds independent information.

## Negative findings / anti-hype rules

The following conclusions are explicitly **not** supported:

- Pump.fun membership itself is not evidence of edge.
- Graduation is not equivalent to profitable or copyable return.
- A high global Wallet Score is not evidence that a specific entry is copyable.
- Multiple wallets buying are not independent evidence until funding/co-trading relationships are checked.
- High attention or positive sentiment is not automatically bullish.
- High model accuracy does not imply positive executable P&L.
- Deep learning is not automatically superior to simpler models.
- Large backtest returns in illiquid assets are not automatically capturable.

## Evidence protocol going forward

For every proposed feature family, record:

1. exact causal feature definition;
2. why it may work economically;
3. strongest external supporting evidence;
4. strongest counterargument / transfer risk;
5. collection cost and coverage risk;
6. leakage risk;
7. expected incremental comparison baseline;
8. forward/out-of-sample acceptance criteria before implementation of trading weights.

## Current decision

Do not modify Wallet Forward v2 Run 2.

After Run 2, use our own quantity-aware forward evidence to choose the next **data collection** gate. The likely first expansion is a causal snapshot that joins wallet event + execution/liquidity + order-flow/microstructure + basic token-risk state, while keeping social and venue-specific lifecycle features optional until they demonstrate a reason to incur their complexity.
