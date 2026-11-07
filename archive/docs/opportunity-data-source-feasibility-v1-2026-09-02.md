# Opportunity Intelligence — Data Source Feasibility v1

## Status

**RESEARCH / READ ONLY.** Prepared while Wallet Forward v2 Run 2 is active. No provider in this document is automatically promoted into the runtime.

## Goal

Identify the lowest-cost, highest-causality way to collect the next feature families without building unnecessary integrations.

The project already has clients/infrastructure for Birdeye, Solana Tracker, Solana RPC and Jupiter causal quotes. The preferred strategy is therefore to exhaust reusable data before adding new vendors.

## 1. Order flow / microstructure

### Option A — Solana Tracker token trades

Existing project fit: **high**.

The documented token-trades endpoint returns trade-level observations across pools with fields including transaction signature, amount, USD price, USD/SOL volume, side, wallet, time, program and pool identifiers.

Potential Core v1 fields directly supported:

- buy/sell side;
- wallet identity;
- USD notional;
- price;
- venue/program;
- pool;
- source event time.

Strengths:

- raw trade-level data rather than aggregate only;
- wallet identity enables unique-wallet and repeat-wallet features;
- venue/pool identity enables later fragmentation/lifecycle analysis;
- project already uses Solana Tracker infrastructure.

Risks/questions to validate before adoption:

- real polling latency and timestamp semantics;
- API-plan/rate-limit capacity during bursts;
- ordering and pagination under high-volume tokens;
- Jupiter parsing semantics;
- whether provider trade-time can be safely paired with our own `observed_at` at response ingestion.

Decision: **first raw-flow adapter candidate**.

### Option B — Birdeye V3 token trades

Existing project fit: **high**.

Birdeye documents a token V3 trade feed with side-aware filters, owner/pool/source filters on Solana, up to 100 rows/request and bounded time/block windows. The project already contains a Birdeye client and configuration path.

Strengths:

- trade-level token feed;
- Solana signer/source metadata;
- current documentation explicitly recommends the endpoint when explainability about who traded and where is required;
- independent provider can later be useful for cross-provider reconciliation.

Risks/questions:

- package access for the user's current Birdeye key;
- compute-unit/API quota consumption;
- response latency during bursts;
- exact response fields must be persisted raw before normalization.

Decision: **strong secondary/raw-flow source; possible primary if current package access is better than Solana Tracker**.

### Option C — Birdeye Token Trade Data aggregate windows

Existing project fit: **high**.

Birdeye documents aggregate token trade data with buy/sell counts, unique wallets, volume and change metrics. Custom frames include second windows in multiples of 5 seconds and minute/hour windows.

Strengths:

- very low engineering cost for first descriptive microstructure snapshot;
- directly maps to buy/sell count, unique-participant and acceleration features;
- custom 5s+ windows overlap well with the proposed 10/30/60/300s research windows.

Limitation:

- aggregate data cannot prove self-trading, wallet independence or coordination;
- provider-computed rolling-window semantics need timestamp testing;
- cannot replace raw flow for graph/repeat-wallet research.

Decision: **excellent low-cost aggregate baseline, never a manipulation detector by itself**.

## 2. Execution / liquidity

### Jupiter causal quotes — already available

Existing project fit: **very high**.

The project already persists causal quote timing and provider metadata including router, provider slippage, provider price impact and swap USD value when available.

Immediate reuse:

- quote availability at T0;
- causal buy/sell quote price;
- proxy/executable status;
- provider price impact;
- route/router metadata;
- quote latency and later deterioration across delay probes.

Decision: **reuse before adding another execution vendor**.

### Birdeye market data / exit liquidity

Birdeye currently documents current market-data endpoints containing price, liquidity, market cap/FDV, supply and holders, plus dedicated token exit-liquidity endpoints in its V3 catalog.

Potential use:

- contextual liquidity snapshot;
- research-notional exit-side feasibility;
- liquidity quality cross-check against Jupiter routeability.

Decision: **candidate supplement, not substitute for Jupiter quoteability**.

## 3. Network / landing regime

### Native Solana `getRecentPrioritizationFees`

Existing project fit: **high** because RPC infrastructure already exists.

Solana documents this method as returning recent prioritization fees from a node cache covering up to roughly 150 blocks; optional writable accounts can make the estimate account-specific.

Useful causal features:

- recent fee median/percentiles;
- zero-fee share;
- fee dispersion;
- account-specific fee estimate later when the exact route/accounts are known.

Important limitation from Solana's own guidance:

- the generic minimum fee per block can frequently be zero and is not by itself a reliable landing quote;
- fee pricing is dynamic and no canonical perfect estimator exists.

Decision: **cheap network-regime feature now; actual landing probability must wait for executable shadow telemetry**.

## 4. Token risk / concentration

### Solana Tracker holders

Documented holder endpoints provide top holders and paginated holder lists with balances and percentage ownership.

Potential features:

- top-N concentration calculated consistently by us;
- holder-count trajectory;
- concentration change over time;
- overlap between top holders and tracked wallet/creator clusters later.

Cost concern:

- full-holder pagination is too expensive for every T0 event.

Decision: **use lightweight/top-holder snapshot at low cadence, cache by token and timestamp; do not block entry-time snapshot on full pagination**.

### Existing Solana Tracker search/full token objects

Current documentation exposes fields such as top10, dev, insiders, snipers, holders, buy/sell counts, total transactions, LP burn and curve percentage in full token search objects. The current project already maps several of these into `WaveTokenSnapshot` / `MarketIntegrityFeatures`.

Decision: **reuse as aggregate risk context while explicitly preserving detection limits**.

## 5. Graph / wallet independence

No current aggregate provider field is sufficient to prove independent convergence.

Possible future evidence sources:

- funding transfers from raw Solana history;
- repeated co-trading across tokens;
- common creator/deployer interactions;
- shared pool/launch timing patterns;
- connected components built from observed on-chain relationships.

Decision: **do not fake graph independence in Core v1**. Persist wallet identities now so graph features can be added later without recollecting every event.

## 6. Market/regime context

Lowest-cost first version:

- SOL causal price/return/volatility;
- aggregate activity level across tokens already observed by the collector;
- aggregate buy/sell pressure in the monitored universe;
- RPC/priority-fee regime;
- quote failure/latency regime.

Do not initially block the design on BTC/ETH, macro, Google Trends or social feeds.

Decision: **build regime from data we already touch before purchasing broader datasets**.

## Recommended first collector architecture

```text
wallet BUY observed at T0
        |
        +--> existing Jupiter quote snapshot
        |
        +--> token flow adapter
        |      primary trial: Solana Tracker raw token trades
        |      fallback/cross-check: Birdeye V3 raw trades
        |      cheap aggregate baseline: Birdeye trade-data frames
        |
        +--> cached aggregate token-risk state
        |
        +--> cheap Solana network-regime state
        v
score-free Opportunity Snapshot Core
```

Every HTTP/RPC adapter should persist:

- provider/source;
- request start;
- response/observed time;
- provider event time;
- raw payload or stable raw subset;
- status/error/retry metadata;
- normalization version.

## Provider-selection experiment

Before productionizing a flow source, run a small read-only provider comparison on the same tokens/events:

1. request Solana Tracker and Birdeye around the same T0;
2. persist our own request/observed timestamps;
3. compare trade counts, signatures, sides, wallet identities, price/notional and lag;
4. measure missingness and duplicate semantics;
5. compare API cost/quota and burst resilience;
6. choose the simplest provider that meets causal coverage requirements;
7. retain provider abstraction so the other source remains a reconciliation/fallback option.

## Do not build yet

Until the causal core demonstrates a need for them, defer:

- X/social collector;
- generic NLP sentiment;
- LLM narrative scoring;
- Google Trends;
- Telegram/Discord scraping;
- image/meme semantics;
- venue-specific Pump.fun logic beyond fields already cheaply present;
- full graph database;
- deep learning model.

## Current recommendation

The project is unusually well positioned for the next phase because most of the required first-party/provider plumbing already exists.

The likely lowest-friction path is:

**existing wallet event + existing Jupiter quote + Solana Tracker/Birdeye token flow + cached existing risk fields + native Solana fee regime**.

This should be validated as a data-quality experiment before any trading score is introduced.
