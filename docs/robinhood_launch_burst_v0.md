# Robinhood / Pons Launch Burst V0

Status: **Market-First, feature-only research track**.

This track is independent from Solana/Pump Launch Burst. No Solana threshold, selector, feature ranking, outcome rule, or economic conclusion is imported into Robinhood.

## Research question

Can the first 1s / 5s / 10s / 30s of a new Pons V2 launch expose causal microstructure features stable enough to justify a later prospective economic hypothesis?

V0 does **not** ask whether any feature is profitable.

## Canonical protocol surface

- Robinhood Chain mainnet, chain id `4663`
- Pons V2 factory `0x7eD598BcEf8bd9Edd8C97A195C6d13f40801EC7e`
- `TokenLaunched(token, curve, deployer, pairToken, launchConfigId, graduationThreshold)` discovers each launch and per-launch curve.
- `CurveBuy(buyer, recipient, quoteIn, tokensOut, fee, tax)` and `CurveSell(seller, recipient, tokensIn, quoteOut, fee, tax)` form the pre-graduation tape.

## Headline cohort

V0 headline analysis uses only native-ETH quoted launches:

`pairToken == 0x0000000000000000000000000000000000000000`

Custom quote assets are retained in coverage counts but are not mixed into raw-quote feature distributions.

## Clocks

Two clock domains are retained:

1. `(blockNumber, transactionIndex, logIndex)` for canonical on-chain ordering.
2. `observed_at_ns` for local evidence availability.

Feature windows are gated by `observed_at_ns`. A trade arriving after a cutoff is unavailable to that snapshot even if its block timestamp is earlier.

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

Pons V2 applies a decaying snipe tax to early BUYs. On `CurveBuy`, that opening tax is folded into `fee`, while creator tax is reported separately in `tax`. V0 therefore measures the fee load actually observed in the event instead of hard-coding a nominal schedule.

## Acquisition V0

`benchmarks.robinhood_launch_burst_v0.live` bootstraps acquisition with standard Robinhood JSON-RPC: `eth_chainId`, `eth_blockNumber`, `eth_getLogs`, `eth_getBlockByNumber`, and `web3_sha3` for event topics.

The collector starts prospectively at `latest + 1`, discovers launches from the Pons V2 factory, and tracks only curves still inside the 30-second research horizon.

Default public RPC: `https://rpc.mainnet.chain.robinhood.com`.

For sustained research, set `ROBINHOOD_RPC_URL` to a production endpoint. JSON-RPC polling is a bootstrap path, not the final Signal Plane. Robinhood's sequencer feed is the candidate low-latency acquisition source; a future adapter must emit the same normalized observations and prove parity before replacing polling.

## Hard guards

V0:

- opens no economic outcomes;
- has no profitability label;
- freezes no selector;
- imports no Solana threshold;
- keeps custom-pair launches separate;
- keeps Social/Event-First separate;
- does not use post-graduation Uniswap V4 activity as pre-graduation evidence;
- does not treat graduation as quality;
- does not convert missing evidence into returns.

## Next phases

1. collect a sufficient feature-only corpus;
2. audit coverage, missingness and feature redundancy;
3. freeze exactly one Robinhood-specific hypothesis;
4. freeze entry delay, snipe-tax treatment, fees, slippage, exit and failed-exit policy;
5. open prospective outcomes;
6. compare Robinhood and Solana only as separate strata.
