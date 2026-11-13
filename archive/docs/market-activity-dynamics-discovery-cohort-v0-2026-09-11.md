# Market Activity Dynamics — Fresh Discovery Cohort V0

Status: **PREREGISTERED / NO OUTCOMES INSPECTED**

This protocol defines the first fresh discovery cohort for `market_activity_dynamics_v0_discovery`.
It is discovery-only. It does not define a trading rule, score, recommendation, threshold, or holdout claim.

## Scientific question

Does the shape of causally available Market-First activity at frozen T0 — level, velocity/acceleration proxies, notional dynamics when fully observed, and participant structure — contain information about later forward outcomes?

## Population and denominator

The denominator is **every Market-First opportunity episode considered for the designated acquisition run**. An episode does not disappear because its T0 snapshot, Activity Dynamics evidence, executable quote, or future outcome is missing.

Each considered episode receives one immutable cohort disposition:

- `ANALYZABLE_T0`: exact immutable T0 snapshot exists and contains `market_activity_dynamics_v0_discovery`.
- `ACTIVITY_DYNAMICS_MISSING`: exact immutable T0 snapshot exists but Activity Dynamics is absent.
- `T0_SNAPSHOT_MISSING`: no immutable T0 snapshot exists when the episode is registered.
- `T0_NOT_FROZEN`: the episode has no frozen `decision_as_of` when registered.

These dispositions are denominator accounting, not labels of economic quality.

## Immutability / anti-survivorship rule

The first persisted cohort disposition for `(cohort_key, episode_key)` is canonical. A later replay may be idempotent only if it reproduces the exact same identity and disposition. A missing/incomplete episode must never be upgraded retrospectively after outcomes become observable.

## T0 lineage

For `ANALYZABLE_T0`, persist lineage to:

- acquisition run;
- episode key;
- exact token mint;
- frozen `decision_as_of`;
- immutable T0 snapshot key;
- immutable T0 snapshot SHA-256;
- T0 snapshot method version;
- Activity Dynamics method version.

No feature is reconstructed after the fact.

## Activity evidence

Only the preregistered `market_activity_dynamics_v0_discovery` object is eligible for the primary Activity Dynamics analysis. It contains observed-only activity evidence derived from the existing cumulative 10/30/60/300 second windows.

No chain-completeness claim is introduced. Missing notional remains missing. Unique-wallet counts remain cumulative context and are not differenced between nested windows.

## Forward outcomes

Forward outcomes remain in the existing `opportunity_forward_outcomes` research layer and are scheduled only after T0 is frozen. The cohort registry stores no price outcome, return, MFE, MAE, score, or success/failure label.

At analysis time, report at minimum:

1. total cohort denominator;
2. count by immutable T0 disposition;
3. Activity-Dynamics-analyzable denominator;
4. count by forward-outcome terminal status and horizon;
5. missing/unavailable/provider-error outcomes without deletion.

The existing default Market-First forward horizons are +5m/+15m/+60m unless a separate protocol is preregistered before collection.

## Discovery constraints

The discovery cohort may compare descriptive associations for the already-frozen families:

- observed event/buy/sell rates;
- adjacent interval rate ratios;
- notional-rate dynamics only where the underlying cumulative notional coverage permits them;
- participant context already preserved at T0.

Forbidden during collection:

- changing Activity Dynamics windows;
- adding outcome-informed thresholds;
- optimizing a weighted score;
- selecting only survivors or executable winners;
- excluding missing outcomes after observing them;
- mixing Social/Event evidence;
- mixing Launch Burst evidence;
- adding Support-Coin relationship evidence;
- promoting a discovery association directly to a trading rule.

## Promotion path

If no useful association is found, close or deprioritize this feature family.

If discovery suggests a simple relationship, freeze one small hypothesis before a **fresh holdout**. The discovery cohort is burned and may not be reused as confirmatory evidence.

Economic edge remains **NOT EVALUATED** until a preregistered fresh holdout is completed.
