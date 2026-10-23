# Exceptional Trade Intelligence v56 — Causal Pre-Entry Snapshot Protocol

Date: 2026-09-07

Mode: **PAPER / RESEARCH / READ ONLY**

## Purpose

Prepare the causal evidence layer needed to study a future question:

> What was observably different immediately before entries made by wallets/trades later classified as exceptional?

v56 does **not** answer that economic question yet. It only defines and tests the pre-entry snapshot semantics so a later study cannot accidentally use the target entry itself, same-tick activity, delayed backfill, or post-entry outcomes as predictive evidence.

This work is orthogonal to the live v55 Causal Early-Opportunity Discovery run. It performs no market acquisition, no provider calls and no concurrent economic experiment.

## Reference entry contract

Each research reference is represented by:

- `reference_key`
- `acquisition_run_key`
- `wallet_address`
- `token_mint`
- `entry_chain_time`
- `entry_observed_at`

The reference object deliberately contains **no P&L, return, exit, rank, score, or exceptional label**.

Outcome/exceptional labels must live in a separate layer and may be joined only after pre-entry features have been frozen for a study.

## Strict dual cutoff

An event may enter the pre-entry snapshot only if both are true:

1. `event.chain_time < reference.entry_chain_time`
2. `event.observed_at < reference.entry_observed_at`

The inequalities are strict.

Events with the same `chain_time` second as the reference entry are excluded because the persisted store does not establish a canonical sub-second ordering between an arbitrary external wallet entry and every market event.

A trade that happened before the reference on-chain but was observed by the collector only at or after the reference entry is also excluded. This prevents historical backfill from masquerading as information that was available in real time.

## Frozen descriptive windows

v56 reconstructs these market-time windows immediately before the reference entry:

- 10s
- 30s
- 60s
- 300s

No return label is used to choose or adjust these windows.

## Descriptive evidence

For each window v56 may report:

### Activity
- event count
- buy count
- sell count

### Participation structure
Only when wallet identity coverage is complete:
- unique wallets
- unique buy wallets
- unique sell wallets
- repeated-wallet event share
- top-1 wallet event share
- top-3 wallet event share
- buy/sell wallet overlap count/share

These metrics are **participation-structure evidence**. They must not be described as manipulation, wash trading, sybil activity, insider activity or organic demand without an independently validated semantic study.

### Notional
Only when notional coverage is complete:
- buy-notional share

### Price
Only when price coverage is complete:
- window return

### Simple dynamics
Deterministic label-free transforms may include:
- event-rate ratio 10s vs 60s
- event-rate ratio 30s vs 300s
- unique-buy-wallet-rate ratio 10s vs 60s
- top-1 wallet event share 30s/60s
- repeated-wallet event share 30s/60s
- buy/sell wallet overlap share 60s

No weighted opportunity score is created.

## Missingness rules

- Partial wallet identity -> concentration/repetition/overlap metrics remain missing rather than computed from a selected subset.
- Partial notional coverage -> notional-share metrics remain missing.
- Partial price coverage -> return remains missing.
- Zero causal pre-entry rows -> explicit inconclusive snapshot.

Missingness may not be backfilled from observations learned after the reference entry.

## Relationship to existing modules

`src/wallet_entry_context.py` remains legacy candle-based descriptive research and is not the causal authority for v56.

`src/onchain_wallet_research.py` remains wallet-behavior profiling and does not establish pre-entry market state or profitability.

`src/wallet_placebo_matching.py` may later support control-wallet construction because it uses pre-period behavioral diagnostics and avoids an opaque weighted score. It is not invoked by v56.

## What v56 proves if tests/CI pass

Only that the code can reconstruct a strict persisted pre-entry market snapshot with explicit information cutoffs and conservative missingness.

It does **not** prove:

- that any wallet is exceptional or skilled;
- that any participation pattern is organic or manipulated;
- that exceptional entries are predictable;
- that copying a wallet has edge;
- that any v56 feature predicts forward returns;
- executable/fill/shadow/live readiness.

## Future exceptional-reference selection — intentionally NOT defined here

v56 does not define a profit threshold such as +100%, top 1%, or a leaderboard rank. Defining that target universe after seeing feature effects would create selection bias.

Before a future comparison study starts, a separate protocol must pre-register:

1. the data source for wallet entries and outcomes;
2. exact entry identity and clock semantics;
3. the exceptional outcome definition;
4. control/reference population construction;
5. deduplication and dependence rules;
6. minimum sample support;
7. the feature set to compare;
8. the evaluation statistic.

Only then may outcome labels be joined to v56 snapshots.

## Forbidden

- using the target entry as a pre-entry event;
- same-second target leakage;
- treating later-observed historical events as known before entry;
- choosing an exceptional threshold after inspecting feature results;
- calling concentration/repetition metrics manipulation detection;
- using future sell/P&L data in pre-entry feature construction;
- converting v56 into a BUY rule;
- running a second live economic acquisition while v55 is active;
- live-money execution.

## Acceptance for this scaffold

v56 scaffold is accepted when:

1. unit tests prove strict market-time cutoff;
2. unit tests prove strict knowledge-time cutoff;
3. same-second target events are excluded;
4. partial wallet identity cannot create pseudo-complete concentration metrics;
5. reference clocks reject impossible ordering;
6. CLI is read-only and uses persisted observations only;
7. full repository CI is green.

Classification after scaffold acceptance:

`READY_V56_CAUSAL_PREENTRY_RESEARCH_SCAFFOLD`

This classification is an engineering/causal-semantics readiness statement only, not an economic result.
