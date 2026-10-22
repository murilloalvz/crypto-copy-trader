# Pump Market Stream v1 — Native Acquisition Design

Date: 2026-09-03

Mode: **PAPER / RESEARCH / READ ONLY / NO LIVE EXECUTION**

## Goal

Provide the first real-time market-event adapter for Market Opportunity Radar v1 without depending on a tracked-wallet allowlist or UI scraping.

Pipeline:

`Solana logsSubscribe -> Pump program logs -> Anchor TradeEvent -> causal MarketTradeObservation -> SQLite`

This stage validates acquisition plumbing only. It does not create BUY decisions and does not establish edge.

## Why native logs first

Solana `logsSubscribe` supports a `mentions` filter for one pubkey per subscription. Pump publishes its bonding-curve program ID and Anchor IDL publicly. The Pump TradeEvent includes a stable causal prefix containing mint, SOL amount, token amount, buy/sell flag, user and timestamp.

Using this event directly avoids one `getTransaction` hydration request per observed bonding-curve trade and therefore reduces latency and RPC load.

## Program

Pump bonding curve:

`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`

TradeEvent discriminator at freeze time:

`[189, 219, 127, 211, 78, 230, 97, 238]`

Decoded v1 prefix:

1. mint: pubkey
2. sol_amount: u64
3. token_amount: u64
4. is_buy: bool
5. user: pubkey
6. timestamp: i64

Later event fields are intentionally ignored by the v1 decoder.

## Causal clocks

- `chain_time` = Pump event timestamp.
- `observed_at` = local receipt time of the WebSocket notification.

The adapter rejects an impossible row where `observed_at < chain_time`.

## Persistence

Event key:

`pump:<signature>:<event-index>`

Source provider:

`solana_logs_subscribe`

Venue:

`pump_bonding_curve`

Deduplication remains run-scoped through Market Observation Store.

## Missingness and quote assets

Pump now supports quote assets beyond SOL. The stable prefix decoded here does not include the later `quote_mint` field.

Therefore v1 only persists TradeEvents whose `sol_amount > 0`. Non-SOL quote events remain unsupported rather than being silently misclassified.

USD notional and USD price remain missing at this stage. They must be enriched causally later from an explicit market/execution source.

## Reconnect behavior

The async iterator:

- converts configured HTTP(S) RPC URL to WS(S);
- subscribes at explicit commitment;
- uses ping/pong timeouts;
- reconnects with bounded exponential backoff;
- resets backoff after a successful subscription;
- does not hide malformed causal events.

## Smoke gate

`pump_market_stream_smoke.py` is intentionally bounded to 1–900 seconds.

First operational smoke should use 120 seconds at `confirmed` commitment and answer only:

- does the provider accept `logsSubscribe`?
- do Pump TradeEvents decode live?
- do causal timestamps remain valid?
- are events persisted idempotently?
- how many decoded events/tokens/wallets arrive?
- does the user's RPC endpoint sustain the burst?

No long acquisition run should start from this adapter alone.

## Next adapter

PumpSwap must be implemented separately from its own official IDL/event schema. Do not infer PumpSwap trades through Pump bonding-curve TradeEvent assumptions.
