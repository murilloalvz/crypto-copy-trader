# Native Participant Quality Prospective Holdout V1 — Preregistration — 2026-09-24

Mode: PAPER / RESEARCH / PROSPECTIVE / NO LIVE MONEY

## Scientific state before fresh collection

Participant Quality Memory V1 completed four role-normalized memory cohorts and returned
`READY_TO_PREREGISTER_NATIVE_PARTICIPANT_QUALITY_HOLDOUT`.

Frozen memory lineage:

- `participant-quality-native-memory-rolefix-20260924-03-M1`
- `participant-quality-native-memory-rolefix-20260924-03-M2`
- `participant-quality-native-memory-rolefix-20260924-03-M3`
- `participant-quality-native-memory-rolefix-20260924-03-M4`

Frozen feature:

`native_participant_prior_900_route_quote_return_median_of_wallet_medians_pct`

Frozen cutoff:

`-65.65233776856643`

Frozen favorable direction:

`HIGH`

Group assignment is immutable:

- HIGH: feature > cutoff
- LOW: feature <= cutoff
- missing feature: unclassified, never zero and never imputed

The cutoff was the outcome-blind median of available M2-M4 memory feature values. No holdout
economic outcome existed when this rule was frozen.

## Causal feature contract

For every holdout episode, Participant Quality is computed at the episode/decision causal clock using
only route-research history from the four frozen memory cohorts above.

Holdout H1/H2 episodes and outcomes are never added to the feature history used to classify another
holdout episode. This deliberately freezes the information base for a clean prospective test.

Same-token prior episodes remain excluded. Prior 900-second outcomes and their SELL quote must have
been known strictly before current T0. Missing history remains missing.

## Fresh acquisition

Exactly two prospective cohorts are authorized:

- H1
- H2

Each cohort uses:

- 120-second acquisition;
- maximum 40 selected episodes;
- minimum 30 route-research decisions;
- route-only BUY notional: USD 25;
- route-only slippage: 100 bps;
- hazard start pacing: 650 ms;
- entry start pacing: 1000 ms;
- primary economic horizon: 900 seconds.

Each cohort must independently pass the V7 Signal Plane -> Research Plane -> route-research bridge,
have exact 300/900/3600 schedule accounting, and complete the existing 300/900 forward collector.

A technical/acquisition failure produces INCONCLUSIVE and does not authorize threshold changes.

## Primary economic label

Current episode return is the route-only quote-to-quote 900-second return:

`100 * (900s SELL quote price / causal entry BUY quote price - 1)`

Only AVAILABLE non-executable route quotes with valid causal clocks are labeled. Provider errors,
missing quotes, invalid clocks and invalid prices remain unavailable; they are never converted to
zero or losses.

## Support gates

Before any economic KEEP/KILL verdict:

1. feature coverage >= 50% in H1 and H2;
2. at least 40 paired feature+900s outcomes aggregate;
3. at least 15 HIGH paired outcomes aggregate;
4. at least 15 LOW paired outcomes aggregate;
5. at least 5 HIGH and 5 LOW paired outcomes in each H1 and H2.

If any support gate fails, classification is
`INCONCLUSIVE_NATIVE_PARTICIPANT_QUALITY_HOLDOUT_SUPPORT`.

No automatic H3 is authorized.

## Frozen effect gates

If support is sufficient, every effect gate below must pass:

1. aggregate Spearman(feature, 900s return) > 0;
2. aggregate HIGH median return > aggregate LOW median return;
3. HIGH median return > LOW median return separately in H1 and H2;
4. aggregate HIGH mean-without-best > aggregate LOW mean-without-best;
5. aggregate HIGH profit factor > aggregate LOW profit factor;
6. aggregate HIGH catastrophic-loss rate <= aggregate LOW catastrophic-loss rate.

Catastrophic loss threshold is frozen at -80%, matching the project's existing Burst diagnostic
convention.

These are directional gates; no post-fresh threshold search, subgroup search, cutoff movement,
direction flip, alternative horizon promotion or combination rescue is permitted.

## Verdicts

All support + all effect gates PASS:

`KEEP_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`

Support PASS but any effect gate FAIL:

`KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`

Technical or support insufficiency:

`INCONCLUSIVE...`

KEEP is not mature edge. It authorizes only a separately preregistered independent replication.
It does not authorize live-money execution.

## Forbidden after fresh starts

- moving the cutoff;
- changing HIGH to LOW;
- adding H3 because H1/H2 are inconvenient;
- using 300s or 3600s as replacement primary horizons;
- adding holdout episodes to their own feature-history pool;
- missing=zero or provider-error=loss;
- threshold sweeps or subgroup rescue;
- calling memory readiness or a single favorable metric edge;
- live-money execution.
