# Post-Run2 Evidence Decision Framework — preregistered 2026-09-02

## Status

**PRE-REGISTERED RESEARCH DECISION FRAMEWORK / PAPER / READ ONLY.**

This document is written **before Wallet Forward v2 Run 2 is evaluated**. Its purpose is to reduce hindsight-driven decisions after seeing the replication result.

It does not alter Run 2, its wallet cohort, enrollment window, follow-up window, quote delays or any trading parameter.

## Question after Run 2

The immediate question is not:

> Which parameter would have made the last two runs profitable?

It is:

> What did two independent forward windows establish about the wallet-only baseline, its copyability, its dependence structure and the next highest-value information family we need to observe?

## Audit order

After Run 2 completes, analyze in this order.

### Gate 1 — protocol integrity

Verify independently for Run 2:

- frozen cohort unchanged;
- expected 4h enrollment + 6h follow-up;
- polling interval and RPC commitment unchanged;
- quote delays unchanged;
- copy notional unchanged;
- completed/aborted status and exact cause if aborted;
- enrollment cutoff persisted correctly;
- follow-up-only BUYs excluded from economic denominator;
- finality status;
- causal lag distribution;
- quote coverage and missingness;
- RPC/network telemetry;
- no evidence of retrospective action leakage.

If this gate fails materially, do not interpret economic results as replication evidence. Fix infrastructure only if the failure is architectural; do not change economic parameters.

### Gate 2 — quantity-aware economic integrity

Use only the quantity-aware replay.

Check:

- source inventory reconstruction;
- multiple scale-ins of the same wallet/token;
- partial versus full liquidation semantics;
- noncopy inventory from follow-up-only buys;
- missing exit quote censoring;
- right censoring;
- no invented exits;
- wallet/token cluster isolation.

Legacy event-lot replay must not be used for economic conclusions.

### Gate 3 — effective sample / dependence

Report both raw counts and dependence-aware structure:

- enrolled BUY count;
- active wallets;
- unique tokens;
- wallet/token clusters;
- repeated-event share;
- largest-wallet share;
- largest-token share;
- largest-cluster share;
- number of closed, open and censored economic lots by delay.

Do not treat repeated scale-ins in one wallet/token cluster as independent trials.

### Gate 4 — economic description

For each causal delay, report:

- closed sample count;
- open and censored count;
- mean and median net return;
- win rate with uncertainty when meaningful;
- profit factor when meaningful;
- total descriptive P&L at fixed research notional;
- concentration of losses/wins by wallet/token/cluster;
- sensitivity to quote timing and missingness.

These remain descriptive until independent sample breadth is sufficient.

### Gate 5 — Run 1 vs Run 2 replication comparison

Compare without retuning:

- activity rate;
- enrolled sample size;
- active-wallet breadth;
- token breadth;
- cluster concentration;
- direction and magnitude of quantity-aware returns;
- delay sensitivity;
- censoring pattern;
- quote/execution surface;
- whether losses/wins are persistent across independent clusters or dominated by one event.

## Predefined interpretations

### Outcome A — wallet-only looks consistently weak or economically uncopyable

Examples of evidence:

- repeated negative executable/proxy return patterns across independent wallet/token clusters;
- severe quote deterioration after source entry;
- source entries are profitable only before our observable/quoteable time;
- liquidity/price impact makes apparent source edge inaccessible;
- results remain dominated by adverse selection even at minimal delay.

Decision:

- **do not retune wallet thresholds to rescue the result**;
- treat wallet actions as candidate information events, not automatic copy instructions;
- next data collection gate should capture **execution/liquidity + order flow/microstructure + token-risk context at T0**;
- evaluate whether these contexts can reject bad wallet entries or identify the minority that remains copyable.

### Outcome B — wallet-only looks promising but sample is narrow/dependent

Examples:

- positive descriptive returns but only a few clusters;
- one wallet/token dominates outcomes;
- delay behavior is plausible but uncertainty is large.

Decision:

- no promotion to shadow/live;
- expand independent forward evidence without changing the economic rule based on the positive result;
- still add low-cost causal execution/order-flow context because apparent edge in illiquid assets can disappear after realistic trading constraints.

### Outcome C — wallet-only looks mixed/unstable across runs

Examples:

- Run 1 negative, Run 2 positive, or vice versa;
- strong wallet/regime dependence;
- large differences in activity or market state.

Decision:

- prioritize **market/regime features**, **wallet-action archetype** and **microstructure context**;
- explicitly test whether the same wallet action has different outcomes under different regimes;
- avoid averaging incompatible regimes into one global Wallet Score.

### Outcome D — both runs contain too little independent economic sample

Examples:

- zero/few enrolled BUYs;
- almost all observations censored;
- too few active wallets or unique clusters for useful comparison.

Decision:

- do not infer profitability or failure;
- diagnose whether the bottleneck is acquisition universe, wallet activity, enrollment design or source copyability;
- preserve the existing evidence; any cohort/protocol redesign becomes a **new preregistered acquisition protocol**, not a silent threshold change.

### Outcome E — infrastructure fails but economic opportunity exists

Examples:

- network/RPC or quote collection failure prevents causal reconstruction;
- incomplete finality/causal boundary;
- run aborts before sufficient observation.

Decision:

- repair infrastructure only;
- repeat under the same economic protocol if methodologically justified;
- do not use infrastructure failure as a reason to change wallets or economic parameters.

## Next data-collection candidate — Opportunity Snapshot Core v1

Unless Run 2 reveals a more fundamental acquisition/infrastructure blocker, the highest-value next research object is a **causal T0 snapshot**, not a final Opportunity Score.

For each eligible wallet BUY event, preserve:

### Identity / timing

- run_key;
- observation_id / signal_id;
- wallet;
- mint;
- chain_time;
- observed_at;
- decision_as_of;
- source program / venue;
- token age if known causally.

### Wallet-action state

- current observed buy quantity;
- source balance before/after;
- scale-in/reentry state;
- wallet recent activity rate;
- wallet typical holding-time summary from pre-T0 data only;
- action size relative to wallet's recent observed sizing where causally available;
- independent-wallet convergence count only after relationship checks exist.

### Execution/liquidity state

- causal quote output for research notionals;
- route/provider availability;
- price impact when available;
- quote response latency;
- route count/fragmentation when available;
- quote deterioration probes;
- pool liquidity/depth proxies;
- exit-side quoteability where feasible without introducing future data;
- congestion/priority-fee environment where available.

### Order-flow / microstructure state

Measured only from events observed by T0:

- buy count / sell count in multiple short windows;
- buy/sell notional imbalance;
- unique buyers and sellers;
- buyer/seller arrival acceleration;
- trade-count velocity;
- median/tail order size;
- repeated-wallet share;
- flow concentration;
- short-window return and realized volatility;
- price response per unit of net flow.

### Basic token-risk state

Only features obtainable causally and robustly:

- holder/early-flow concentration where available;
- creator/deployer activity where resolvable;
- liquidity removal/addition observations;
- suspicious connected-wallet indicators once graph data exists;
- mint/freeze/state flags where applicable;
- abrupt early inactivity/liquidity deterioration.

### Market/regime context

- SOL short-window returns/volatility;
- broad tracked-token activity level;
- aggregate buy/sell pressure across the observed universe;
- congestion/fee regime;
- optional BTC/ETH context only if latency/cost is trivial and it proves incremental relevance.

## Explicitly deferred from Core v1

Do not block the first causal core on:

- X/social API integration;
- generalized sentiment models;
- LLM narrative scoring;
- Google Trends;
- Telegram/Discord scraping;
- image/meme semantics;
- Pump.fun-only logic that cannot generalize across venues.

These remain valid hypotheses. They enter later through ablation if the causal market/on-chain core leaves unexplained incremental opportunity.

## Modeling decision before enough data

Do not train a high-capacity predictive model merely because features exist.

Initial work should be:

1. data quality and missingness;
2. causal feature correctness;
3. univariate distributions;
4. cluster-aware descriptive relationships;
5. simple baselines;
6. time-separated validation when sample breadth becomes adequate;
7. only then boosted trees / nonlinear interactions if they beat simpler baselines.

No neural-network requirement exists.

## Two-model research architecture to consider

External evidence suggests separating two questions may be more robust than one monolithic score:

### A. Opportunity / return model

Estimate whether an event has favorable **cost-adjusted capturable upside**.

### B. Rejection / hazard model

Estimate probability of severe failure such as:

- rug-like liquidity collapse;
- extreme adverse excursion;
- inability to exit at research notional;
- manipulation/coordinated-wallet risk;
- catastrophic quote deterioration.

A trade candidate should eventually need both acceptable expected opportunity and acceptable hazard. This architecture is a research hypothesis, not yet a trading rule.

## Exit research commitment

Entry intelligence does not replace exit-engine research.

After enough causal opportunities exist, compare predeclared exit policies using the same entries and causal data:

- source-wallet exit copy;
- fixed horizon;
- stop loss;
- take profit;
- trailing logic;
- flow/liquidity deterioration exit;
- combinations only after individual policies have evidence.

Never select the best exit for each historical trade retrospectively and call that a strategy.

## Stop rules after Run 2

After the combined audit:

- **do not start Run 3 automatically**;
- **do not retune the cohort automatically**;
- **do not add social/Pump-specific features automatically**;
- **do not promote to shadow/live**;
- choose exactly one next methodological gate based on the evidence above.

## Research north star

The project advances when uncertainty is reduced, including when an attractive hypothesis is disproved.

A negative wallet-only result can be a successful experiment if it reveals which contextual information is missing. A simple model that survives execution is preferred to a complex model that wins only in hindsight.
