# Launch Burst Discovery V0 — Preregistration

Date: 2026-09-10
Status: PREREGISTERED / NOT YET RUN / NO ECONOMIC EDGE CLAIM
Track: C — Launch Burst / First-Move Capture

## Purpose

Test whether a newly launched Pump.fun token still has economically meaningful, executable residual movement after the bot has had enough causal information to make a fixed-time decision.

This track is independent from Market-First and Social/Event-First. No evidence from another track is required for enrollment, scoring, filtering, or outcome interpretation in V0.

Primary question:

> After a fixed causal checkpoint at launch +10 seconds, does a covered Pump.fun launch cohort contain meaningful residual return that remains observable through an executable or explicitly-labeled execution proxy?

V0 is discovery research. It does not define a profitable selector, confidence score, TAKE/SKIP recommendation, convergence rule, or real-money execution policy.

## Scope

- Venue/protocol: Pump.fun only.
- Launch event: explicit supported Carbon-decoded Pump Create/CreateV2 semantics only.
- Population: every eligible launch observed inside the frozen covered-live interval, subject only to preregistered systems-validity criteria.
- Decision checkpoint: launch +10 seconds on the local causal availability clock.
- Forward horizons from the frozen decision checkpoint: 15s, 30s, 60s, 120s, 300s.
- Position size/notional: MUST be frozen before the first outcome-bearing live run. V0 must not choose the size after seeing returns.
- No TP, SL, trailing stop, adaptive exit, ML ranker, or threshold optimization in V0.

## Cohort denominator and completeness gate

The study must not call its denominator `all launches` until a Launch Cohort Completeness Audit establishes the eligible-launch reference for the same covered interval.

Program-reference recall is insufficient because:

- program reference != invocation;
- invocation != target Create/CreateV2 event;
- WSS program-signature recall != semantic launch-event completeness.

If the semantic launch reference cannot be enumerated completely for an interval, cohort completeness is MISSING for that interval and economic results from that interval cannot be promoted as an all-launch estimate.

Never enroll only tokens that later trade, survive, migrate, reach a liquidity threshold, reach a holder threshold, or produce an outcome. Dead, failed, illiquid, and non-exitable launches remain part of the cohort when they were validly observed at enrollment.

## Causal clock contract

- `observed_at` / `observed_wall_ns`: local causal evidence-availability clock.
- `chain_time` / `chain_as_of`: on-chain ordering/window clock.
- Never require `observed_at >= chain_time`.
- Never subtract chain and local clocks to claim latency without explicit calibration.
- No future event, account state, quote, social observation, or outcome may backfill the +10s T0 snapshot.
- Evidence observed after the frozen decision checkpoint belongs only to forward/outcome records.

## T0 snapshot

At the +10s checkpoint, freeze only information causally available by that checkpoint. V0 should reuse existing factual infrastructure rather than duplicate calculations.

Candidate factual fields already supported by the project include:

- exact token mint;
- launch/protocol facts;
- Mayhem mode when explicit;
- token age;
- event/buy/sell counts;
- unique participants/buyers when causally observable;
- buy/sell imbalance;
- repeat-wallet share;
- compatible notional/flow facts;
- first/latest causally known price and price change;
- execution/liquidity surface when available;
- collection coverage;
- explicit missingness;
- provenance;
- `decision_as_of` and `chain_as_of`.

Do not add sniper/bundler/insider/dev labels, holder graphs, smart-wallet scores, social scores, or large feature families merely because they are available. Those require separate evidence and later preregistration.

## Execution semantics

Execution is part of the hypothesis, not cosmetic enrichment.

- route != quote;
- quote != fill;
- chart price != executable price;
- theoretical MFE != captured profit.

Entry and exit observations must carry provider/venue, side, requested size/notional, local observation time, price/amount semantics, and executable-vs-proxy status where applicable.

If a defensible entry cannot be observed at the frozen checkpoint, entry status is MISSING/FAILED rather than silently dropping the launch.

If an entry is represented but an exit cannot be defensibly observed at a forward horizon, the outcome remains an explicit unavailable/failed outcome rather than disappearing from the dataset.

## Forward outcomes

For every enrolled launch, schedule the frozen horizons before their outcomes are known.

At each horizon record, at minimum:

- target time;
- actual local observation time;
- AVAILABLE / MISSING / FAILED / PENDING semantics;
- exit quote/execution proxy when available;
- return only when input semantics make the computation valid;
- provider/route failure where relevant;
- explicit missingness/provenance.

Do not rewrite T0 using any forward observation.

## Discovery outputs

V0 may report descriptive distributions only. At minimum:

- eligible launch count;
- semantic cohort coverage/completeness status;
- T0 snapshot availability count;
- executable/proxy entry availability fraction;
- exit availability/failure fraction by horizon;
- return distribution by horizon when valid;
- median and fixed distribution quantiles;
- positive/negative/zero-return counts when valid;
- right-tail concentration/dependence;
- mean return with the single best observation removed (`mean_without_best`);
- missing/failed exit counts;
- MFE/MAE only if they can be reconstructed causally from sufficiently covered observations.

Systems health, semantic completeness, and economic performance must be reported separately.

## Discovery burn and holdout rule

The first valid Launch Burst dataset is discovery-only and is burned for selector validation.

If discovery suggests a candidate predictive feature or selector:

1. state the hypothesis explicitly;
2. freeze the feature definition, thresholds, size, T0 checkpoint, horizons, inclusion rules, and gate before new outcomes;
3. collect a fresh prospective holdout;
4. evaluate exactly once under the frozen rule;
5. close failed hypotheses rather than retuning the same holdout.

No threshold tuning after outcome inspection.

## Explicit non-goals

V0 does NOT:

- prove Launch Burst has edge;
- merge Market, Social, and Launch evidence;
- emit a unified score;
- perform real-money execution;
- optimize exits;
- infer missing observations as zero;
- infer migration from PumpSwap activity;
- infer social causation;
- infer smart-wallet quality;
- treat provider labels as ground truth.

## Preconditions before first outcome-bearing run

1. Semantic Launch Cohort Completeness Audit defined and passing for the study interval, or the interval is explicitly marked incomplete and withheld from all-launch economic conclusions.
2. Covered live acquisition path operational.
3. Carbon Create/CreateV2 semantics verified on the live payload path.
4. Exact mint identity preserved.
5. Dual-clock contract enforced end-to-end.
6. +10s checkpoint frozen.
7. Forward horizons frozen at 15/30/60/120/300s.
8. Position size/notional frozen.
9. Entry/exit availability and failure semantics frozen.
10. Discovery dataset identifier frozen before outcome inspection.

## Promotion criterion

V0 can only justify a next-stage Launch Burst hypothesis when:

- cohort construction is causally defensible;
- missingness/failures remain visible;
- execution observability is adequate to interpret returns;
- descriptive evidence is not explained solely by one or a few extreme winners;
- the proposed next hypothesis is frozen before a fresh holdout.

Any positive V0 result remains discovery evidence, not validated economic edge.
