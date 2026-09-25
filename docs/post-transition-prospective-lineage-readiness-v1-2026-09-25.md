# Post-Transition Prospective Lineage Readiness V1 — Amendment — 2026-09-25

Mode: SYSTEMS / RESEARCH READINESS / NO ECONOMIC OUTCOME

## Motivation

Research Readiness V0 observed four role-valid direct PumpSwap transitions, all with
`pump_lineage_missing`.

The local DB had not been prospectively accumulating Pump CreateEvent births before those
transitions.

## Amendment

V1 subscribes to Pump and PumpSwap on one ordered Solana WebSocket connection.

Subscriptions:

1. Pump program logs;
2. PumpSwap program logs.

Pump CreateEvents are persisted immediately as venue `pump_bonding_curve` with their true local
observation second.

A PumpSwap transition may use that lineage only if the birth is already present when the transition
notification is processed.

Historical backfill is forbidden.

## Strict local clock rule

The lifecycle store currently records local availability at one-second resolution.

Therefore a birth is lineage-eligible only when:

`birth_observed_at < transition_observed_at`

not merely `<=`.

If both local observations fall in the same second, the order cannot be reconstructed safely from the
persisted lifecycle row alone and V1 classifies it:

`SAME_SECOND_UNRESOLVED`

It is excluded fail-closed.

Chain chronology also requires:

`birth_market_started_at <= transition_chain_time`

## Frozen research contract unchanged

V1 does not change:

- Post-Transition V0 feature definitions;
- two fixed 10-second flow windows;
- transition +30s decision snapshot;
- one decision snapshot per transition;
- no selector predicates during discovery;
- structural-reacceleration marker remains diagnostic only;
- +60s primary future route-shadow label;
- +300s exploratory future label;
- US$25 route-paper semantics;
- Rust Signal Plane V7.

## PASS meaning

`PASS_POST_TRANSITION_PROSPECTIVE_LINEAGE_READINESS_V1`

requires at least one real causal chain:

`Pump birth observed -> later PumpSwap CreatePool observed -> post-transition trade -> immutable +30s snapshot`

with a valid snapshot hash chain.

PASS is still systems/readiness evidence only.

It does not authorize live money or claim edge.

## INCONCLUSIVE meaning

If no complete causal lineage reaches the +30s snapshot during the fixed observation window, the
result is INCONCLUSIVE.

Do not backfill, weaken the clock rule, change +30s or promote a partial transition.
