# PumpSwap Native Market Stream v1 — Design Freeze

Date: 2026-09-03

Mode: **PAPER / RESEARCH / READ ONLY**

## Purpose

Extend native market acquisition beyond the Pump bonding curve without changing Market Opportunity Radar thresholds or using economic outcomes.

Target path:

`Solana logsSubscribe -> PumpSwap Anchor events -> causal pool resolution -> MarketTradeObservation / MarketLifecycleObservation -> existing Market Radar`

PumpSwap program:

`pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`

## Official event identities

Current Pump public IDL defines:

- `BuyEvent` discriminator: `[103, 244, 82, 31, 44, 245, 119, 119]`;
- `SellEvent` discriminator: `[62, 47, 55, 10, 165, 3, 220, 42]`;
- `CreatePoolEvent` discriminator: `[177, 49, 12, 210, 160, 118, 167, 116]`;
- `Pool` account discriminator: `[241, 154, 109, 4, 17, 177, 109, 188]`.

The adapter decodes only the stable causal prefix required by the research contract. Unknown trailing fields are intentionally ignored.

## Critical identity rule

PumpSwap `BuyEvent` and `SellEvent` expose `pool` and `user`, but do not directly expose `base_mint`.

Therefore **trade events alone are insufficient to identify the token**.

The adapter must never infer a mint from transaction position, log order, UI metadata or unrelated balances.

A trade is eligible for market persistence only after a causal `pool -> base_mint, quote_mint` mapping is available.

## Pool resolution

Resolution order:

1. `CreatePoolEvent` observed in the current stream;
2. run-scoped persisted pool mapping already observed earlier;
3. explicit `getAccountInfo(pool)` hydration of the PumpSwap `Pool` account;
4. unresolved if all above fail.

For RPC hydration, the mapping availability clock is the time the response is learned by the collector. Hydration cannot be backdated to pool creation.

Pool mappings are cached after successful resolution to prevent one RPC request per trade.

## Clock semantics

Trade:

- `chain_time` = PumpSwap event `timestamp`;
- WebSocket delivery time records when the raw trade event became visible;
- the persisted resolved `MarketTradeObservation.observed_at` is `max(websocket_observed_at, pool_mapping_observed_at)`.

That final rule is mandatory because a trade whose pool identity was hydrated later was not fully usable as a token-specific observation at the earlier WebSocket timestamp. Persisting it at the earlier time would backdate information availability.

Pool mapping:

- CreatePool mapping `observed_at` = local WebSocket delivery time;
- hydrated mapping `observed_at` = local time after the RPC response is obtained;
- first-seen mapping time/provenance remains authoritative even if a later independent source corroborates the same pool identity.

Lifecycle:

- only CreatePoolEvent provides a true `market_started_at` for this adapter v1;
- hydration of an old Pool account does not invent a market start time.

## Persistence identity

Trade event keys:

- `pumpswap-buy:<signature>:<event-index>`;
- `pumpswap-sell:<signature>:<event-index>`.

Lifecycle key:

- `pumpswap-create:<signature>:<event-index>`.

Pool mapping key is run + pool address.

`transaction_key=<signature>` is preserved so the existing transaction-aware radar can distinguish raw events from independent transactions.

## Missingness

The v1 adapter does not infer USD notional or USD price from raw PumpSwap amounts.

`notional_usd=None` and `price_usd=None` remain explicit until quote-asset identity, decimals and a causal USD conversion surface are available.

Unknown/unresolved pools do not become fake token trades; they are counted as unresolved acquisition observations in smoke telemetry.

## Operational guardrails

- one WebSocket connection with bounded reconnect backoff;
- explicit commitment;
- failed Solana transactions ignored;
- pool-account hydration uses existing Solana RPC retry/fallback infrastructure;
- successful pool mappings cached;
- no order signing/submission;
- no detector threshold change;
- no 12-hour acquisition before bounded local smoke passes.

## Validation gate

Unit/regression tests must cover:

- exact program subscription;
- Buy/Sell/CreatePool prefix decoding;
- Pool account decoding;
- clock rejection for impossible observations;
- CreatePool mapping without RPC;
- hydrated mapping availability semantics, including effective trade `observed_at`;
- cache reuse;
- unresolved pool behavior;
- transaction identity preservation;
- pool mapping replay/backdating/conflict rules;
- failed transaction rejection.

After CI passes, run a 120-second local PumpSwap smoke and measure acquisition volume, pool resolution coverage, hydration load/failures, unresolved trades and token/wallet diversity.

This gate validates data plumbing only, not economic edge.
