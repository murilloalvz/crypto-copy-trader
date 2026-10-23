# Opportunity Intelligence — Data Source Feasibility v2 — 2026-09-03

## Status

**RESEARCH DESIGN / PAPER / READ ONLY.**

This source plan was reviewed while Wallet Forward v2 Run 2 was active. It does not call providers from the active PC, alter the run, add a trading score or authorize execution.

## Design question

What is the cheapest and most causal way to collect the first evidence-backed Opportunity Snapshot without building an oversized provider stack?

The source hierarchy is deliberately conservative:

1. reuse data already persisted by the project;
2. use native Solana/on-chain data where practical;
3. reuse providers for which the project already has adapters/credentials;
4. add a new provider only when a missing feature family has demonstrated enough value to justify cost and operational dependency.

## Recommended Core v1 source stack

### 1. Wallet trigger and source inventory — existing forward collector

Source:

- Solana RPC + existing Wallet Forward runtime.

Already provides:

- source wallet;
- token mint;
- BUY/SELL;
- `chain_time`;
- real `observed_at`;
- quantity/balance semantics for newer observations;
- DEX/program context;
- run-scoped causal boundary.

Decision: **reuse; no new provider needed.**

This remains the trigger/information event, not an automatic BUY instruction.

### 2. Raw token flow / microstructure — Solana Tracker token trades, provider trial first

Official endpoint:

`GET https://data.solanatracker.io/trades/{tokenAddress}`

Official response/documentation exposes fields including:

- transaction signature;
- amount;
- `priceUsd`;
- USD/SOL volume;
- buy/sell type;
- wallet;
- event time;
- program;
- pools;
- cursor pagination;
- optional Jupiter parsing and arb hiding.

This maps naturally to the Core raw flow contract:

```text
provider event time -> chain/event time
HTTP response completion -> observed_at
wallet -> participant identity
volume -> notional
priceUsd -> event price
```

Current published Solana Tracker pricing (August/September 2026):

- Free: 2.5K requests/month, 3 rps;
- Advanced: EUR 50/month, 200K requests, no paid rate limit;
- Pro: EUR 200/month, 1M requests;
- Premium: EUR 397/month, 10M REST requests + unlimited Datastream;
- Business: EUR 599/month, 25M requests;
- Enterprise: EUR 1,499/month, 100M requests.

Published model: one REST call = one credit.

Important project-specific blocker: the project has previously observed `403 Insufficient credits` from the Solana Tracker Data API. Therefore **do not assume this source is currently available just because the adapter exists**. Verify the account/quota with one explicit post-Run2 provider trial before making it a dependency.

Decision: **best raw-flow first trial if current account access is usable; otherwise fall back to Birdeye raw/aggregate without redesigning the causal schema.**

Official references:

- https://docs.solanatracker.io/data-api/trades/get-token-trades
- https://www.solanatracker.io/data-api

### 3. Cheap aggregate order-flow baseline — Birdeye Token Trade Data Single

Official endpoint:

`GET /defi/v3/token/trade-data/single`

Current docs expose custom frames:

- up to 8 intervals per request;
- second intervals must be multiples of 5s, from 5s to 3600s;
- minute intervals 1m to 1440m;
- trade counts, buy/sell activity, unique-wallet participation and volume features.

Therefore one request can directly request our first candidate frames:

```text
10s,30s,60s,300s
```

Current documented cost:

- 10 Compute Units per request.

Current Birdeye plan pricing:

- Standard: free, 30K CU, 1 rps, limited access;
- Lite: USD 39, 2.5M CU, 15 rps;
- Starter: USD 99, 8M CU, 15 rps;
- Premium: USD 199, 20M CU, 50 rps;
- Business: USD 499, 60M CU, 100 rps.

There is a documentation-access nuance: endpoint badges and the general package-access table are not perfectly consistent for every package name. Before depending on a paid tier, verify the actual API key's endpoint access rather than inferring it from the pricing page.

### Cost implication

At 10 CU per aggregate snapshot, the free 30K-CU allowance is theoretically about 3,000 such requests/month if this endpoint is available to the account.

This makes **event-driven collection** attractive and continuous per-token polling unattractive.

Example of what NOT to do:

```text
1 token polled every 10s
= 6 requests/min
= 60 CU/min at 10 CU/request
= 86,400 CU/day for one token
```

Instead:

```text
wallet event arrives
-> request one causal aggregate snapshot
-> persist raw response + requested_at + observed_at
-> decide whether another follow-up snapshot is part of a preregistered experiment
```

Decision: **strong low-cost aggregate baseline; do not pretend aggregate frames are raw trades.**

Official references:

- https://docs.birdeye.so/reference/get-defi-v3-token-trade-data-single
- https://docs.birdeye.so/docs/pricing
- https://docs.birdeye.so/docs/rate-limiting

### 4. Raw-flow fallback / cross-check — Birdeye V3 recent/token trades

Birdeye V3 recent trade APIs support rich trade-level filtering and up to hundreds of items per request. Current documentation for recent V3 trades reports dynamic CU cost:

- up to 100 items: 12 CU;
- up to 300 items: 30 CU;
- up to 500 items: 50 CU.

This is useful when we need participant/transaction-level evidence rather than an aggregate frame.

Decision: **use as fallback/cross-check if Solana Tracker raw trades are unavailable or for provider agreement studies. Do not collect the same expensive raw feed from two providers permanently unless redundancy proves useful.**

Official reference:

- https://docs.birdeye.so/reference/get-defi-v3-txs-recent

### 5. Token market/risk snapshot — reuse existing provider fields first

Existing project market snapshots already expose useful observational fields such as:

- liquidity;
- holders;
- top-10 share;
- developer share;
- insiders;
- snipers;
- LP burn;
- provider risk score;
- buy/sell counts;
- volume windows.

Solana Tracker also currently advertises risk information, including sniper/insider/bundler/authority/liquidity factors, in token responses.

Decision:

- persist raw provider fields/provenance;
- treat provider risk scores as inputs, never truth labels;
- do not spend many holder-pagination requests at every T0 until concentration features prove incremental value;
- do not call `risk_score -> reject` without our own forward validation.

### 6. Venue/pool fragmentation — Birdeye market list only when needed

Birdeye Token All Market List can return markets/pools for one token and sort by liquidity/volume. Current documented cost: 20 CU/request.

Potential features:

- number of meaningful markets;
- dominant-pool share;
- route/liquidity fragmentation;
- post-launch migration from one venue to broader DEX liquidity.

Decision: **Tier 2 collection. Do not pay this cost for every event until route fragmentation shows a reason to matter.**

Official reference:

- https://docs.birdeye.so/reference/get-defi-v2-markets

### 7. Execution surface — existing Jupiter causal quotes

The project already persists Jupiter `/order` research quotes with:

- side;
- input/output route direction;
- real observation time;
- price;
- provider router;
- provider slippage metadata;
- provider price-impact metadata;
- provider swap USD value when available;
- success/error attempt lineage.

Decision: **reuse Jupiter. Do not add Solana Tracker Raptor quote calls merely to duplicate the same execution question.**

Proxy quote remains a price/route observation, not a fill.

### 8. Network/priority-fee regime — native Solana RPC

`getRecentPrioritizationFees` returns recent prioritization-fee observations. Current Solana documentation states:

- node cache contains up to 150 recent blocks;
- up to 128 writable account addresses can be supplied;
- account-specific requests reflect fees for a transaction locking those accounts.

This is useful as a cheap congestion/fee-regime feature.

Important limitation from Solana's own docs: without relevant accounts the result often reflects the lowest fee and can be zero, so it is not a complete landing-probability model.

Decision: **collect as network-regime context; never call it a fill probability.**

Official references:

- https://solana.com/docs/rpc/http/getrecentprioritizationfees
- https://solana.com/docs/core/fees

## Critical timing contract for every REST source

A provider query triggered by a wallet event adds real latency.

Required timeline:

```text
wallet chain_time
-> wallet observed_at
-> provider requested_at
-> provider completed/observed_at
-> decision_as_of >= every feature used
-> execution ready_at
```

A feature received at 10:00:05 cannot be attached to a hypothetical decision made at 10:00:01.

For raw trade APIs:

- event timestamp describes market time;
- response completion describes our knowledge time.

For aggregate frame APIs:

- persist the full provider response;
- persist requested/completed time;
- retain provider timestamp if supplied;
- do not synthesize fake individual trades from the aggregate.

The cost of gathering intelligence must later appear in end-to-end execution latency.

## Provider-call strategy

### Phase A — event-driven research

On an eligible forward wallet BUY:

1. persist wallet action;
2. request the cheapest high-value flow context;
3. persist response and timing even if partial/failing;
4. obtain the preregistered execution quote path;
5. define decision time only after the inputs used by that experiment were available.

### Phase B — ablation

Compare using the same opportunity universe:

- wallet only;
- wallet + execution;
- + aggregate flow;
- + raw flow if available;
- + basic risk;
- + regime.

Do not pay for graph/social/lifecycle enrichment until the causal core shows what remains unexplained.

## Current source choice

### First preferred trial

- Wallet: existing forward collector.
- Execution: existing Jupiter.
- Flow aggregate: Birdeye `trade-data/single` event-driven.
- Raw flow: Solana Tracker token trades **only if one post-Run2 quota/access check passes**; Birdeye V3 fallback otherwise.
- Risk: existing token snapshot/provider fields.
- Network: native Solana priority-fee RPC.

### Explicitly deferred

- X/social paid integration;
- Telegram/Discord scraping;
- Google Trends;
- LLM narrative scoring;
- Pump.fun-only architecture;
- expensive holder graph on every event;
- second execution quote vendor;
- provider x402/payment-per-request flow.

The Birdeye x402 option is not appropriate for the current project because it requires per-request on-chain payment/signing mechanics, while the project remains research/read-only and already supports API-key providers.

## Cost north star

Do not optimize for the maximum number of API calls. Optimize for **information gained per causal opportunity per dollar/CU/credit**.

A feature family earns higher collection cost only after a cheaper baseline fails to explain the relevant variation or an ablation shows incremental forward value.