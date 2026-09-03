# Market Opportunity Radar v1 — Design Freeze

Date: 2026-09-03

Mode: **PAPER / RESEARCH / READ ONLY**

## Design decision

The market, not a selected wallet, becomes the primary acquisition trigger.

Pipeline:

`market activity changes state -> radar trigger -> token opportunity episode -> execution + flow + risk + wallet + regime context -> decision_as_of -> forward outcomes`

Tracked wallets remain features. An episode with zero tracked-wallet participation is valid.

## Why

Wallet Forward v2 validated the causal/runtime infrastructure but produced only four enrolled BUYs across two 10h windows, with strong wallet×token dependence. The bottleneck is sample acquisition and diversity.

## Evidence basis

- Pump publishes public on-chain programs for bonding-curve trading and PumpSwap, making on-chain activity a canonical integration surface rather than UI scraping.
- Solana provides WebSocket subscriptions for program/log activity, allowing event-driven observation.
- Birdeye exposes real-time meme stats, listings, pairs and transaction streams when package entitlement supports WebSockets.
- PumpPortal exposes new-token/migration streams and metered token/account trade streams; it is useful as an optional provider, not a sole dependency.

## Detector contract

The pure detector in `src/market_opportunity_radar.py` uses two clocks:

- `chain_time`: market time;
- `observed_at`: local availability time.

Established-market trigger:

- fast window 30s;
- preceding baseline segment 270s inside a 300s horizon;
- >=6 fast events;
- >=4 unique known wallets;
- >=3 baseline events;
- fast/baseline event-rate acceleration >=3x.

Fresh-market trigger:

- causal market age <=120s;
- >=6 fast events;
- >=4 unique known wallets.

Direction is descriptive only. Price appreciation is not a hard trigger.

## Episode contract

`src/market_opportunity_episode_store.py` persists raw market triggers independently of tracked-wallet presence.

- same run + same token + trigger before +60s => same episode;
- trigger exactly at +60s => new episode;
- different acquisition runs never share an episode;
- `decision_as_of` freezes once;
- raw triggers can be loaded with a causal availability cutoff.

## Source strategy

Preferred order:

1. native Solana/Pump on-chain adapter;
2. optional provider cross-check/enrichment;
3. Jupiter execution proxy;
4. wallet intelligence attached after market trigger.

No paid provider fan-out is authorized by this design alone.

## Next implementation gate

Before a 12h acquisition run:

1. CI for pure radar + episode store;
2. native/provider adapter contract;
3. short real stream smoke test;
4. reconnect/duplicate/clock audit;
5. bounded cost/rate behavior;
6. only then freeze a runnable acquisition orchestrator.

Passing those steps validates acquisition infrastructure, not economic edge.