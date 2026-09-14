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

The production-observed Pons V2 factory used by multiple live-chain integrations is `0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e`. A newer Pons repository revision has also published `0x7E1EAbd52Ae29598e6483F72dCf1a70b14284dB8`. V0 therefore does not silently trust either address: preflight requires runtime bytecode plus recent `TokenLaunched` activity and selects only a unique active candidate. If more than one candidate is active, the run is held and the factories must be studied as separate strata.

An explicit `--factory-address` override is allowed only after bytecode is observed at that address and is recorded in the preflight artifact.

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
- observed fee and creator-tax load;
- opening BUY fee share, which includes Pons snipe tax folded into `fee`;
- deployer BUY share;
- top-1 / top-3 buyer concentration;
- actor/recipient mismatch;
- first-trade delay and time to 3/5 trades;
- inter-arrival timing and half-window acceleration;
- effective BUY quote-per-token progression;
- snapshot dispatch lag.

No feature becomes a selector until a feature-only corpus is frozen and audited.

## Pons-specific opening tax

Pons V2 documents a decaying snipe tax on early BUYs. On `CurveBuy`, that opening tax is folded into `fee`, while creator tax is reported separately in `tax`.

V0 therefore has a dedicated feature-only `fee_dynamics` report that measures first/last/min/median event-observed buy fee, known deployer-exempt buys, non-deployer buys, and local/chain age. It does **not** infer `snipe_tax = fee - assumed_base_fee` without causally observed curve fee state. Launch-specific exemptions can also exist, so a non-deployer buy is not automatically labelled taxed.

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
- keeps multiple active Pons factories separate;
- keeps Social/Event-First separate;
- does not use post-graduation Uniswap V4 activity as pre-graduation evidence;
- does not treat graduation as quality;
- does not convert missing evidence into returns.

## Next phases

1. pass network/factory preflight;
2. collect and integrity-audit a feature-only corpus;
3. inspect feature coverage, opening-fee dynamics, missingness and redundancy;
4. freeze exactly one Robinhood-specific hypothesis;
5. freeze entry delay, snipe-tax treatment, fees, slippage, exit and failed-exit policy;
6. open prospective outcomes;
7. compare Robinhood and Solana only as separate strata.

The full sequencing and anti-post-hoc rules are frozen in `docs/robinhood_launch_burst_research_protocol_v0.md`.
