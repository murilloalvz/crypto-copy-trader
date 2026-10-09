# Market Opportunity Radar v1 — Preregistered Acquisition Protocol

Date: 2026-09-03

Mode: **PRE-REGISTERED / PAPER / RESEARCH / READ ONLY / NO LIVE EXECUTION**

Status: supersedes the wallet-triggered `Causal Opportunity Acquisition v1` **before any acquisition run was started**.

## Why the trigger changed

Wallet Forward v2 proved that the causal collector, Jupiter quote path, finality audit and quantity-aware replay can work prospectively, but it produced only four enrolled BUYs across two 10h windows, with three of the four in one wallet×token cluster.

The acquisition gate therefore moved from:

`selected wallet BUY -> token`

into:

`market activity changes state -> token -> opportunity episode`

Wallet identity is not required to create an opportunity.

## Research question

> Can the project detect early, causally observable changes in token-market activity, persist them as independent opportunity episodes, and enrich them with execution, flow, dynamic wallet intelligence, risk and regime context without look-ahead?

Passing this gate validates data acquisition. It does not establish profitability.

## Venue policy

The radar is venue-agnostic at the interface level.

Pump.fun/PumpSwap is the first high-activity laboratory, but the data model must support Raydium, Meteora and other Solana venues later. Pump origin is never evidence of attractiveness by itself.

Primary discovery preference:

1. Solana on-chain stream as canonical market-event source;
2. Pump bonding-curve and PumpSwap as first venue adapters;
3. provider WebSockets/APIs only as accelerators, enrichment or cross-checks;
4. no required scraping of the Pump.fun UI.

Protocol-freeze program IDs:

- Pump: `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`;
- PumpSwap: `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`.

## Provider policy

Provider use must remain replaceable and bounded.

Potential Birdeye use: meme lifecycle/trading stats, new listings and event-driven trade enrichment when entitlement supports it.

Potential PumpPortal use: new-token/migration streams and controlled per-token trade comparison. Metered trade subscriptions must not become unbounded fan-out.

Native Solana WebSocket/RPC remains the canonical fallback. `confirmed` may be used for early observation only with later finality audit.

## Two-clock causal rule

Every market observation retains:

- `chain_time`: when the market event happened;
- `observed_at`: when our collector actually knew it.

A row can contribute to a T0 feature only when:

1. its market time belongs to the requested market window; and
2. `observed_at <= decision_as_of`.

Backfilled old transactions discovered later cannot masquerade as fresh flow.

## Market movement candidate v1

The detector is intentionally simple and auditable. It is an acquisition trigger, not a trading model.

### Established-market activity acceleration

Frozen acquisition windows:

- fast window: 30s;
- total baseline horizon: 300s;
- comparison baseline: preceding 270s excluding the fast window.

Candidate requirements:

- >=6 causally available trades in the fast 30s;
- >=4 unique known participant wallets in the fast window;
- >=3 events in the preceding 270s baseline;
- fast/prior event-rate >=3.0x.

These thresholds are acquisition mechanics, not claims of optimal profitability.

### Fresh-market burst

If a causal market-start timestamp exists and a 270s baseline does not yet make sense, a token may become a candidate when:

- market age at T0 <=120s;
- >=6 fast-window events;
- >=4 unique participant wallets.

### Direction is descriptive

The radar records pressure but does not require a large price appreciation before firing.

Preferred direction statistic:

- signed notional imbalance when coverage is complete;
- otherwise count imbalance.

Labels:

- `upward_pressure` at >=+20%;
- `downward_pressure` at <=-20%;
- `mixed_pressure` otherwise.

Price movement is descriptive in v1 so the detector is not structurally forced to arrive after a pump already happened.

## Missingness policy

No imputation.

Persist explicit coverage for wallet identity, notional, price, source/venue and observation latency. Metrics that require complete identity/notional coverage stay missing when coverage is incomplete.

## Opportunity episodes

Every market movement candidate is retained as a raw radar trigger.

The first trigger for a token opens an opportunity episode. For 60s after the first trigger's observed time:

- additional movement triggers for the same token/run join the same episode;
- raw triggers remain individually persisted;
- enrichment is not duplicated only because the detector fired again;
- a trigger at exactly +60s opens a new episode.

Different acquisition runs never share an episode.

## Opportunity-native wallet intelligence

There is **no whitelist or frozen set of "good wallets" in the Market Opportunity Radar path**.

The causal order is:

`market movement -> episode -> discover every wallet participating in that episode -> evaluate those wallets with history already resolved before decision_as_of`

The old Discovery/Copyability pipeline remains historical research infrastructure. Its `Copyability Score`, Candidate Score or prior eligibility must not become a hidden admission filter for radar episodes.

For every causally observed participant wallet, Opportunity Wallet Intelligence v1 may attach:

- current BUY/SELL/repetition behavior;
- current notional participation when coverage is complete;
- count of prior episodes already resolved before T0;
- prior unique-token breadth;
- same-token prior episode count;
- prior positive-outcome share where return coverage exists;
- prior mean/median realized return where available;
- prior median holding time where available;
- history coverage and sample-size quality flags.

Critical rules:

- a previously unknown wallet is still a valid participant;
- unresolved history remains missing, not negative;
- a historical outcome that only resolves after current T0 cannot be used;
- the current episode itself cannot leak into "prior competence" evidence;
- no `wallet_score`, `passed`, `recommended` or BUY decision exists in wallet intelligence v1;
- a wallet that looked strong historically can still be contradicted by current flow/risk/execution evidence;
- a wallet with no history does not invalidate the opportunity.

The research question is not "is this a good wallet?" but:

> Given that this wallet is participating in this specific market opportunity, what evidence about its behavior was already knowable, and does that evidence add incremental value when crossed with the rest of the T0 state?

Implementation contract:

- `src/opportunity_wallet_intelligence.py`
- `tests/test_opportunity_wallet_intelligence.py`
- `docs/opportunity-wallet-intelligence-v1-design-2026-09-03.md`

## T0 evidence families

Each episode should eventually freeze one evidence bundle at `decision_as_of` containing the evidence that was actually available by that time.

Priority families:

1. **market movement/lifecycle** — acceleration, pressure, market age;
2. **execution/tradability** — Jupiter causal quote, route, price impact, latency, liquidity metadata;
3. **order flow/microstructure** — buy/sell counts, rates, imbalance, breadth, repeated participants, price response;
4. **dynamic wallet intelligence** — behavior/history of the wallets actually inside this episode;
5. **basic token/hazard risk** — causal authority/liquidity/concentration/route-deterioration signals where available;
6. **network/market regime** — Solana priority-fee/congestion and later broader regime context.

Initial research notional remains US$25 for continuity with Wallet Forward v2.

`decision_as_of` must include the time spent obtaining mandatory features. The system may never pretend provider responses were known at the original radar-detection instant.

## Outcomes

Outcomes are separate labels and never enter T0 features.

Initial horizons:

- +5m;
- +15m;
- +60m.

Where possible use the same route-aware execution-proxy semantics as T0. Missing quotes remain missing.

## Run gate

Do **not** start the 12h acquisition run until:

- detector tests pass;
- market observation/episode stores pass;
- Opportunity Wallet Intelligence causal tests pass;
- at least one native/provider stream smoke demonstrates real timestamps and reconnect behavior;
- provider cost/burst behavior is bounded;
- a short end-to-end smoke proves `stream -> radar -> episode -> evidence -> decision_as_of` without look-ahead.

Only after those gates may the first 12h acquisition window start.

## DATA-READY targets

Hard integrity requirements:

- zero look-ahead;
- immutable episode IDs and `decision_as_of`;
- raw triggers retained;
- cross-run isolation;
- provider failures/missingness persisted;
- outcomes excluded from features;
- no wallet allowlist used to create/suppress episodes;
- historical wallet evidence only from outcomes already known before T0.

Diversity targets:

- >=30 opportunity episodes;
- >=15 unique tokens;
- broad participant-wallet diversity where identity coverage exists;
- largest token share <=20%;
- >=90% episodes with mandatory timing/identity fields plus at least one usable execution proxy.

Passing DATA-READY validates acquisition quality, not edge.

## Post-acquisition ablations

Once sample quality is adequate, compare at minimum:

1. movement detector only;
2. dynamic wallet evidence only;
3. execution/liquidity only;
4. order flow only;
5. market + wallet;
6. market + flow;
7. wallet + flow;
8. market + execution;
9. market + wallet + execution;
10. all available Core evidence families;
11. risk/regime only when coverage supports fair comparison.

Use time-separated and token/wallet-cluster-aware evaluation.

The purpose is to learn whether wallet competence evidence adds incremental predictive value **inside market-detected opportunities**. It is not to recreate a wallet-copy whitelist.

## Explicit non-rules

The following are not BUY rules:

- 3x acceleration;
- 6 trades/30s;
- 4 wallets/30s;
- Pump.fun origin;
- bonding-curve progress;
- participation by a historically strong wallet;
- absence of a known wallet;
- social attention.

## Stop rules

- no Wallet Forward v2 Run 3;
- no live/shadow promotion from acquisition volume;
- no tuning detector thresholds from first-run P&L;
- no pre-selecting "good wallets" to filter market episodes;
- no unbounded paid subscriptions;
- no social/NLP complexity before Core ablations;
- no proxy quote treated as a fill.

## North star

`market begins to move -> detect causally -> inspect who is actually participating -> cross participant evidence with flow/execution/risk/regime -> freeze decision_as_of -> measure forward capturable outcome`

The project succeeds only if that pipeline eventually demonstrates an out-of-sample, cost-adjusted and realistically executable edge.