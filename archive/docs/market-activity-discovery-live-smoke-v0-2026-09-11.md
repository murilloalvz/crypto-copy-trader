# Market Activity Discovery — Short Live Operational Smoke V0

Status: **PREREGISTERED OPERATIONAL SMOKE / NOT STARTED / NO ECONOMIC ANALYSIS**

This protocol defines a short live systems-only smoke before the official six-hour Market Activity Dynamics discovery run. It is not a discovery cohort, holdout, backtest, or trading experiment.

## Purpose

Verify that the already-frozen Market-First research boundary works on real incoming observations without contaminating the official discovery cohort.

The smoke validates only:

- canonical episode handoff;
- exact token mint identity;
- frozen local T0 = `first_trigger_observed_at`;
- frozen chain anchor = `first_trigger_chain_time`;
- immutable T0 snapshot + SHA-256 lineage;
- Activity Dynamics presence/missingness;
- immutable cohort disposition accounting;
- duplicate/replay behavior;
- +5m/+15m/+60m outcomes being scheduled as `PENDING` only;
- provider/coverage/missingness diagnostics;
- restart/load behavior;
- zero real-money execution.

## Isolation

The live smoke MUST use fresh smoke-only identities and persistence/artifacts that are never reused by the official discovery run.

Smoke members are permanently excluded from the scientific discovery denominator and from any future holdout.

The official six-hour discovery run remains unopened during this smoke.

## Frozen smoke duration

Admission duration: **5 continuous minutes** from smoke start.

This duration is operational only and is frozen before the smoke begins. It must not be extended or stopped based on returns, token quality, feature values, or any economic observation.

An operational failure may interrupt the smoke. Such a smoke is classified invalid/interrupted and must not be silently promoted to PASS.

## Admission boundary

The smoke observes the same canonical Market-First episode boundary intended for discovery, but it does not modify detector thresholds, kernel behavior, provider selection, or hot-path ordering.

Research work must occur outside the Signal Plane through a bounded/non-blocking Research Plane handoff. Research persistence or provider calls are forbidden inside the kernel or stateful detector commit path.

## T0 contract

For every smoke episode considered:

- local `decision_as_of = first_trigger_observed_at`;
- on-chain `chain_as_of = first_trigger_chain_time`;
- these clocks remain independent;
- evidence first observed later is missing from T0 and may not be backfilled;
- failure to build T0 keeps the episode in the smoke denominator with an explicit missing disposition.

## Operational PASS conditions

A smoke may be classified operational PASS only if all of the following hold for the smoke sample:

1. no crash or unhandled research-plane exception propagates into the Signal Plane;
2. no duplicate cohort identity or divergent snapshot replay is accepted;
3. every considered canonical episode receives exactly one denominator disposition;
4. every analyzable member has exact snapshot key + SHA-256 lineage;
5. every analyzable T0 respects the frozen local and chain anchors;
6. scheduled outcomes remain PENDING during admission and are not fabricated/backfilled;
7. restart/load preserves run, cohort, snapshot and pending-outcome identities;
8. provider/coverage failures remain explicit rather than becoming zeros;
9. no real-money order is signed or submitted;
10. no return, win rate, MFE, MAE, feature association, threshold, or economic edge is inspected for promotion.

These are systems/research-integrity criteria only. PASS does not imply economic edge.

## Failure handling

Any violation of causal clocks, exact mint identity, denominator preservation, immutable snapshot lineage, or isolation from the hot path invalidates the smoke.

Do not tune Activity Dynamics features, detector thresholds, or discovery rules in response to smoke economics. Only operational defects may be repaired before a new smoke with fresh smoke identities.

## Promotion to the official discovery run

After a clean short live smoke:

1. burn the smoke identities/data for scientific purposes;
2. emit an operational audit with admissions, dispositions, snapshot hashes, duplicate/replay counts, provider/coverage missingness and pending-outcome accounting;
3. create entirely fresh official `acquisition_run_key` and `cohort_key`;
4. open the preregistered six-hour discovery run;
5. do not reuse any smoke observation as discovery evidence.

Economic edge remains **NOT EVALUATED** by this smoke.
