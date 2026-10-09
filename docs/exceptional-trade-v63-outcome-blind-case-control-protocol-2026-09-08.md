# Exceptional Trade v63 — Outcome-Blind Case-Control Matching

Date: 2026-09-08
Mode: PAPER / RESEARCH / READ ONLY

## Research question

For entries made by the same profitable wallet, what causal pre-entry market evidence differs between later exceptional winners and otherwise comparable entries that did not become exceptional?

The objective is to study what a strong trader may have been reacting to, not to copy that wallet automatically.

## Dependency

v63 consumes reference clocks and pre-entry covariates only after v56 causal snapshots have been built. Outcome labels remain a separate input.

## Separation rule

Feature construction must occur before any outcome label is joined.

`FrozenOutcomeLabelV63.outcome_value` is diagnostic metadata only. It is deliberately excluded from the matching key and every tie-breaker.

Changing future profit magnitude while preserving case/control labels must not alter matched pairs.

## Exact matching contract

A case can pair only with a control that matches exactly on:

1. wallet address;
2. pre-frozen strategy signature;
3. venue bucket;
4. entry-notional bucket;
5. market-age bucket.

Within an exact stratum, nearest entry chain time is the deterministic tie-breaker.

Controls are disjoint: one control may be used at most once.

There is NO fallback relaxation. If no exact control exists, the case remains unmatched and sample support falls explicitly.

## Why same-wallet controls

Comparing Cented-like behavior to Pain-like behavior directly can confound strategy, size, latency, risk tolerance, holding style and execution frequency. Within-wallet controls ask a narrower question:

> What was different in the market before this wallet's unusually successful entries relative to its own otherwise comparable entries?

Cross-wallet generalization is a later step. A pattern that exists only in one wallet is not yet a general opportunity feature.

## Outcome label intentionally not defined here

v63 freezes the matching mechanism, NOT the definition of an exceptional winner.

Before labels are assembled from any local dataset, a separate protocol must freeze:

- outcome basis (realized return, realized PnL, executable route return, or another clearly defined quantity);
- observation horizon / closure semantics;
- treatment of scale-ins, staged exits and open inventory;
- exceptional-case threshold;
- control label definition;
- minimum closed-trade support per wallet;
- dependence rules for repeated token entries.

This avoids choosing an outcome definition because it produces attractive pre-entry patterns.

## Candidate features

The v63 matcher itself does not inspect feature values. Future comparisons may use the already causal v56 pre-entry windows, such as:

- event-rate acceleration;
- unique buyer acceleration;
- wallet breadth;
- repeated-wallet share;
- top-wallet concentration;
- buy/sell overlap;
- buy-notional share where coverage is complete;
- pre-entry return where price coverage is complete.

No feature may be called manipulation/organic/insider evidence solely from these descriptive participation metrics.

## What PASS means

A green v63 implementation only proves deterministic, outcome-blind matching semantics and fail-closed unmatched cases.

It does NOT prove:

- exceptional entries are predictable;
- profitable wallets have transferable alpha;
- any v56 feature is economically useful;
- copy trading is profitable;
- wallet convergence is a trading rule.

Any discovered pattern remains retrospective discovery until frozen and prospectively validated on untouched future entries/episodes.
