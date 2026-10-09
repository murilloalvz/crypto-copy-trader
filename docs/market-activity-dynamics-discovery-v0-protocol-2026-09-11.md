# Market Activity Dynamics Discovery V0 — preregistered protocol

Date: 2026-09-11

## Status

`PREREGISTERED / DISCOVERY ONLY / NO ECONOMIC VERDICT`

This protocol is downstream of the validated Market-First prospective T0 boundary. It does not change acquisition, detector thresholds, episode admission, provider pacing, frozen V68 research, Launch Burst, Social/Event/Attention, or any execution policy.

## Question

Does the *shape of observed market activity available at T0* contain useful prospective information beyond a raw activity level?

The first discovery target is descriptive dynamics, not a selector:

- observed event/buy/sell rates in non-overlapping recent intervals;
- rate ratios across adjacent intervals;
- observed notional-rate dynamics only when cumulative notional coverage supports subtraction;
- participant structure copied from already-causal cumulative windows.

No threshold, BUY/SKIP label, score, confidence, optimizer, ML model, exit policy, social feature, launch-quality feature, wallet whitelist, or convergence rule is authorized by this protocol.

## Causal boundary

For every episode:

1. the existing Market-First coordinator freezes `decision_as_of`;
2. the exact `MarketEpisodeResearchSnapshotV0` is persisted immutably before outcomes are scheduled;
3. Activity Dynamics V0 is derived only from the T0 `OpportunitySnapshotCoreV1` already present in that frozen payload;
4. outcomes remain in the separate forward-outcome layer.

No post-T0 observation may alter the T0 dynamics payload.

## Required cumulative windows

V0 requires exactly the existing cumulative market windows:

`10s / 30s / 60s / 300s`

It derives these non-overlapping intervals:

- `0-10s`
- `10-30s`
- `30-60s`
- `60-300s`

Observed counts are subtractable because cumulative windows share one exact `chain_as_of` and local causal cutoff. Unique participant counts are **not** subtractable because the same wallet may appear in more than one nested window.

## Allowed V0 transforms

Per non-overlapping interval:

- observed event count/rate;
- observed buy count/rate;
- observed sell count/rate;
- observed total notional/rate when derivable;
- observed signed notional/rate when derivable.

Across adjacent intervals:

- event-rate ratio;
- buy-rate ratio;
- sell-rate ratio;
- total-notional-rate ratio when both sides are available and the earlier rate is positive.

Participant context is copied only from cumulative `10s / 30s / 60s` windows:

- unique buy wallets;
- unique sell wallets;
- wallet identity coverage;
- repeated-wallet event share.

V0 deliberately does not derive "unique-wallet acceleration" by subtracting nested unique counts.

## Missingness and coverage

Activity Dynamics V0 describes **observed activity**, not chain-complete activity.

- absence of observed events is not proof of true zero intensity;
- incomplete notional coverage remains missing;
- interval notional is only derived when both required cumulative totals are causally available and internally consistent;
- source data-quality flags are preserved;
- no missing value becomes zero solely to enable a ratio.

The current Helius Standard WSS feed remains an operational low-latency input, not an authoritative completeness reference.

## Discovery protocol

Use a fresh prospective Market-First cohort after this protocol is frozen.

For every admitted episode, persist the frozen T0 snapshot and Activity Dynamics V0 before forward outcomes are available. Retain every eligible episode, including missing/unavailable execution evidence and poor outcomes.

Discovery analysis may describe association between the frozen V0 fields and separately collected forward outcomes. It may not promote an economic rule on the same cohort.

The discovery cohort is burned after inspection.

Any candidate rule must be reduced to a small predeclared hypothesis and evaluated on a fresh holdout with unchanged thresholds and lineage.

## Explicit non-goals

Not authorized in V0:

- `HIGH_VOLUME = BUY`;
- arbitrary low/mid/high bins;
- "organic volume" score;
- wash/bot classifier;
- Social/Narrative joins;
- Launch Burst rescue features;
- Support Coin relationships;
- combined Opportunity Score;
- retuning any historical prospective hypothesis;
- exit-policy optimization.

## Promotion condition

V0 may only graduate from descriptive discovery when a fresh discovery cohort suggests a simple, auditable hypothesis worth preregistering for a new holdout.

Until then:

`MARKET ACTIVITY DYNAMICS = DESCRIPTIVE RESEARCH EVIDENCE, NOT EDGE.`
