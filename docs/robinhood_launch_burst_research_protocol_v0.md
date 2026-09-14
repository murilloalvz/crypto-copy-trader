# Robinhood / Pons Launch Burst — Research Protocol V0

Status: **Market-First research track, independent from Solana/Pump and Social/Event-First.**

This document governs the Robinhood/Pons launch-burst line before any economic
outcome is opened.

## 1. Research question

Does early causal market structure around a newly launched Pons V2 bonding curve
contain prospective information that can support a positive net economic execution
hypothesis under a separately frozen execution contract?

V0 does **not** assume that Robinhood is better than Solana, that earlier is always
better, or that the Solana selector transfers across chains.

## 2. Independent stratum

Robinhood/Pons is its own research stratum.

Do not import from Solana/Pump:

- the `signed_flow_over_event_reserve >= 0.08` selector;
- the 5-second primary window;
- the 2-second execution latency assumption;
- any economic result;
- any post-graduation PumpSwap conclusion.

The only things shared are generic scientific contracts: causal clocks, immutable
artifacts, missingness, provenance, replayability and prospective validation.

## 3. Protocol surface

Pons V2 launches begin on one bonding curve per token and later graduate into a
locked Uniswap V4 pool.  V0 studies **pre-graduation curve activity only**.

Canonical event family:

- factory `TokenLaunched` -> launch anchor + curve address;
- curve `CurveBuy` -> quote in / tokens out / fee / creator tax;
- curve `CurveSell` -> tokens in / quote out / fee / creator tax.

The acquisition layer must preserve:

- `block_number`;
- `transaction_index`;
- `log_index`;
- `transaction_hash`;
- `block_hash`;
- local `observed_at_ns` availability clock;
- block timestamp as an independent chain-time field.

`observed_at_ns` decides feature causality.  Block time is descriptive and may be
used to study protocol mechanisms such as the opening fee window, but it does not
backdate local availability.

## 4. Factory drift policy

Factory addresses are versioned evidence, not eternal constants.

Before every live capture:

1. require Robinhood Chain ID 4663;
2. derive/verify the `TokenLaunched` topic;
3. require runtime bytecode at a candidate factory;
4. inspect recent `TokenLaunched` activity;
5. select a factory only when discovery is unique or an explicit operator override
   has bytecode evidence;
6. if multiple factories are active, capture them as separate strata. Never merge
   them merely because the event signature matches.

## 5. Headline quote cohort

V0 headline analysis uses native-ETH quoted Pons V2 launches only.

Custom-pair launches remain preserved as coverage evidence but are excluded from raw
quote-flow distributions because quote raw units are not comparable across assets.
A future custom-pair study must normalize by a separately frozen quote-value source
and is not part of V0.

## 6. Feature windows

Exploratory feature-only horizons are fixed before outcomes:

- 1 second
- 5 seconds
- 10 seconds
- 30 seconds

These are **candidate observation horizons**, not a selector and not a claim that a
particular horizon is economically optimal.

## 7. Initial feature families

Allowed feature-only families include:

### Flow

- trade count / rate;
- gross buy quote;
- gross sell quote;
- signed quote flow;
- signed quote flow / gross activity;
- token demand / supply balance;
- half-window acceleration.

### Participation structure

- unique buyers / sellers / recipients;
- top-1 and top-3 buyer quote concentration;
- deployer participation;
- recipient mismatch rate;
- time to 3 / 5 trades;
- inter-arrival timing.

### Opening-fee dynamics

Pons documents that on buys `CurveBuy.fee` contains the base trade fee plus any
opening snipe tax, while `CurveBuy.tax` is the creator tax.  Therefore V0 may measure:

- observed buy fee bps;
- observed total charge bps;
- first/last/min/median observed buy fee;
- first non-deployer observed fee;
- fee decay over a causal window;
- local and chain age of buys.

V0 must **not** label `fee - assumed_base_fee` as snipe tax unless the curve's causal
fee state was actually observed.  Deployer buys are known exempt; other addresses
may also have launch-specific exemptions, so `non-deployer` does not mean `taxed`.

### Price path

- first/last effective quote-per-token among observed buys;
- last/first effective price ratio.

No feature in this section is an approved trading rule.

## 8. Capture-quality gate

Before feature interpretation, the run must pass the outcome-blind capture audit:

- feature-only = true;
- economic outcomes closed;
- selector not frozen;
- factory discovery PASS;
- zero invalid normalized events;
- zero conflicting block hashes for the same log identity;
- zero duplicate snapshot keys;
- all matured snapshots present;
- exact feature replay from normalized events;
- causal snapshot clocks;
- transport errors = 0 for an official discovery corpus.

Trailing launches whose horizons had not matured when capture stopped are not counted
as missing snapshots.

## 9. Discovery -> prospective discipline

### Phase R0 — acquisition validation

Goal: prove that the collector sees launches/trades with bounded lag and complete,
replayable artifacts.  No feature selection.

### Phase R1 — feature-only discovery

Use one or more audited corpora to describe distributions, coverage, redundancy and
stability across 1/5/10/30 seconds.  No future prices/returns may be joined.

### Phase R2 — hypothesis preregistration

Choose a **small, explicit** candidate hypothesis using feature-only evidence. Freeze:

- stratum/factory generation;
- quote cohort;
- horizon;
- feature(s);
- operator/threshold or ranking rule;
- any confirmation rule;
- source feature corpus hash;
- preregistration self-hash.

Do not open outcomes before this artifact exists.

### Phase R3 — execution contract

Freeze execution assumptions independently of realized returns, including:

- signal-to-entry latency;
- entry route/curve state source;
- opening fee / snipe-tax treatment;
- creator tax;
- slippage / gas / other costs;
- position size;
- partial-fill policy near graduation;
- exit route and horizon;
- unexitable policy;
- graduation-transition policy.

### Phase R4 — prospective economics

Only after R2 and R3 are frozen may future economic outcomes be opened.

Provider or acquisition unavailability is reported separately from economic returns.
Do not silently convert missing provider coverage into zero-return trades.

## 10. Solana comparison

The first objective is to establish whether each chain has an independently supported
hypothesis.  A cross-chain comparison is a later experiment.

Do not compare raw throughput or returns until the compared runs have explicit:

- clock semantics;
- execution costs;
- latency assumptions;
- entry/exit definitions;
- failure policies.

A Robinhood + Solana convergence rule must not be created merely because one chain's
result suggests a feature that happens to look useful on the other.

## 11. Social/Event separation

Social/Event-First remains independent.  Robinhood social/narrative evidence may be
collected in parallel but cannot be used to choose or rescue the Market-First selector
until both tracks have independent prospective evidence and a new convergence
hypothesis is preregistered.

## 12. Current V0 non-goals

V0 does not:

- trade;
- sign or submit transactions;
- use private keys;
- choose a selector;
- read future outcomes;
- claim Pons is superior to Pump;
- merge custom quote assets;
- use the public RPC as a production latency claim;
- claim the raw Nitro sequencer feed has been integrated;
- infer exact snipe tax without causal curve-state evidence.
