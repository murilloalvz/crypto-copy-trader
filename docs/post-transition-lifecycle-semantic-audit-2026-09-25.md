# Post-Transition Pullback / Reacceleration V0 — Lifecycle Semantic Audit — 2026-09-25

Mode: MARKET-FIRST / PAPER / RESEARCH / NO LIVE MONEY

## Scope

This audit answers one narrow question before opening a new economic hypothesis:

Can the current Solana plumbing causally represent

`Pump token birth -> PumpSwap lifecycle transition -> post-transition trades`

without calling the transition a Pump.fun graduation unless that equivalence is actually evidenced?

## Findings

### Pump token birth

`src/pump_bonding_stream.py` decodes Pump `CreateEvent` and persists:

- token mint;
- bonding-curve identity;
- creator/user;
- event timestamp;
- local observation time.

The market lifecycle adapter stores this event as venue `pump_bonding_curve`.

Within this repository, that is the strongest native causal token-birth anchor.

### PumpSwap lifecycle transition

`src/pumpswap_stream.py` decodes PumpSwap `CreatePoolEvent` with:

- pool address;
- creator;
- base mint;
- quote mint;
- base decimals;
- quote decimals;
- event timestamp.

The raw stream learns the event at a separate local `observed_at`.

This is a valid causal **PumpSwap pool-creation / lifecycle-transition anchor**.

### PumpSwap trade identity

PumpSwap Buy/Sell events expose:

- pool;
- user;
- timestamp;
- base amount;
- quote amount.

They do not directly contain the pair mints. Existing pool identity logic therefore requires a
causally known CreatePool mapping or later RPC hydration. Hydration availability is never backdated.

For Post-Transition V0, a transition state begins only from a directly observed CreatePoolEvent.
This avoids using later RPC hydration to invent an earlier transition.

### Asset role

PumpSwap event side is expressed relative to the pool base asset.

The opportunity token is **not always the base mint**. The existing
`src/pumpswap_asset_role.py` contract identifies the non-reference asset only when exactly one side
is WSOL or USDC and inverts Buy/Sell semantics when the opportunity token is the quote side.

Post-Transition V0 uses that role contract and fails closed for ambiguous pairs.

### Graduation claim

No reviewed repository contract proves that every PumpSwap CreatePoolEvent is necessarily the
canonical completion/graduation of a Pump bonding curve.

The event proves:

`a PumpSwap pool for this pair was created and became locally known at this time`.

It does **not** by itself prove:

`this token just graduated from Pump.fun`.

Therefore V0 uses the terms:

- `transition`;
- `post-transition`;
- `PumpSwap pool creation`.

The terms `graduation` and `post-graduation` remain forbidden until a separate semantic proof
links the observed Pump lifecycle to the specific PumpSwap creation event.

## Cross-run Pump origin

The existing market lifecycle table is run-scoped. A token may be born in one acquisition run and
create a PumpSwap pool in a later run.

Post-Transition V0 adds a read-only historical lifecycle lookup:

`load_known_market_lifecycle(...)`

It returns a lifecycle only when all causally available historical rows agree on
`market_started_at + venue`.

Conflicting historical identities fail closed to missing.

This does not alter Signal Plane, detector, Rust V7, persistence ordering or economic selection.

## Event-implied market ratio

CreatePool provides pair decimals and each PumpSwap trade provides base/quote raw amounts.

For unambiguous reference pairs, V0 can derive:

`reference_asset_units / opportunity_token_units`

for each observed swap.

This is called:

`event_implied_reference_per_opportunity`.

It is a market-observed swap ratio. It is **not**:

- USD price;
- executable Jupiter quote;
- guaranteed mid-price;
- route availability;
- a fill guarantee.

Provider route evidence remains outside selector features.

## Causal clocks

Every V0 snapshot is keyed by a local causal boundary:

`(as_of_observed_at, as_of_arrival_index)`.

The arrival index preserves collector order for events learned inside the same one-second wall-clock
bucket. An event contributes only if it is before that exact boundary.

The transition is unavailable before its CreatePool local observation time.

Price path, running peak, running trough, drawdown, recovery and flow dynamics are all reconstructed
only from events causally available by that snapshot.

A later-arriving older-chain-time event cannot rewrite a previously emitted snapshot when that old
snapshot is recomputed at its original as-of time.

## Decision

Current native infrastructure is sufficient for an **offline causal discovery model** and a later
systems-only live probe.

It is not yet evidence of economic edge.

The V0 research name is frozen as:

`POST_TRANSITION_PULLBACK_REACCELERATION_V0`

not `POST_GRADUATION...`.
