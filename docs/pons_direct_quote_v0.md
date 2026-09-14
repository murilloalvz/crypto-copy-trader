# Pons V2 Direct Curve Quote V0

Status: **read-only infrastructure / research support**.

This module answers a narrow question:

> Given causally observed state from one deployed Pons V2 bonding curve, what BUY or SELL does the published integer curve math imply?

It does **not** claim that a transaction can be built, simulated, landed, or filled at that result.

## Separation of concerns

The path is intentionally split into four independent steps:

1. factory discovery;
2. deployed protocol capability detection;
3. causal curve-state read pinned to one block;
4. pure integer quote math.

A failure in one step is never rewritten as another kind of evidence.

## Generation binding

Pons public source and documentation have shown version drift. V0 therefore does not assign snipe-tax semantics from a repository snapshot alone.

`probe_protocol_capabilities_v0` requires these core views for direct quote state:

- `feeBps()`;
- `creatorTaxBps()`;
- `getReserves()`;
- `sellableTokens()`;
- `readyToGraduate()`;
- `graduated()`.

`currentSnipeTaxBps(address)` defines a separate deployed generation when it is callable.

Two snipe modes exist:

- `LIVE_SNIPE_VIEW`: a recipient-specific `currentSnipeTaxBps` value is required for the target quote;
- `PROVEN_NO_SNIPE_VIEW`: the capability probe identified a base-curve generation without that view and the quote state carries zero snipe tax.

Missing snipe state on a snipe-enabled generation is an error. It is never converted to zero.

## Causal state

`direct_quote_state.read_curve_quote_state_v0`:

- captures one latest block number;
- uses that explicit block tag for every `eth_call`;
- requires bytecode at the target curve at that block;
- reads reserves, ordinary fees, graduation state, and recipient-specific snipe state when supported;
- reads the block header before and after the state calls;
- rejects the sample if the pinned block hash changes;
- records block number, block hash, timestamp, generation key, factory, target curve, recipient, raw ABI results, and local observation time.

This avoids silently mixing reserves from one state with tax or graduation state from a later block.

## BUY math

For a full BUY, V0 follows Pons integer ordering:

1. calculate base fee on gross quote input;
2. calculate creator tax on gross quote input;
3. for a proven snipe-enabled generation, calculate recipient-specific snipe tax;
4. subtract charges from gross quote input;
5. apply the constant-product exact-input formula to net curve input.

The recipient-specific snipe rate is capped so ordinary fees + creator tax + snipe tax still leave the documented minimum 1% net input.

If the result exceeds `sellableTokens`, the quote is clamped to that allocation. V0 then:

1. calculates the exact net quote required for the clamped token output using Pons exact-output math and its `+1` raw-unit rounding;
2. grosses that net amount back up using ceiling division;
3. caps actual spend at the requested input;
4. recomputes charge buckets on actual spend;
5. returns the remainder as a mathematical refund.

## SELL math

SELL has no snipe-tax leg in V0.

1. token input is applied to the constant-product exact-input formula;
2. base fee is charged on gross quote output;
3. creator tax is charged on gross quote output;
4. both are subtracted to produce quote output.

SELL is classified closed when either:

- `graduated == true`; or
- `readyToGraduate == true`, even if the graduated flag has not yet been set.

The second guard matters because the Pons curve source explicitly closes SELL at the exhausted sellable allocation before the graduation transaction necessarily completes.

## Evidence labels

Every quote preserves:

- `mathematically_quotable`;
- `fill_claimed = false`;
- state observation time;
- protocol generation key.

The operational probe additionally emits:

- factory discovery evidence;
- protocol capability evidence;
- pinned-block state evidence;
- optional BUY quote;
- optional SELL quote;
- `economic_outcomes_opened = false`.

## Hard guards

V0 must never:

- sign or submit a transaction;
- call a mathematical result a landed fill;
- infer zero snipe tax when the deployed generation exposes a snipe view but recipient state was not read;
- mix state from multiple block tags;
- ignore `readyToGraduate()` for SELL;
- turn provider/router failure into zero economic return;
- use this module to select a profitable feature or threshold.

## Operational command

Once a target launch curve and recipient are known, the read-only probe is:

```powershell
& 'C:\Users\LocalUser\Projetos\crypto-copy-trader\.venv\Scripts\python.exe' `
  -m benchmarks.robinhood_launch_burst_v0.direct_quote `
  --curve '<CURVE_ADDRESS>' `
  --recipient '<PUBLIC_RECIPIENT_ADDRESS>' `
  --quote-in-raw '<RAW_QUOTE_AMOUNT>'
```

`ROBINHOOD_RPC_URL` may be set in `.env`. The public RPC remains a bootstrap source, not latency-grade Signal Plane infrastructure.

The probe is read-only. Do not supply a private key or seed phrase.
