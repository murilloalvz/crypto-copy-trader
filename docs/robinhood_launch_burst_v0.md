# Robinhood / Pons Launch Burst V0

Status: **Market-First, feature-only research track**.

This track is independent from Solana/Pump Launch Burst. No Solana threshold, selector, feature ranking, outcome rule, or economic conclusion is imported into Robinhood.

## Research question

Can the first 1s / 5s / 10s / 30s of a new Pons V2 launch expose causal microstructure features stable enough to justify a later prospective economic hypothesis?

V0 does **not** ask whether any feature is profitable.

## Canonical protocol surface

- Robinhood Chain mainnet, chain id `4663`.
- Factory addresses are treated as versioned evidence, not eternal constants.
- `TokenLaunched(token, curve, deployer, pairToken, launchConfigId, graduationThreshold)` discovers each launch and per-launch curve.
- `CurveBuy(buyer, recipient, quoteIn, tokensOut, fee, tax)` and `CurveSell(seller, recipient, tokensIn, quoteOut, fee, tax)` form the pre-graduation tape.

The production-observed Pons V2 factory used by live integrations is `0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e`. Repository/source revisions may publish other candidate addresses. V0 therefore does not silently trust an address: preflight requires runtime bytecode plus recent `TokenLaunched` activity and selects only a unique active candidate. If more than one candidate is active, the run is held and the factories must be studied as separate strata.

An explicit `--factory-address` override is allowed only after bytecode is observed at that address and is recorded in the preflight artifact.

## Deployed capability binding

Pons public documentation describes a V2 generation with `currentSnipeTaxBps(address)`, while published repository snapshots have at times contained a version mix in which factory source references snipe functions not present in the accompanying curve source. V0 therefore does **not** assign fee/snipe semantics from repository text alone.

After factory discovery, preflight selects a recent real curve and probes deployed bytecode through `eth_call` for:

- `feeBps()`;
- `creatorTaxBps()`;
- `getReserves()`;
- `sellableTokens()`;
- `readyToGraduate()`;
- `graduated()`;
- `currentSnipeTaxBps(address)`.

The first six are required for honest direct BUY/SELL quote state. The resulting `protocol_generation_key` is part of the evidence. A successful `currentSnipeTaxBps` call proves that view exists on the deployed generation; it does not by itself prove a nonzero tax at probe time. If any required core curve view is absent, preflight fails. A core curve without the snipe view is retained as a separate valid generation rather than being silently interpreted as the snipe-enabled generation.

## Headline cohort

V0 headline analysis uses only native-ETH quoted launches:

`pairToken == 0x0000000000000000000000000000000000000000`

Custom quote assets are retained in coverage counts but are not mixed into raw-quote feature distributions.

## Clocks

Two clock domains are retained:

1. `(blockNumber, transactionIndex, logIndex)` for canonical on-chain ordering.
2. `observed_at_ns` for local evidence availability.

Feature windows are gated by `observed_at_ns`. A trade arriving after a cutoff is unavailable to that snapshot even if its block timestamp is earlier.

For polling V0, every batch receives one availability timestamp immediately when `eth_getLogs` returns. Auxiliary block-timestamp lookups happen afterwards and cannot move that availability clock.

## Frozen feature-only windows

`1s`, `5s`, `10s`, `30s`.

No window is primary in V0.

## Feature families

- buy/sell/trade counts and actor counts;
- gross BUY quote input and SELL quote output;
- signed quote flow and signed-flow/activity ratio;
- token demand;
- event-observed fee and creator-tax load;
- opening BUY fee dynamics, interpreted according to the deployed generation capability evidence;
- deployer BUY share;
- top-1 / top-3 buyer concentration;
- actor/recipient mismatch;
- first-trade delay and time to 3/5 trades;
- inter-arrival timing and half-window acceleration;
- effective BUY quote-per-token progression;
- snapshot dispatch lag.

No feature becomes a selector until a feature-only corpus is frozen and audited.

## Pons-specific opening tax

Pons public V2 documentation describes a decaying snipe tax on early BUYs and states that, on the snipe-enabled generation, that opening tax is folded into `CurveBuy.fee`, while creator tax is reported separately in `tax`.

Because deployed generations and published source can drift, V0 always treats `fee` first as **event-observed fee**. The dedicated `fee_dynamics` report measures first/last/min/median observed buy fee, known deployer buys, non-deployer buys and local/chain age. It may be interpreted as base-plus-snipe only when the run's deployed capability probe establishes the snipe-enabled interface and later causal curve state supports the decomposition.

V0 does **not** infer `snipe_tax = fee - assumed_base_fee` without causally observed per-launch fee state. Launch-specific exemptions can exist, so a non-deployer buy is not automatically labelled taxed.

## Direct curve quote V0

`src/pons_v2_curve_quote_v0.py` and `benchmarks.robinhood_launch_burst_v0.direct_quote_state` add a read-only way to separate provider/router coverage from the curve's own mathematical quotability.

The state reader pins every view to one explicit block number and requires the same block hash before and after the read. It records:

- target curve and public recipient;
- factory + deployed generation key;
- block number/hash/timestamp;
- `feeBps` and `creatorTaxBps`;
- tradeable quote/token reserves;
- `sellableTokens`;
- `readyToGraduate` and `graduated`;
- recipient-specific `currentSnipeTaxBps` when the deployed generation supports it;
- raw ABI responses and local observation time.

The pure quote layer then reproduces Pons integer BUY/SELL math, including exact-output `+1` rounding and BUY partial-fill/refund behavior near graduation. A snipe-enabled generation refuses BUY quoting if recipient-specific snipe state was not causally read. SELL is treated closed as soon as `readyToGraduate()` is true, even before `graduated` necessarily flips.

Every result preserves `fill_claimed = false`. Direct Quote V0 is mathematical curve evidence, **not** transaction simulation, landed-fill evidence, a selector, or an economic outcome.

See `docs/pons_direct_quote_v0.md` for the full contract.

## Acquisition V0

`benchmarks.robinhood_launch_burst_v0.live` bootstraps acquisition with standard Robinhood JSON-RPC: `eth_chainId`, `eth_blockNumber`, `eth_getLogs`, `eth_getBlockByNumber`, `eth_getCode`, and `web3_sha3` for event topics.

The collector starts prospectively at `latest + 1`, selects the active Pons V2 factory through live discovery, discovers launches, and tracks only curves still inside the 30-second research horizon.

Default public RPC: `https://rpc.mainnet.chain.robinhood.com`.

For sustained research, set `ROBINHOOD_RPC_URL` to a production endpoint. JSON-RPC polling is a bootstrap path, not the final Signal Plane. Robinhood's public Sequencer Feed is the candidate low-latency acquisition source; a future adapter must emit the same normalized observations and prove parity before replacing polling.

## Capture integrity

Every official discovery corpus must run `benchmarks.robinhood_launch_burst_v0.audit` before feature interpretation. The audit:

- verifies feature-only / outcomes-closed state;
- checks factory discovery provenance;
- detects invalid normalized events;
- detects conflicting block hashes for the same log identity;
- detects duplicate snapshot keys;
- requires every matured 1/5/10/30s snapshot to exist;
- rebuilds every snapshot from `events.jsonl` and requires exact feature parity;
- verifies causal snapshot clocks;
- requires zero transport errors for an official discovery corpus.

Trailing launches whose windows had not matured when the run stopped are not treated as missing.

`benchmarks.robinhood_launch_burst_v0.summarize` runs the integrity audit and opening-fee report automatically for the latest run.

## Hard guards

V0:

- opens no economic outcomes;
- has no profitability label;
- freezes no selector;
- imports no Solana threshold;
- keeps custom-pair launches separate;
- keeps multiple active Pons factories/generations separate;
- binds protocol semantics to deployed capability evidence;
- keeps Social/Event-First separate;
- does not use post-graduation Uniswap V4 activity as pre-graduation evidence;
- does not treat graduation as quality;
- does not convert missing evidence into returns;
- does not call direct curve math a fill or executable transaction.

## Next phases

1. pass network/factory/capability preflight;
2. collect and integrity-audit a feature-only corpus;
3. inspect feature coverage, opening-fee dynamics, missingness and redundancy;
4. freeze exactly one Robinhood-specific hypothesis;
5. freeze entry delay, deployed-generation fee/snipe treatment, slippage, exit and failed-exit policy;
6. open prospective outcomes;
7. compare Robinhood and Solana only as separate strata.

The full sequencing and anti-post-hoc rules are frozen in `docs/robinhood_launch_burst_research_protocol_v0.md`.
