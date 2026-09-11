# Market Activity Dynamics — Fresh Discovery Run V0

Status: **PREREGISTERED / NO OUTCOMES INSPECTED**

This protocol operationalizes the already-preregistered `Market Activity Dynamics — Fresh Discovery Cohort V0` without changing its features, outcomes, denominator, or scientific question.

## Run identity

- Track: Market-First
- Feature family: `market_activity_dynamics_v0_discovery`
- Cohort registry: `market_activity_discovery_cohort_v0`
- T0 snapshot: current preregistered Market Episode Research Snapshot carrying Activity Dynamics lineage
- Forward outcomes: existing +5m / +15m / +60m research outcomes
- Real-money execution: forbidden

Each live acquisition execution must use a fresh `acquisition_run_key` and a fresh `cohort_key`. Keys identify the run; they must not encode or depend on economic outcomes.

## Frozen T0 clock contract

The local causal T0 for this discovery is **exactly the canonical episode `first_trigger_observed_at`**.

The independent on-chain market anchor is **exactly the canonical episode `first_trigger_chain_time`**.

Therefore:

- `decision_as_of = first_trigger_observed_at`;
- `chain_as_of = first_trigger_chain_time`;
- the two clocks are independent and are never numerically compared as a latency claim;
- no configurable post-trigger delay is allowed;
- evidence observed after `first_trigger_observed_at` is not part of T0;
- quotes, protocol enrichment, pool identity, research metadata, or any other evidence that arrives later remains missing from T0 rather than being backfilled;
- forward targets are scheduled from the frozen local `decision_as_of` only after the immutable T0 snapshot is persisted.

This contract is frozen before any outcome from the fresh discovery cohort has been inspected.

## Frozen stopping rule

The discovery acquisition window is **6 continuous wall-clock hours from run start**.

The run must not stop early because:

- returns look good or bad;
- a feature appears predictive or uninformative;
- a target number of winners/losers is reached;
- a certain profitability, win rate, MFE, MAE, or effect size is observed;
- a manually interesting token appears.

The run may terminate early only for an operational failure that prevents valid acquisition. Such a run is classified operationally interrupted and must not be silently treated as a completed discovery cohort.

No result-based extension is allowed. When 6 hours elapse, new cohort admissions stop. Already scheduled forward outcomes may continue to terminal collection after the admission window closes.

## Sample adequacy

Sample adequacy is not a stopping rule and does not extend this run.

After the admission window is closed, report before economic interpretation:

- total considered episodes;
- count by immutable cohort disposition;
- `ANALYZABLE_T0` count;
- forward-outcome terminal coverage by horizon.

If the sample is too small or too incomplete for useful discovery, classify the run as insufficient and preregister a separate fresh run. Do not append more admissions to the closed cohort after seeing outcomes.

No minimum episode count is used to decide when this run stops.

## Admission denominator

Every Market-First opportunity episode considered by this designated acquisition run must be registered exactly once in the cohort denominator.

Allowed immutable dispositions remain:

- `ANALYZABLE_T0`
- `ACTIVITY_DYNAMICS_MISSING`
- `T0_SNAPSHOT_MISSING`
- `T0_NOT_FROZEN`

An episode may not disappear because T0, Activity Dynamics, executable quotes, or future outcomes are missing.

## Admission order

For each considered Market-First episode:

1. identify the already-admitted canonical episode;
2. freeze the local T0 at `first_trigger_observed_at` and the on-chain anchor at `first_trigger_chain_time`;
3. build/persist the causal T0 using only evidence available at that local cutoff;
4. register the episode once in the discovery cohort with the exact first scientific disposition;
5. if T0 preparation succeeded, preserve the immutable snapshot lineage and already-scheduled forward outcomes;
6. if T0 preparation failed or evidence is missing, preserve the denominator disposition rather than deleting the episode.

The cohort registry never stores economic outcomes.

## Frozen feature family

No feature additions are allowed during the run. Primary discovery evidence is limited to the already-preregistered Activity Dynamics V0 surface:

- observed event/buy/sell rates in non-overlapping intervals derived from 10/30/60/300s cumulative windows;
- adjacent observed-rate ratios;
- notional-rate dynamics only where prerequisite coverage is complete;
- cumulative participant context already present at T0.

No score, threshold, classifier, recommendation, Social/Event evidence, Launch Burst evidence, Support-Coin evidence, or convergence feature may be added to this cohort.

## Outcome separation

Forward outcomes remain in the existing outcome research layer. They must never be written into the cohort member record or used to change T0 disposition.

The admission window may close before +60m outcomes finish. Outcome completion after the admission window is allowed because targets were scheduled from frozen T0 before their outcomes existed.

## Discovery burn rule

This entire cohort is discovery-only and is burned after analysis.

If a simple relationship appears promising, define one small hypothesis and its exact thresholds/contrast before collecting a separate fresh holdout. This cohort cannot become confirmatory evidence.

Economic edge remains **NOT EVALUATED** until a fresh preregistered holdout succeeds.
