# Multivariate Opportunity Intelligence Scaffold — 2026-09-08

Status: **engineering / research scaffold only**

Mode: **PAPER / RESEARCH / READ ONLY**

This document aligns the new participant/temporal interaction work with the research tracks already built through v56-v67. It does not change the frozen v68 prospective protocol and it does not claim a profitable combined strategy.

## 1. Long-run objective

The project should not assume that one standalone feature will explain an opportunity. The useful object is an interpretable causal representation of a market episode, where complementary dimensions can later be tested for incremental and interaction value.

Conceptually:

`movement`
`+ intensity / direction`
`+ participant distribution`
`+ temporal structure`
`+ pre-frozen wallet convergence`
`+ causal relationship / hazard evidence`
`+ chain-specific lifecycle / launch quality`
`+ executability`
`-> selection research`
`-> entry`
`-> exit geometry / policy research`
`-> shadow`
`-> sizing only after validated net economics`

This is a research architecture, not an entry score.

## 2. Failed standalone hypotheses are not erased

A prospective FAIL closes the exact tested statement, not every future conditional use of the underlying measurement.

Example:

- v48 rejected the frozen standalone rule based on `flow60_event_count`;
- v48 did **not** test `intensity × participant breadth`, `intensity × temporal persistence`, or another preregistered conditional regime on a fresh dataset.

A previously failed variable may therefore re-enter only as a genuinely new interaction hypothesis if:

1. the old standalone result remains recorded as FAIL;
2. the interaction question is specified before inspecting the new discovery outcomes;
3. a fresh discovery sample is used where appropriate;
4. selection among interaction candidates follows a frozen rule;
5. any selected interaction receives a separate fresh prospective holdout.

The same rule applies if v68 fails: `flow60_buy_share_pct` would be closed under its exact v68 rule, but direction could later appear inside a separately designed interaction study.

## 3. Pre-entry component families

### 3.1 Movement / intensity

Existing radar and snapshot evidence describes whether activity is present and how much activity exists. Examples include event counts and rates.

Important boundary: the frozen detector remains unchanged. These measurements are post-detection research evidence, not a reason to retune detector thresholds while v68 is active.

### 3.2 Direction

Existing causal flow features describe BUY/SELL composition, including the v68 candidate `flow60_buy_share_pct`.

Direction is a component family. A v68 PASS or FAIL determines the exact frozen v68 hypothesis, not whether direction can ever interact with another independently designed family.

### 3.3 Participant distribution

The new score-free layer measures how BUY events are distributed across observed addresses:

- buyer breadth ratio;
- top-1 / top-3 buyer event share;
- buyer-event HHI;
- repetition;
- wallet identity coverage.

If BUY wallet identity is incomplete, structural concentration metrics remain missing rather than being computed on a selected subset.

Distinct addresses are not asserted to be independent humans or independent traders. Concentration and repetition are descriptive evidence, not manipulation labels.

### 3.4 Temporal flow structure

The new T0-anchored temporal layer separates sustained activity from one short burst using fixed market-time subwindows.

It keeps two clocks separate:

- market clock: episode T0 anchors the market window;
- knowledge clock: only observations with `observed_at <= research_decision_as_of` are eligible.

This prevents variable pipeline latency from becoming an economic feature.

Examples of raw outputs:

- active subwindow count/share;
- maximum subwindow event share;
- temporal event HHI;
- early-half vs late-half activity;
- late/early event ratio;
- buy-active subwindows.

These are descriptive measurements with no frozen bullish/bearish direction yet.

### 3.5 Pre-frozen wallet convergence — v60 / v65

Yesterday's wallet-convergence work remains a first-class complementary family.

The isolated research branch strengthens v60 for multivariate use by separating market and knowledge clocks:

- cohort membership must be frozen strictly before episode T0;
- market participation must belong to the T0-anchored market window;
- evidence must be observed by the research decision cutoff.

This preserves the market-first architecture. Wallets are evidence after the radar has opened an episode; they are not an acquisition whitelist.

v65 remains the deterministic/hashable manifest authority for prospective cohort membership. Public profitable-wallet lists are research seeds only until frozen under the project-owned manifest semantics.

Potential future interaction questions include:

- participant distribution × wallet convergence;
- temporal persistence × wallet convergence;
- direction × wallet convergence.

No interaction direction or threshold is asserted here.

### 3.6 Hazard / integrity evidence

Existing token-hazard evidence can remain a separate causal family when its provider/clock/coverage semantics are valid.

Provider-native meanings must not be renamed. For example, top-token-account concentration is not automatically holder concentration.

Participant concentration must also remain separate from token-account concentration: they answer different questions.

### 3.7 Direct funding relationship — v61

v61 remains useful but must not be inflated into a generic insider/manipulation signal.

The supported primitive is an exact causal direct deployer/participant transfer relationship under its chain and clock rules.

Safe future observables may include direct-link presence/count/share only when a new protocol defines the participant universe and coverage. A direct funding link does not prove common ownership, insider status, manipulation, wash trading, or malicious coordination.

General common-funder / multi-hop cluster research requires separate graph infrastructure and should not be silently inferred from v61.

### 3.8 Social evidence — v57

v57 remains optional causal evidence with exact token-mint linkage and knowledge-time semantics. Social `created_at` is not equivalent to availability to the system.

There is still no approved live social provider, so social evidence must not be fabricated or treated as missing=negative.

## 4. Chain-specific component families

### 4.1 Robinhood Chain / Pons — v62 / v64 / v66 / v67

Yesterday's Pons work stays aligned as a second laboratory, not as Solana feature contamination.

- v62: chain-aware Pons adapter and lifecycle contract;
- v64: exact curve-progress/maturity from causal state, not external trade summation;
- v66: deployed capability attestation before trusting protocol-specific semantics;
- v67: raw launch-quality evidence only, no weighted FIRE/WATCH/SKIP score.

These concepts fit the broader `lifecycle / stage / launch quality` family, but their raw definitions are chain-specific.

Do not copy Pons thresholds into Solana or assume cross-chain equivalence. Shared modeling happens at the conceptual family level; raw evidence remains namespaced by chain/protocol capability.

## 5. Downstream families that must NOT leak into pre-entry selection

### 5.1 Route executability

Route availability is not equivalent to transaction assembly, landing, or fill. Route-only returns remain market-opportunity metrics, not realized PnL.

Executability is a later gate between selection evidence and shadow/live economics.

### 5.2 Market-first exit geometry — v58

v58 is deliberately downstream of entry. Its MFE, MAE, time-to-peak/trough, giveback, MFE capture, coverage and gaps are post-entry path geometry.

These values must **never** be included in a pre-entry selection vector for the same episode. Doing so would be direct lookahead leakage.

v58 instead answers a different profit-critical question:

> after a valid entry candidate exists, can an exit policy preserve the rare right-tail winner while containing adverse paths?

This is especially important because previous route-only samples were heavy-tailed and a single explosive winner could dominate the mean.

### 5.3 Shadow and position sizing

Shadow execution comes only after prospective selection evidence plus realistic execution and exit research.

Position sizing comes after observed shadow/net-return distributions. It is not a substitute for edge validation.

## 6. Outcome-blind multivariate representation

`src/opportunity_multivariate_research.py` is a representation layer, not a strategy.

Its current role is to place causally compatible pre-entry components on the same episode/T0/decision lineage while preserving:

- feature clocks;
- missingness;
- component method versions;
- pre-frozen cohort identity;
- interaction-family questions.

It intentionally has no PnL/outcome argument, no favorable bin, no weight, and no entry score.

Current interaction families are research questions only:

1. intensity × participant distribution;
2. direction × participant distribution;
3. intensity × temporal structure;
4. participant distribution × temporal structure;
5. direction × temporal structure;
6. participant distribution × wallet convergence;
7. temporal structure × wallet convergence;
8. direction × wallet convergence.

Do not multiply every pair mechanically. The final candidate set must remain small, semantically distinct and preregistered before discovery economics.

## 7. What a future interaction study should test

The next multivariate phase should shift from only asking:

> does X work alone?

Toward:

> does X add information conditional on Y, and does that incremental information replicate prospectively?

A defensible sequence is:

1. freeze the causal episode representation;
2. acquire a fresh discovery dataset;
3. audit coverage and dependence before looking for economics;
4. preregister a small, non-duplicative interaction candidate set;
5. run discovery under a frozen selection rule;
6. advance at most the allowed number of candidates;
7. freeze the selected interaction semantics and any cutpoints/model form;
8. collect a separate fresh prospective holdout;
9. compare against the simpler component baseline to measure incremental value;
10. only after prospective evidence, move through executability -> exit -> shadow.

## 8. Anti-overfitting rules

Do not:

- use v68 outcomes to invent a formula that rescues v68;
- promote another burned v55 candidate as if it were new;
- generate dozens of algebraic aliases of breadth/concentration/persistence;
- optimize bins, weights or interaction formulas on the same holdout used for validation;
- call one giant winner proof of a robust model;
- construct a weighted Frankenstein score before individual and incremental evidence exists;
- use ML/grid search while prospective sample size is still small;
- mix post-entry v58 geometry into pre-entry features;
- reinterpret direct funding or concentration as manipulation without stronger evidence.

## 9. Alignment with the active v68 run

The active v68 experiment remains the sole live economic acquisition.

This isolated branch changes none of the frozen v68 detector, feature, bins, direction, horizon, pacing, systems gate, acquisition or prospective criteria.

The work in this branch is preparatory measurement and causal architecture only.

If v68 PASSes, the immediate economic path remains execution realism -> v58 exit/right-tail research -> shadow. The multivariate scaffold remains available for later incremental-selection research.

If v68 FAILs or is INCONCLUSIVE, the exact v68 buy-share rule closes. A new, fresh interaction/participant/temporal discovery can then be designed without mining the v68 holdout for a rescue.

## 10. Current thesis

The economically interesting long-run thesis is not “one magic feature.” It is that profitable opportunities may be distinguished by a coherent causal state such as:

`movement has started`
`+ flow has a useful stage/direction structure`
`+ participation is distributed in a useful way`
`+ activity persists rather than being a single burst`
`+ pre-frozen useful wallet archetypes converge`
`+ causal integrity/lifecycle evidence remains acceptable`
`+ the route is realistically executable`
`+ the exit preserves the rare right tail`

Every plus sign above is a hypothesis boundary. It becomes strategy logic only after incremental prospective evidence supports it.
