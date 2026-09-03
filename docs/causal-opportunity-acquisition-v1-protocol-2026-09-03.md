# Causal Opportunity Acquisition v1 — Preregistered Protocol

Date: 2026-09-03

Mode: **PRE-REGISTERED / RESEARCH / READ ONLY / NO LIVE EXECUTION**

Status: protocol design only. Do not start the acquisition run until the implementation and its tests pass.

## Why this gate exists

Wallet Forward v2 produced a technically valid but economically tiny sample: four enrolled BUYs across two independent 10h windows, all in Run 1, with three of the four belonging to one wallet×token cluster.

The next gate therefore targets **sample acquisition and causal context**, not profitability optimization.

The goal is to answer:

> Can the project collect a diverse set of wallet-triggered opportunity episodes while preserving the exact information availability timeline needed for later execution-aware modeling?

A pass does **not** mean a strategy has edge.

## Core methodological change

Wallets remain a low-cost causal trigger source, but they are no longer treated as automatically copyable signals.

The acquisition object becomes:

`wallet BUY trigger -> opportunity episode -> causal context -> decision_as_of -> execution proxy -> forward outcome labels`

Future models may learn that some wallets are useful, neutral or negative features.

## Frozen trigger universe

Use the already-existing public research universe:

`wallets/research-cohort-public-v2-2026-09-02.txt`

Expected frozen size: 27 addresses.

All 27 may generate observation triggers in this acquisition protocol regardless of prior copyability eligibility. Prior eligibility/fingerprint fields may be attached as metadata, but they must not suppress an event because of outcome information.

This is an observation universe, not a copy portfolio.

## Trigger definition

A raw trigger is a newly observed supported on-chain **BUY/swap into a token** from any frozen source wallet after the acquisition baseline.

Every raw trigger is persisted, including repeated buys.

No trigger is deleted because another wallet/token event looks more attractive.

## Opportunity episode definition

Provider enrichment is event-driven rather than continuously polling every token.

The first raw BUY trigger for a token opens an opportunity episode.

For **60 seconds after the first trigger's `observed_at`**:

- additional BUY triggers for the same token are attached to the same episode;
- all raw wallet actions remain individually persisted;
- repeated triggers may contribute convergence/concentration features;
- external enrichment is not duplicated solely because another wallet bought the same token during that 60s episode window.

After 60 seconds, a new trigger for that token may open a new episode.

The 60s rule is a data-acquisition deduplication rule, not a trading cooldown and not an economic threshold.

## Required clocks

Each episode must preserve at least:

- `chain_time`: market/event time of the trigger;
- `trigger_observed_at`: when the local collector learned of it;
- per-source `requested_at` when applicable;
- per-source `observed_at` / response completion time;
- `decision_as_of`: the latest availability timestamp among the mandatory features used by the decision snapshot.

Market-window features use event/market timestamps to define what happened in the market and availability timestamps to prove the data was known by `decision_as_of`.

No feature may use a row merely because its market timestamp is old enough; it must also have been observed before the snapshot cutoff.

## Opportunity Snapshot Core v1

The first acquisition version focuses on low-cost, evidence-backed feature families.

### 1. Wallet action state

Required where causally available:

- source wallet;
- token mint;
- BUY quantity / observed balance transition;
- scale-in/reentry indication;
- trigger chain-to-detection lag;
- source venue/program;
- prior wallet fingerprint/eligibility metadata computed only from information available before the event.

### 2. Execution / tradability

At `decision_as_of`, capture a read-only execution proxy for the research notional.

Initial research notional remains **US$25** for continuity with Wallet Forward v2.

Persist when available:

- quote price;
- route/provider;
- output amount;
- route availability;
- price impact/slippage metadata;
- request/response latency;
- executable vs proxy flag.

No quote is treated as a realized fill.

### 3. Order flow / microstructure

Target windows:

- 10s;
- 30s;
- 60s;
- 300s.

Candidate fields include:

- BUY count;
- SELL count;
- BUY/SELL notional where covered;
- unique BUY wallets;
- unique SELL wallets;
- repeated-wallet share;
- signed flow imbalance;
- trade velocity;
- price return within the window;
- coverage/missingness for wallet, price and notional fields.

A trade contributes to a market window only if its event time is inside that window **and** it was available by the snapshot cutoff.

### 4. Network regime

Capture a causal Solana congestion/fee context when available, including recent priority-fee conditions.

Missing network-regime data remains explicit.

### 5. Basic token risk

Only cheap causal fields may enter Core v1. No synthetic risk score is allowed.

Examples that may be attached when reliably available before `decision_as_of`:

- mint/freeze authority state;
- holder or early-flow concentration fields;
- abrupt liquidity/route unavailability flags.

If a field cannot be collected causally and reliably, it stays missing rather than being backfilled from the future.

## Explicitly deferred from acquisition v1

The first acquisition gate does not require:

- X/Twitter API;
- generic sentiment;
- LLM narrative scoring;
- Telegram/Discord scraping;
- Google Trends;
- image/meme semantics;
- Pump.fun-only rules that cannot generalize across venues;
- deep learning;
- automatic trading score.

These may be tested later only for incremental value.

## Outcome-label collection

Outcome labels are not features and are never available to the T0 decision snapshot.

For research only, collect forward execution-proxy observations after `decision_as_of` at:

- +5 minutes;
- +15 minutes;
- +60 minutes.

When possible, outcome observations use the same research notional and route-aware quote semantics as the entry proxy.

These labels are stored separately from features and are only joined during offline evaluation.

Missing outcome quotes remain missing; no candle or later quote is substituted silently.

## Initial acquisition window

Initial validation run target: **12 hours**.

The 12h window is an acquisition/infrastructure gate, not a profitability experiment.

If the data-quality sample target is not met, exactly one second 12h window may be run under the same frozen protocol before redesigning the trigger universe or episode logic.

No parameter tuning is allowed between those two windows.

## Acquisition-quality gate

A 12h acquisition window is considered **DATA-READY** only if all integrity requirements pass and diversity is sufficient for later exploratory ablation.

Hard integrity requirements:

- zero look-ahead violations;
- zero feature rows with `observed_at > decision_as_of` used as T0 features;
- every raw trigger retains source wallet, mint, chain time and observed time;
- every episode has an immutable identifier and frozen `decision_as_of`;
- provider failures/missingness are persisted rather than silently dropped;
- cross-run lineage is blocked;
- outcome labels are excluded from feature construction.

Diversity targets for the initial gate:

- at least **30 opportunity episodes**;
- at least **15 unique tokens**;
- at least **5 active source wallets**;
- largest source-wallet share <= **50%** of episodes;
- largest token share <= **20%** of episodes.

Coverage target:

- >= **90%** of episodes have the mandatory identity/timing fields plus at least one usable execution proxy at `decision_as_of`.

These thresholds decide whether the acquisition pipeline is sufficiently diverse to proceed to a larger research sample. They do not decide BUY/SELL behavior and do not establish edge.

## If the first window fails

### Infrastructure failure

Fix infrastructure only. Do not change economic definitions or trigger universe in the same evidence record.

### Low activity / insufficient diversity

Run one independent second 12h window with the exact same frozen protocol.

If both windows remain below the acquisition-quality targets, stop and preregister a new trigger-universe design.

### Provider coverage failure

Keep raw wallet triggers. Diagnose provider availability/cost/latency separately. Do not delete episodes lacking enrichment.

## Evaluation after DATA-READY

If this gate passes, the next analysis is feature ablation and target feasibility, not live trading.

At minimum compare:

1. wallet identity/action only;
2. execution/liquidity only;
3. order flow only;
4. wallet + execution;
5. wallet + order flow;
6. execution + order flow;
7. wallet + execution + order flow;
8. add token-risk/regime fields only when coverage supports them.

Use cluster-aware and time-separated evaluation. Repeated events from the same wallet/token/episode are not independent observations.

## Stop rules

After this protocol is frozen:

- do not launch Wallet Forward v2 Run 3 as a substitute;
- do not retune the old 3-wallet cohort based on Run 1 returns;
- do not add social/Pump-specific logic merely to increase complexity;
- do not promote shadow/live from acquisition metrics;
- do not call a model successful from accuracy alone;
- do not treat proxy quotes as fills.

## North star

The acquisition system is successful only if it creates enough causally clean, diverse observations to test this future question:

> Given only information truly available by decision time, can we estimate cost-adjusted, realistically capturable forward opportunity while rejecting hazardous/untradeable states?
