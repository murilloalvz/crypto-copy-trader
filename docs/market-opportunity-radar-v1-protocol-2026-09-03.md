# Market Opportunity Radar v1 — Preregistered Acquisition Protocol

Date: 2026-09-03

Mode: **PRE-REGISTERED / PAPER / RESEARCH / READ ONLY / NO LIVE EXECUTION**

Status: supersedes `docs/causal-opportunity-acquisition-v1-protocol-2026-09-03.md` **before any acquisition run was started**.

## Why the trigger is changing

Wallet Forward v2 established that the collector, causal boundary, Jupiter quote path, finality audit and quantity-aware replay can work prospectively. It did not establish a wallet-only edge: across two 10h windows only four BUYs entered the frozen economic sample, with three of four in one wallet×token cluster.

The failure mode is therefore not merely model quality. The old design waits for a small wallet set while the Solana token market continues producing many independent movements.

The next acquisition gate changes the trigger from:

`selected wallet BUY -> token`

into:

`market activity changes state -> token -> opportunity episode`

Wallet activity remains an important feature and possible confirmation channel, but **wallet identity is no longer required to create an opportunity**.

## Research question

> Can the project detect early, causally observable changes in token-market activity, persist them as independent opportunity episodes, and enrich them with execution, flow, wallet, risk and regime context without look-ahead?

Passing this gate validates data acquisition. It does not establish profitability.

## Venue policy

The radar is **venue-agnostic at the interface level**.

Pump.fun/PumpSwap is the first high-activity laboratory, but the data model must also be able to represent Raydium, Meteora and other Solana venues later.

No rule may assume that a token is attractive merely because it originated on Pump.fun.

## Canonical discovery surface

Primary design preference:

1. **Solana on-chain stream** as the canonical source of market events;
2. official Pump program activity and PumpSwap activity as the first venue adapters;
3. provider WebSockets/APIs only as accelerators, enrichment or cross-checks.

Relevant public Pump program IDs at protocol-freeze time:

- Pump bonding-curve program: `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`;
- PumpSwap AMM program: `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`.

The implementation must not scrape the Pump.fun user interface as a required data source.

## Provider policy

Provider use must remain replaceable.

### Birdeye

Potential uses:

- `SUBSCRIBE_MEME` for real-time meme lifecycle/trading stats;
- new pair / new listing streams;
- token transaction streams;
- REST trade data for event-driven enrichment.

Because WebSocket access depends on package entitlement, Birdeye cannot be the only acquisition path until the user's actual entitlement is verified.

### PumpPortal

Potential uses:

- new-token stream;
- migration stream;
- per-token trade streams for controlled comparison.

Its trade streams are third-party and metered. They must not become an unbounded subscription fan-out.

### Solana RPC

Native WebSocket/RPC remains the preferred canonical fallback because it observes on-chain program activity directly. `confirmed` may be used for early observation only when the run retains a later finality audit.

## Two-clock causal rule

Every market observation must retain:

- `chain_time`: when the event happened in the market;
- `observed_at`: when our collector actually knew the event.

A row can contribute to a T0 feature only when:

1. its `chain_time` belongs to the relevant market window; and
2. its `observed_at <= decision_as_of`.

Backfilled old transactions discovered later are not allowed to masquerade as fresh flow.

## Market movement candidate v1

The first detector is deliberately simple and auditable. It is a **data-acquisition trigger**, not a trading model.

### Established-market activity acceleration

Default windows:

- fast window: **30 seconds**;
- baseline horizon: **300 seconds** total;
- baseline comparison segment: the preceding **270 seconds**, excluding the fast 30s window.

A token becomes an `activity_acceleration` candidate when all are true:

- at least **6** causally available trade events in the fast 30s window;
- at least **4** unique known participant wallets in that fast window;
- at least **3** events in the preceding 270s baseline segment;
- fast event-rate / prior baseline event-rate >= **3.0x**.

These are frozen acquisition thresholds. They are not claims of optimal profitability and must not be tuned after seeing forward returns from the first acquisition window.

### Fresh-market burst

New markets often do not have a valid 270s baseline. When a causal market-start timestamp is available, a token may instead become a `fresh_market_burst` candidate when:

- market age at T0 is <= **120 seconds**;
- at least 6 fast-window events are observed;
- at least 4 unique participant wallets are observed.

This branch prevents new launches from being excluded solely because a historical baseline cannot yet exist.

### Direction is descriptive

The radar records direction but does not use price appreciation as a mandatory trigger.

Preferred direction statistic:

- signed notional imbalance when notional coverage is complete;
- otherwise count imbalance.

Labels:

- `upward_pressure` when imbalance >= +20%;
- `downward_pressure` when imbalance <= -20%;
- `mixed_pressure` otherwise.

Price change is descriptive only in v1. This is intentional: requiring a large price move before triggering would systematically detect tokens after the move has already occurred.

## Missingness policy

No imputation.

Persist explicit coverage for:

- wallet/participant identity;
- notional;
- price;
- source/venue;
- observation latency.

If wallet identity coverage is incomplete, participant concentration metrics that require complete identity must remain missing rather than being calculated on a selected subset.

## Opportunity episodes

Every market movement candidate is persisted as a raw radar trigger.

The first trigger for a token opens an opportunity episode.

For **60 seconds after the first trigger's observed time**:

- additional movement triggers for the same token and acquisition run join the same episode;
- raw triggers remain individually persisted;
- provider enrichment is not duplicated solely because the detector fired repeatedly;
- at exactly +60s, a new trigger opens a new episode.

Different acquisition runs can never share an episode.

## Wallet intelligence after the trigger

Wallets are now context, not prerequisites.

At or before `decision_as_of`, the episode may attach:

- whether one of the previously researched wallets participated;
- number of researched wallets participating;
- broader unique-wallet participation;
- known wallet fingerprint metadata computed only from information available before T0;
- repeated-wallet/concentration features.

A market episode with zero tracked-wallet participation remains a valid observation.

## Core T0 enrichment

Priorities:

1. **execution / tradability** — Jupiter causal quote for the research notional;
2. **order flow / microstructure** — counts, rates, imbalance, breadth, repeated participants;
3. **basic token/lifecycle risk** — causal authority/liquidity/lifecycle fields when available;
4. **wallet context** — tracked-wallet participation and independence;
5. **network regime** — recent Solana priority-fee/congestion context.

Initial research notional remains **US$25** for continuity with Wallet Forward v2.

`decision_as_of` must include the time spent obtaining mandatory features. The model is never allowed to pretend that provider responses were available at the original detection instant.

## Outcomes

Outcomes are stored separately and never enter T0 features.

Initial forward horizons:

- +5m;
- +15m;
- +60m.

Where possible use the same route-aware execution-proxy semantics as T0. Missing quotes remain missing.

## First run length

Do **not** start a long run until:

- pure detector tests pass;
- episode-store tests pass;
- at least one provider/native stream smoke test demonstrates real timestamps and reconnect behavior;
- provider cost/burst behavior is bounded.

After those gates, the first acquisition window remains **12 hours**.

## Data-readiness targets

The first 12h window is DATA-READY only if integrity passes and sample diversity is adequate.

Integrity:

- zero look-ahead violations;
- immutable episode IDs;
- immutable `decision_as_of`;
- raw triggers retained;
- cross-run isolation;
- provider failures/missingness persisted;
- outcomes excluded from features.

Diversity targets:

- >= **30 opportunity episodes**;
- >= **15 unique tokens**;
- >= **5 distinct participant/source-wallet identities** where identity coverage exists;
- largest token share <= **20%**;
- >=90% episodes with identity/timing fields plus at least one usable execution proxy.

The old `largest tracked source-wallet <=50%` gate is removed because a tracked wallet is no longer required to create an episode.

## What is explicitly NOT frozen as an economic rule

The following are not BUY rules:

- 3x activity acceleration;
- 6 trades/30s;
- 4 wallets/30s;
- Pump.fun origin;
- bonding-curve progress;
- tracked-wallet participation;
- social attention.

They are acquisition mechanics/features whose predictive value must be tested later.

## Post-acquisition ablations

Once sample quality is adequate, compare at minimum:

1. movement detector only;
2. execution/liquidity only;
3. order flow only;
4. wallet context only;
5. movement + execution;
6. movement + order flow;
7. movement + wallet context;
8. execution + order flow;
9. all Core families;
10. risk/regime added only when coverage supports them.

Use time-separated and token/wallet-cluster-aware evaluation.

## Stop rules

- no Wallet Forward v2 Run 3;
- no live/shadow promotion from acquisition volume;
- no tuning detector thresholds using the first run's P&L;
- no unbounded paid provider subscriptions;
- no social/NLP complexity before Core ablations;
- no proxy quote treated as fill;
- no Pump.fun-specific success metric treated as executable return.

## North star

`market begins to move -> detect causally -> explain the movement with flow/execution/risk/wallet/regime -> freeze decision_as_of -> measure forward capturable outcome`

The project succeeds only if that pipeline eventually demonstrates an out-of-sample, cost-adjusted and realistically executable edge.