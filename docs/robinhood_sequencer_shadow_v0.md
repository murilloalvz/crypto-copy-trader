# Robinhood Sequencer Shadow V0

Status: **Market-First acquisition research, INTENT-ONLY**.

Robinhood Chain publishes a Nitro sequencer feed at:

`wss://feed.mainnet.chain.robinhood.com`

Robinhood's full-node documentation wires the same feed into Nitro with:

`--node.feed.input.url=wss://feed.mainnet.chain.robinhood.com`

The purpose of this track is to test whether that feed can provide earlier causal evidence than JSON-RPC log polling without changing the executed-event semantics used by Launch Burst.

## Critical boundary: intent is not execution

Nitro's broadcast feed carries `MessageWithMetadata` / L2 messages before or around execution availability. It is **not** a receipt/log stream.

Therefore V0 may infer only transaction intent from the feed:

- signed transaction target (`to`);
- native value;
- calldata;
- calldata selector;
- feed sequence number;
- Nitro/L1 timestamp metadata;
- local receive clock.

It may **not** infer from feed presence alone:

- EVM success;
- emitted `TokenLaunched`, `CurveBuy`, or `CurveSell` logs;
- actual token output;
- post-trade reserves;
- graduation;
- landed fill economics.

Executed Pons evidence remains the canonical RPC/log track. Feed evidence is reconciled to it later.

## Wire-format provenance

V0 is pinned to Nitro feed version 1 as documented in Offchain Labs Nitro commit:

`a618155919315241665356fe60f3cd00d66d5e46`

Relevant upstream contracts:

- `broadcaster/message/message.go`
  - `BroadcastMessage.version`
  - `messages[]`
  - `BroadcastFeedMessage.sequenceNumber`
  - `message`
  - optional `blockHash`
  - `signatureV2`
  - optional `blockMetadata`
- `arbos/arbostypes/messagewithmeta.go`
  - `message`
  - `delayedMessagesRead`
- `arbos/arbostypes/incomingmessage.go`
  - L1 message kind
  - sender
  - block/timestamp metadata
  - `l2Msg` byte payload
- `arbos/parse_l2.go`
  - L1 kind `3` = L2 message
  - L2 kind `3` = nested batch
  - L2 kind `4` = signed Ethereum transaction
- `arbos/util/util.go`
  - nested batch elements use an 8-byte big-endian unsigned length prefix.

Go `encoding/json` serializes the byte slices as base64 strings. V0 tests against the serialization example shipped in Nitro itself.

## Signed transaction subset

The pure parser recognizes ordinary signed Ethereum transactions accepted by Nitro's signed-tx path:

- legacy RLP;
- EIP-2930 type `0x01`;
- EIP-1559 type `0x02`.

From those envelopes it extracts only:

- target address;
- value;
- calldata;
- four-byte calldata selector;
- raw signed transaction bytes;
- local SHA-256 fingerprint for evidence-file deduplication.

The SHA-256 fingerprint is **not** an Ethereum transaction hash.

V0 explicitly does not use Python `hashlib.sha3_256` as a substitute for Ethereum Keccak-256. Canonical transaction hashes, when needed for RPC parity, must be resolved with a real Keccak implementation or an RPC `web3_sha3` reconciliation step outside the hot observation clock.

## Pons intent classification

A signed feed transaction may be classified as:

- `PONS_FACTORY_TARGET_INTENT` when its target is the active Pons factory;
- `PONS_CURVE_BUY_INTENT` for a known curve plus deployed/canonical BUY selector;
- `PONS_CURVE_SELL_INTENT` for a known curve plus deployed/canonical SELL selector;
- `PONS_CURVE_OTHER_INTENT` for another call to a known curve.

No intent is marked executed until RPC/log reconciliation proves it.

Factory calls remain generic in V0 because `launchToken` is overloaded and factory generations may change. We do not freeze a launch selector from source text alone.

## Scientific clocks

The local feed receive clock is captured before parsing and is the causal availability clock for feed evidence.

Any later operation — transaction-hash resolution, receipt lookup, log matching, feature reconstruction — receives its own clock and may not move the original feed observation earlier.

## Shadow requirement

The feed cannot replace RPC acquisition merely because it is faster.

A later shadow run must establish:

1. feed transport health;
2. parser accounting;
3. transaction-intent identity;
4. RPC execution reconciliation;
5. executed Pons event coverage;
6. duplicate/reconnect/backlog behavior;
7. latency delta on matched evidence;
8. zero leakage from future receipt/log state into feed-time features.

Only then may the feed become a Signal Plane source.

## Hard guards

V0:

- opens no economic outcomes;
- creates no selector;
- makes no profitability claim;
- never treats feed receipt as EVM success;
- never treats a feed BUY intent as a `CurveBuy` event;
- never uses SHA3-256 as Ethereum Keccak-256;
- keeps raw feed evidence for replay;
- keeps Social/Event-First separate.
