# Market-First Exit Research — Current Gap and Required Next Contract

Date: 2026-09-07

Mode: **PAPER / RESEARCH / READ ONLY**

## Finding

The repository already contains a useful `exit_engine_v1`, but it belongs to the earlier Wave signal architecture.

Its enrollment is tied to:

- `wave_signals`;
- `WAVE_STRATEGY_VERSION`;
- a forward experiment boundary over Wave signal IDs;
- GeckoTerminal/candle-style price observation;
- fixed-time, stop-loss, take-profit and trailing-stop policy definitions.

Its metrics already include return distribution, profit factor, MFE, MAE, MFE captured, duration, largest-winner dependence and closed-PnL drawdown.

This makes it valuable prior research infrastructure, but it is **not** the authoritative exit path for the current market-first route-research pipeline.

## Why direct reuse would be scientifically wrong

Current market-first research decisions are defined through:

`market episode -> causal enrichment -> route-only research decision -> exact-output route outcomes`

They have different entry semantics, clocks, provider evidence and lineage from Wave signals.

Creating a market-first position by silently converting a v55 episode into a `wave_signal` would conflate two experiment generations and could break:

- entry-price comparability;
- causal `decision_as_of` lineage;
- route-only notional/slippage semantics;
- provider missingness;
- execution-path interpretation.

Therefore no adapter should be implemented merely to reuse the old schema quickly.

## What the old exit engine proves

It proves that the project already has defensible concepts for:

- forward-only exit enrollment;
- paired policy comparison;
- no declaration of a winner during collection;
- explicit observation gaps;
- MFE/MAE accounting;
- largest-winner dependence;
- MFE-capture measurement.

It does not prove which exit policy works for current market-first opportunities.

## Required future market-first exit contract

Only after entry-selection research justifies advancing should a new protocol pre-register:

### Entry identity
- market episode key;
- acquisition run key;
- token mint;
- frozen `research_decision_as_of`;
- exact route-only BUY input/output semantics;
- entry quote/attempt lineage.

### Observation clock
- explicit target sampling schedule or event-driven route observations;
- real `observed_at` for each observation;
- no interpolation/backfill presented as observed evidence;
- explicit provider failures/missingness.

### Exit quote semantics
- SELL exact token amount associated with the entry or clearly defined remaining position amount;
- same route/provider family where possible;
- explicit slippage/notional semantics;
- no threshold-price fantasy fills.

### Path metrics
At minimum:
- MFE and MAE over observed executable/route surface;
- time to MFE;
- time to MAE;
- terminal return;
- return captured / MFE captured;
- giveback from peak;
- duration;
- missing observation coverage.

### Convexity robustness
Because memecoin returns may be dominated by rare large winners, evaluation should preserve:
- mean and median;
- PF;
- mean without best trade;
- largest winner share of gross profit;
- winner truncation diagnostics;
- paired comparison on the same entries.

These are robustness diagnostics, not reasons to delete outliers.

## Policy research sequencing

Do **not** invent a new trailing-stop percentage now.

Preferred sequence:

1. establish a defensible entry-selection hypothesis prospectively;
2. collect a market-first path dataset under a pre-registered observation contract;
3. describe MFE/MAE/peak-giveback geometry without choosing a winning threshold from the same data;
4. pre-register a small number of simple exit hypotheses;
5. compare them on new paired forward data;
6. only later move to shadow execution.

## Relationship to v55

v55 is an entry/opportunity-selection discovery experiment and is already running.

No exit parameter, policy, sampling path or old Wave exit result may be injected into v55 or used to rescue its candidate selection.

## Current conclusion

Exit research is strategically important, especially for preserving rare convex winners, but the correct next engineering move is **not** to tune `exit_engine_v1`.

The current gap is a market-first path-observation contract that matches the route-research lineage. That contract should be designed only when the entry-selection gate warrants spending more provider/runtime budget on dense path observations.

## Forbidden now

- copying Wave exit policies into v55;
- selecting a trailing-stop/TP/SL threshold from historical best returns;
- converting route-only terminal outcomes into fake intraperiod MFE/MAE;
- interpolating unobserved prices as observed path evidence;
- declaring old Wave exit results valid for current market-first episodes;
- running an additional live exit experiment while v55 is active;
- live-money execution.
