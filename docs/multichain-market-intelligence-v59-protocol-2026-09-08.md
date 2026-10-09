# Multichain Market Intelligence v59 — research architecture

Date: 2026-09-08
Mode: PAPER / RESEARCH / READ ONLY

## Purpose

Prepare the market-first architecture to compare opportunity formation across chains without changing the currently running Solana v55 experiment.

v59 is an identity and adapter milestone. It does not activate a second live collector, alter the Solana detector, or claim that one chain has economic edge.

## Current chain priorities

### 1. Solana — active laboratory

Solana remains the validated acquisition and systems laboratory. Existing detector thresholds, v54 systems profile, v55 discovery contract, route-only economics, and causal lineage remain frozen.

### 2. Robinhood Chain / Pons — next research target

Robinhood Chain is the first non-Solana target because current public on-chain research shows:

- a fast-growing memecoin market with meaningful wallet and trade activity;
- Pons exposes an explicit bonding-curve lifecycle and graduation to Uniswap v4;
- launch, curve-trade, graduation, holder and DEX data are observable from public/indexed sources;
- the chain is EVM-compatible and has standard JSON-RPC/WebSocket infrastructure;
- market participation appears structurally different from Solana, making it scientifically useful as an independent environment rather than merely more sample size.

This prioritization is a research decision, not an instruction to move capital or abandon Solana.

### 3. BNB Chain / Four.meme — secondary comparison target

BNB Chain remains relevant because Four.meme has ongoing launch/trading activity and an explicit bonding-curve-to-DEX lifecycle. It is a useful later replication environment if Robinhood/Solana findings warrant cross-chain testing.

### 4. Base — observe, lower priority

Base remains technically easy to support through EVM adapters, but current launchpad activity is materially smaller than the leading Solana/Robinhood/BNB venues. It should not consume engineering priority solely because EVM support is convenient.

## Architectural rule: adapters at the edges

Do not refactor the validated Solana pipeline into a generic abstraction while v55 is active.

Instead:

`chain-specific stream -> chain adapter -> canonical v59 observation -> future shared intelligence`

Current Solana observations are wrapped without semantic mutation. Future Robinhood observations will be normalized into the same contract while retaining chain-native provenance.

## Canonical identity

Every future multichain asset and event must include:

- chain namespace (`solana` or `eip155` initially);
- chain reference (`mainnet` for current Solana adapter; numeric EVM chain id for EIP-155);
- native asset address/mint;
- native event key, namespaced by chain and asset;
- source provider;
- chain time and first observed time;
- transaction key when available;
- block number/event index when the source exposes them.

A token address or transaction identifier alone is never globally unique.

## Lifecycle semantics

The shared lifecycle vocabulary supports at least:

- `market_started`
- `pool_created`
- `graduated`
- `venue_changed`

A Pons graduation must remain a graduation event. It must not be collapsed into a generic market start merely to fit Solana-era storage.

## Cross-chain comparability rules

Do not compare raw thresholds such as `6 events / 30s` across chains until the acquisition semantics are proven equivalent.

Before any cross-chain economic experiment, freeze and audit:

1. what constitutes one trade/event;
2. wallet identity semantics (signer vs router/bundler);
3. transaction de-duplication;
4. launch/market-start clock;
5. lifecycle stage;
6. USD notional methodology;
7. observation latency;
8. missingness;
9. venue coverage;
10. quote/execution semantics.

The goal is to compare opportunity dynamics, not force identical thresholds onto structurally different markets.

## Robinhood/Pons-specific research questions

A future read-only adapter should be able to answer causally:

- how quickly unique buyers accumulate after launch;
- event-rate acceleration before graduation;
- whether buyer breadth grows or activity repeats among a small wallet set;
- distance/time to graduation;
- what changes immediately before and after graduation;
- whether profitable entries concentrate before curve completion, near graduation, or after Uniswap migration;
- whether exceptional wallets scale out rather than exit once;
- whether creator/deployer/funding relationships distinguish poor outcomes from organic expansion.

These questions are hypotheses for future discovery, not filters.

## Scientific boundary with v55

v59 cannot:

- add Robinhood/BNB/Base rows to v55;
- change v55 features or candidate selection;
- use v55 outcomes to design a Robinhood threshold;
- use a cross-chain result to rescue a v55 failure;
- change the Solana detector while v55 is running.

## Promotion gate

No non-Solana chain becomes an economic execution target until it independently demonstrates:

1. reliable causal acquisition;
2. explicit lineage and missingness;
3. stable latency/coverage under realistic load;
4. a prospective economic hypothesis on fresh data;
5. executable/shadow economics after fees, slippage and landing assumptions.

Until then, multi-chain means market intelligence and research only.