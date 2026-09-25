# Post-Transition Pullback / Reacceleration V0 — Discovery Protocol — 2026-09-25

Mode: MARKET-FIRST / DISCOVERY ONLY / PAPER / NO LIVE MONEY

## Scientific question

After a causally observed PumpSwap lifecycle transition for a token with confirmed prior Pump origin,
does the shape of a subsequent pullback and recovery/reacceleration contain useful information about
future route-shadow economics?

This protocol is intentionally different from the failed/parked Launch-Burst selectors. It studies a
later market state instead of stacking another filter on the first five seconds after launch.

## Current status

`OFFLINE_CAUSAL_SCAFFOLD / NO FRESH ECONOMIC OUTCOME OPENED`

Rust Signal Plane V7 remains frozen.

No detector threshold, Launch Burst rule, Participant Quality rule, Sniper rule or Concentration
Decay rule is modified.

## Cohort identity

A future Post-Transition V0 research state requires:

1. directly observed PumpSwap `CreatePoolEvent`;
2. exactly one WSOL/USDC reference asset in the pair;
3. non-reference opportunity token resolved through the frozen PumpSwap asset-role contract;
4. prior Pump token-birth lifecycle causally known no later than transition observation;
5. Pump birth chain time <= PumpSwap transition chain time.

Missing or conflicting lineage is excluded as missing evidence. It is never guessed.

## Transition semantics

PumpSwap CreatePool is a **transition anchor**, not a graduation label.

The research state records:

- pool;
- opportunity mint;
- reference mint;
- pair orientation;
- decimals;
- transition chain time;
- transition local observed time;
- optional confirmed Pump-birth chain/observed clocks.

## Market-observed price proxy

Every raw PumpSwap Buy/Sell event supplies base and quote amounts.

After role normalization, V0 derives:

`event_implied_reference_per_opportunity = reference_units / opportunity_units`

This metric is used only to describe the observed post-transition path.

It is not an executable/provider price and cannot establish routeability or economic PnL.

## Causal path features

At every research snapshot, using only events observed by that exact local as-of clock:

### Lifecycle / timing

- seconds since transition observation;
- seconds since transition chain time;
- trade count available;
- Pump-origin confirmation flag.

### Pullback geometry

- first causally observed post-transition trade ratio as reference;
- current return from reference;
- running peak to date;
- running trough to date;
- running-trough return from reference;
- current drawdown from running peak;
- maximum drawdown observed to date;
- duration from the relevant running peak to the deepest drawdown observed to date;
- current recovery from running trough;
- seconds since running trough.

A "running trough" means the minimum observed **so far**. It is not a future-confirmed local low.

### Flow / participation dynamics

One fixed transform is frozen before economic outcomes:

- recent window: last 10 observed seconds;
- prior window: the preceding 10 observed seconds.

For each window:

- event count/rate;
- buy count/rate;
- sell count/rate;
- unique buy wallets;
- unique sell wallets;
- gross reference-asset flow;
- signed reference-asset flow;
- gross/signed reference-flow rate;
- top-wallet gross-flow share.

Across windows:

- event-rate delta and ratio;
- buy-rate delta and ratio;
- sell-rate delta;
- gross-flow-rate delta and ratio;
- signed-flow-rate delta;
- unique-buy-wallet delta;
- top-wallet-concentration delta.

No alternative window is promoted from this discovery sample.

## Structural research marker

V0 exposes one **diagnostic research marker**, not a BUY/SKIP selector:

`structural_reacceleration_candidate = true`

only when all are already true at the snapshot:

1. a negative pullback from the first post-transition reference trade has already been observed;
2. current observed ratio is above the running trough already known;
3. both the prior and recent 10-second flow windows contain at least one observed event;
4. recent signed reference-flow rate exceeds the prior signed reference-flow rate.

This marker has no magnitude threshold and carries no profitability claim.

Its purpose is to identify a causally auditable state worth describing during discovery.

It must not be called a validated signal.

## Anti-leakage invariants

V0 must prove:

- snapshot filtering by the exact local `(observed_at, arrival_index)` boundary;
- later arrivals in the same wall-clock second cannot leak into an earlier snapshot;
- future trades cannot alter a recomputed earlier snapshot;
- future minimum/maximum is never used;
- transition identity is exact by pool;
- ambiguous asset role fails closed;
- reversed reference/token orientation normalizes price and side correctly;
- trade before transition is rejected;
- conflicting duplicate event identity is rejected;
- replay order does not change the snapshot for one fixed as-of;
- historical Pump lifecycle lookup is causal and ambiguity returns missing;
- provider quotes are absent from feature construction;
- outcomes are absent from feature construction.

## Economic labels — frozen before opening outcomes

When this line reaches fresh economic discovery, route-shadow labels stay separate from the market
features.

Primary future label:

`fixed +60s route-shadow net return`

Rationale: current Solana route-paper infrastructure already has a frozen +60s contract and the
post-transition reacceleration state is intended to detect fast continuation/recovery.

Exploratory secondary label:

`+300s route-shadow return`

Rationale: a later-state recovery can persist longer than the initial Launch Burst. +300s is reported
only as exploratory context and cannot replace +60s as primary based on results.

The existing US$25 notional, fees, adverse slippage, route-quality and unexitable-return semantics
must be reused when the economic collector is wired.

No economic outcomes are opened by the offline scaffold in this commit.

## Discovery promotion rule

Fresh discovery may describe associations between frozen causal V0 features and the separately
collected +60s/+300s outcomes.

It may not:

- threshold-sweep pullback magnitude;
- threshold-sweep recovery magnitude;
- threshold-sweep flow acceleration;
- optimize the 10s window;
- combine Participant Quality/Sniper/Concentration outcomes;
- promote the best subgroup on the same sample;
- call the structural marker edge.

If discovery suggests one simple auditable rule, that rule must be reduced to one separately
preregistered hypothesis and evaluated on a new holdout.

## Validation sequence

1. synthetic offline fixture;
2. targeted unit/anti-leakage tests;
3. full repository CI;
4. systems-only live probe with provider economic calls disabled;
5. fresh discovery capture;
6. outcome-blind candidate reduction;
7. separate preregistered holdout;
8. independent replication before any mature-edge claim.

Live economic collection is not authorized by this protocol revision.

## Frozen discovery decision snapshot — amendment before outcomes

This amendment is frozen after the systems-only PASS and before any Post-Transition V0 economic
outcome is opened.

Each causally eligible transition receives exactly one discovery decision snapshot at:

`transition_observed_at + 30 seconds`

Rationale:

- V0 already froze two adjacent 10-second flow windows;
- +30s provides causal room for both windows plus initial post-transition path formation;
- one fixed checkpoint avoids repeated correlated provider labels per token;
- the checkpoint is frozen before any economic outcome from this research line exists.

Eligibility at the +30s checkpoint:

1. direct PumpSwap CreatePool was observed;
2. opportunity/reference asset role is unambiguous;
3. prior Pump birth for the opportunity mint is causally known by transition observation;
4. Pump birth chain time is not after the PumpSwap transition;
5. at least one post-transition trade is causally available by +30s.

No structural feature is a selector. In particular:

`structural_reacceleration_candidate`

is recorded as a diagnostic feature but does not determine who receives an economic label.

All complete lineage-eligible +30s snapshots receive the same frozen labels:

- primary: fixed +60s route-shadow net return from entry;
- exploratory: fixed +300s route-shadow net return from entry.

Provider calls start only after the immutable +30s feature snapshot is frozen.

Primary/exploratory roles cannot be swapped after results.
