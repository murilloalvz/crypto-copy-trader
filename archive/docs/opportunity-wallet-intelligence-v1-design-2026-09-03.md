# Opportunity Wallet Intelligence v1 — Dynamic Participant Evidence

Date: 2026-09-03

Mode: **PAPER / RESEARCH / READ ONLY**

## Purpose

Market Opportunity Radar v1 must not depend on a curated list of supposedly good wallets.

The correct causal order is:

`market movement -> opportunity episode -> observe wallets participating in that episode -> evaluate those wallets using only evidence already available by decision_as_of -> cross with execution + flow + risk + regime`

Wallets are therefore **dynamic evidence discovered inside each opportunity**, not an allowlist and not a prerequisite for radar detection.

## Non-negotiable rule

There is no `good_wallets` set in the opportunity path.

A wallet may be:

- previously unknown;
- historically strong;
- historically weak;
- highly active but poorly resolved;
- new with no usable history;
- apparently competent globally but behaving atypically in the current token.

All of these states remain observable. None of them suppresses the market episode by identity alone.

The legacy Discovery/Copyability pipeline remains historical research infrastructure. Its `Copyability Score` must not be reused as a hidden radar admission filter.

## What the wallet layer asks

For every wallet causally observed participating in the current episode, ask:

1. How many prior opportunity/trade episodes had already resolved before current T0?
2. Across those resolved episodes, what was its positive-outcome share?
3. What were mean and median realized returns where return coverage exists?
4. What was its typical holding time where known?
5. How many different tokens does that history cover?
6. Has the wallet traded this same token before?
7. Is it buying, selling, scaling or repeatedly appearing in the current episode?
8. How much of current observed notional does it represent when notional coverage is complete?
9. Is current wallet evidence broad across independent participants or concentrated in one actor?
10. How complete is the historical evidence, and is the sample large enough to interpret cautiously?

These are descriptive causal features. They are not a verdict that a wallet is smart.

## Causal history rule

A historical wallet outcome may contribute to current wallet evidence only if:

- its entry was already observed before current `decision_as_of`;
- its outcome had already become observable before current `decision_as_of`;
- it is not the current opportunity episode itself.

An old entry whose result resolves after current T0 is not usable history at T0.

Unresolved history stays missing. It is never silently classified as a loss.

## No monolithic wallet score in v1

Opportunity Wallet Intelligence v1 deliberately exposes an evidence vector rather than a single `Wallet Score`.

Reason:

- a single score hides sample size and missingness;
- a wallet may be useful in one market state and harmful in another;
- the value of wallet evidence must be tested jointly with market evidence;
- future models need to distinguish reliability from direction.

The snapshot contract therefore contains no `passed`, `recommended`, `BUY`, `wallet_score` or trading decision field.

## Cross-analysis architecture

The future T0 opportunity evidence bundle should combine:

### Market movement

- activity acceleration / fresh-market burst;
- pressure direction;
- market age/lifecycle;
- detector strength and coverage.

### Order flow / microstructure

- buy/sell counts;
- signed flow;
- unique participants;
- participant repetition/concentration;
- trade velocity;
- short-window price response.

### Wallet intelligence

- every causally observed participant wallet;
- resolved prior sample size;
- prior positive-outcome share;
- prior mean/median outcome;
- token diversity;
- same-token history;
- holding-time behavior;
- current buy/sell/repetition/notional participation;
- history coverage and quality flags.

### Execution / liquidity

- Jupiter quote availability;
- buy/sell proxy prices;
- route/router;
- price impact;
- liquidity metadata;
- quote age/latency;
- proxy vs executable distinction.

### Hazard / token risk

- lifecycle state;
- authority/liquidity hazards when causally available;
- holder/flow concentration where coverage supports it;
- route disappearance or severe quote deterioration.

### Network / regime

- Solana priority-fee/congestion state;
- broader market regime features when causally available.

No family is assumed to be predictive merely because it exists.

## Example interpretation

Suppose Radar detects a Pump/PumpSwap token entering an activity burst.

At T0 the bot observes 12 wallets buying.

Instead of asking:

> did wallet 7mP buy?

it asks:

> who are these 12 wallets, what evidence about their prior behavior was actually known before now, how independent are they, and does their participation agree or conflict with flow, liquidity, token risk and execution conditions?

A possible future pattern might be:

`activity acceleration + broad independent buying + several wallets with resolved positive history + healthy liquidity + acceptable execution + low hazard`

But this is only a research hypothesis. It must be validated by forward labels and ablation before becoming any rule.

## Ablation requirement

After a sufficiently large causal sample, compare at minimum:

1. market detector only;
2. wallet evidence only;
3. order flow only;
4. execution/liquidity only;
5. risk/regime only where coverage exists;
6. market + wallet;
7. market + flow;
8. wallet + flow;
9. market + wallet + execution;
10. all available Core evidence families.

Use time-separated and token/wallet-cluster-aware evaluation.

The goal is to learn whether wallet competence evidence adds incremental predictive value **inside a detected opportunity**, not to resurrect a wallet-copy whitelist.

## Implementation v1

`src/opportunity_wallet_intelligence.py`

The pure causal builder:

- discovers wallets from current episode participation;
- excludes future current events;
- excludes historical outcomes that were unresolved at T0;
- excludes the current episode from prior-history evidence;
- keeps return/holding/notional missingness explicit;
- reports sample-size warnings;
- exposes no trading score or recommendation.

Tests:

`tests/test_opportunity_wallet_intelligence.py`

## North star

`market tells us where to look -> participants tell us who is involved -> history tells us what was knowable about those actors -> execution/flow/risk/regime tell us whether the opportunity is actually attractive and capturable`
