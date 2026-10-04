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

### E10 — Solana rug pull taxonomy and public dataset

- Grade: **C**.
- Added: 2026-10-04 (Fase A / A5). Figures below were checked against the arXiv abstract on that date.
- Source: Chen, Li, Jiang, He, Zhou, Wu, Zheng — arXiv 2603.24625 (v1 2026-03-25, v2 2026-05-31), "From Hype to Collapse: Investigating Rug Pull Scams on Solana".
- Scope: 68 manually verified community-reported incidents → benchmark of 117 confirmed rug pull tokens; a behavior-guided identification + human-validation pipeline applied to 100,063 tokens newly issued on Orca, Raydium and Meteora in H1 2025, labeling 76,469 as rug pulls; a random audit of 382 samples estimates a 0.26% labeling false-positive rate. Dataset released.
- Main result: three Solana-specific rug patterns — **Freeze Authority Abuse**, Liquidity Withdrawal, Pump-and-Dump — because Solana's unified SPL Token program moves fraud from contract logic to on-chain behavior; rugs show very short lifecycles and "highly organized group behaviors".
- What transfers: Freeze Authority Abuse is a deterministic token-metadata fact (SPL mint freeze authority set or not), orthogonal to every flow/participation hypothesis in `src/opportunity_edge_hypotheses_v0.py`. Candidate hard-reject (tail-risk) check if a provider already exposes it causally.
- What does **not** transfer automatically: venues are Orca/Raydium/Meteora, not the Pump.fun bonding curve or PumpSwap; the target is fraud labeling, not executable return; ~76% of new tokens labeled rug means base rates are extreme and any filter must be judged against that base rate.
- Project action: check whether the mint's freeze authority is already captured with a causal `observed_at`; if so, register a rejection-filter hypothesis (not an alpha hypothesis) with its own preregistration. Not yet scheduled.

### E11 — Bot detection inside a Pump.fun copy-trading system (peer-reviewed)

- Grade: **A/B**.
- Added: 2026-10-04 (Fase A / A5). Checked against the arXiv abstract and HTML v3 on that date.
- Source: Luo, Feng, Xu, Liu — arXiv 2601.08641 (v3 2026-02-05), "Resisting Manipulative Bots in Meme Coin Copy Trading: A Multi-Agent Approach with Chain-of-Thought Reasoning", Proceedings of the ACM Web Conference 2026 (WWW'26).
- Scope: 6,000 Pump.fun meme coin projects with complete historical trading records from Flipside; a multi-agent LLM copy-trading system that filters three bot types before deciding.
- Bot definitions (Algorithms 1-3): **bundle bots** = non-creator wallets that buy within the meme coin's creation block; **sniper bots** = wallets buying within the first 1 to K blocks after creation (K=5 default); **bump bots** = flip-to-position ratio α = F/(ΔP+ε) above ξ=50.
- Main result: smart-money trades average 14% return; estimated copier return 3% per investment "under realistic market frictions". The friction model (fees, slippage, latency) is not detailed in the abstract or the sections checked.
- Why A/B and not A: peer-reviewed and directly on Pump.fun, but the economic result belongs to an LLM agent system with under-specified frictions and an evaluation split not checked here; only the bot-detection definitions are directly reusable.
- What transfers: bundle-bot detection is a coordination primitive that needs **no funding link** — the gap confirmed in this repo (no such primitive exists; see `src/market_integrity.py` detection limits and `H_ORGANIC_VS_COORDINATED_V0`). It is computable from creation-block trades the project already observes.
- What does **not** transfer automatically: the 3%/14% returns; and same-block buying may reflect popularity rather than coordination (see RED-COHORT-2026-v1 in `docs/external-evidence-reuse-map-v1.md`, where an activity-matched placebo showed a larger lift than the cohorts).
- Project action: draft a Bundle Bot Detection V0 preregistration with an activity-matched placebo from the first discovery pass (Fase A / A6). No engineering priority before that preregistration.

### E12 — Pine Analytics, "Exit Liquidity Machines" (practitioner report)

- Grade: **E**.
- Added: 2026-10-04 (Fase A / A5). Checked against the original post on that date.
- Source: Pine Analytics, Substack, 2025-04-21, "Exit Liquidity Machines". Not peer-reviewed. Data from Flipside Crypto dashboards and Arkham Intelligence; about one month of data starting 2025-03-15.
- Method: tokens sniped in the same block they were deployed, restricted to snipers with a direct pre-launch SOL transfer from the deployer.
- Reported figures: over 15,000 tokens; 4,600+ sniper wallets; 10,400+ unique deployers; this pattern is "~1.75% of launch activity on pump.fun"; over 15,000 SOL realized profit; 87% of snipes profitable; over 55% fully exited in under one minute and nearly 85% within five minutes; activity concentrated 14:00-23:00 UTC; over 50% of tokens sniped in the exact launch block.
- Stated limitations: only direct one-hop funding links; multi-hop chains (5-7 hops) are not linked, so the result is a subset of all sniping.
- Correction recorded: an earlier internal summary (claude.ai Project notes, 2026-10-04) described the 1.75% figure as an "admitted ~98% false-negative rate". That is a misreading. 1.75% is the share of Pump.fun launches matching the narrow pattern; the authors acknowledge undercounting but give no false-negative rate.
- What transfers: the mechanism (deployer pre-funds a same-block sniper, exit within minutes) is the same one `docs/direct-funding-link-v61-protocol-2026-09-08.md` formalizes, and the exit timing implies a 900s horizon sits after the typical extraction window.
- Project action: none on its own. Use only as hypothesis background for v61; never as a quantitative prior.

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
