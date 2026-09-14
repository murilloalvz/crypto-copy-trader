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
  - nested batch depth is rejected at `depth >= 16`
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

V0 explicitly does not use Python `hashlib.sha3_256` as a substitute for Ethereum Keccak-256. Canonical transaction hashes, when needed for RPC parity, are resolved through RPC `web3_sha3` after the feed receive clock has already been frozen.

## Pons intent classification

A signed feed transaction may be classified as:

- `PONS_FACTORY_TARGET_INTENT` when its target is the active Pons factory;
- `PONS_CURVE_BUY_INTENT` for a known curve plus deployed/canonical BUY selector;
- `PONS_CURVE_SELL_INTENT` for a known curve plus deployed/canonical SELL selector;
- `PONS_CURVE_OTHER_INTENT` for another call to a known curve.

No intent is marked executed until RPC/log reconciliation proves it.

Factory calls remain generic in V0 because `launchToken` is overloaded and factory generations may change. We do not freeze a launch selector from source text alone.

## WebSocket transport V0

`src/robinhood_nitro_ws_v0.py` implements a minimal read-only client using only Python stdlib socket/TLS primitives.

The current Nitro transport contract is:

- `FeedClientVersion = 2`;
- `FeedServerVersion = 2`;
- request header `Arbitrum-Feed-Client-Version: 2`;
- request header `Arbitrum-Requested-Sequence-Number: <MessageIndex>`;
- response header `Arbitrum-Feed-Server-Version: 2`;
- response header `Arbitrum-Chain-Id: 4663`.

V0 deliberately does **not** advertise `permessage-deflate`. If the server unexpectedly negotiates a WebSocket extension, the handshake is rejected instead of silently changing transport semantics.

The client handles:

- partial TCP reads;
- multiple WebSocket frames coalesced into one TCP receive;
- 7-bit, 16-bit, and 64-bit WebSocket payload lengths;
- fragmented text messages;
- server ping / masked client pong;
- close frames;
- preservation of unread bytes for the next frame.

The local `observed_at_ns` is captured when a complete text message becomes available, before feed parsing or later RPC reconciliation.

## MessageIndex is not eth_blockNumber

`Arbitrum-Requested-Sequence-Number` is a Nitro message index. V0 never derives it from `eth_blockNumber`.

The initial sequence `0` is allowed only as a bootstrap request and is explicitly labeled:

`BOOTSTRAP_ONLY_NOT_LIVE_BOUNDARY`

After at least one message is observed, reconnects request exactly `last_sequence + 1`. Sequence gaps, duplicates, and reorder observations are recorded rather than silently repaired.

## Causal backlog/live bootstrap

V0 does not assume that messages received immediately after connection are live. The public feed can send backlog depending on the requested MessageIndex.

Before the first WebSocket handshake, the capture freezes one canonical RPC head:

- block number;
- block hash;
- block timestamp;
- local `captured_at_ns`.

Raw feed messages are then persisted with their original `observed_at_ns` before parsing.

After capture, each feed `blockHash` may be resolved through `eth_getBlockByHash`. That later lookup is used only to classify the already-observed message relative to the frozen anchor:

- resolved block number `<= anchor block` → `BACKLOG_CONFIRMED_PRECONNECT_HEAD`;
- resolved block number `> anchor block` → `LIVE_CANDIDATE_POST_ANCHOR`;
- missing block hash → `UNKNOWN_NO_FEED_BLOCK_HASH`;
- unresolved block hash → `UNKNOWN_FEED_BLOCK_HASH_UNRESOLVED`.

Only `LIVE_CANDIDATE_POST_ANCHOR` can become feed-latency eligible.

Post-capture resolution may never change the original feed receive clock. A single provider failure while resolving a feed block is isolated as unresolved evidence rather than causing the whole capture to be discarded.

Before latency eligibility is accepted, the original anchor block is re-read by number. Its hash must still match. If not, classification becomes `FAIL_ANCHOR_REORG_GUARD` and all latency eligibility is disabled.

## Raw capture artifacts

`benchmarks/robinhood_sequencer_shadow_v0/capture.py` writes:

- `raw-frames.jsonl` — raw WebSocket text plus immutable receive clock and connection metadata;
- `report.json` — chain, anchor, handshake, reconnect, transport, parser, and sequence continuity accounting.

The raw capture opens no execution, latency-edge, or economic claim.

`benchmarks/robinhood_sequencer_shadow_v0/classify_bootstrap.py` later writes:

- `bootstrap-classifications.jsonl`;
- `bootstrap-report.json`.

This stage determines only whether a feed message is scientifically eligible for later latency comparison.

## Sequencer → RPC reconciliation

`benchmarks/robinhood_sequencer_shadow_v0/reconcile.py` resolves canonical Ethereum transaction identity after observation with RPC `web3_sha3(raw_signed_tx)` and then matches that identity to executed RPC event evidence.

The clocks remain distinct:

1. feed receive clock;
2. tx-hash resolution clock;
3. RPC executed-event observation clock.

A feed intent with no observed executed event remains `UNKNOWN`; it is not assigned a failed trade or zero return.

Only matched, bootstrap-eligible executed evidence may contribute to a future feed-vs-RPC latency distribution.

## Scientific clocks

The local feed receive clock is captured before parsing and is the causal availability clock for feed evidence.

Any later operation — block-hash resolution, transaction-hash resolution, receipt lookup, log matching, feature reconstruction — receives its own clock and may not move the original feed observation earlier.

## Shadow requirement

The feed cannot replace RPC acquisition merely because it is faster.

A shadow run must establish:

1. feed transport health;
2. parser accounting;
3. sequence continuity and reconnect behavior;
4. backlog/live separation against a frozen pre-handshake anchor;
5. anchor reorg guard;
6. transaction-intent identity;
7. RPC execution reconciliation;
8. executed Pons event coverage;
9. latency delta on matched, latency-eligible evidence;
10. zero leakage from future receipt/log state into feed-time features.

Only then may the feed become a Signal Plane source.

## Hard guards

V0:

- opens no economic outcomes;
- creates no selector;
- makes no profitability claim;
- never treats feed receipt as EVM success;
- never treats a feed BUY intent as a `CurveBuy` event;
- never uses SHA3-256 as Ethereum Keccak-256;
- never treats initial sequence `0` as a live boundary;
- never derives Nitro MessageIndex from L2 block number;
- never makes unresolved/hashless feed messages latency eligible;
- disables latency eligibility if the frozen anchor fails its reorg guard;
- keeps raw feed evidence for replay;
- keeps Social/Event-First separate.
