# Market Opportunity Radar v1.1 — Transaction-Awareness Amendment

Date: 2026-09-03

Mode: **PAPER / RESEARCH / READ ONLY**

Status: **pre-acquisition methodological amendment based on live plumbing evidence, not economic outcomes**.

## Trigger for this amendment

The first bounded native Pump stream smoke ran for 120.2 seconds and observed:

- 3,476 log notifications;
- 3,688 decoded Pump `TradeEvent`s;
- 3,600 persisted SOL-paired market observations;
- 223 unique tokens;
- 1,984 unique wallets.

The output also showed signatures containing multiple decoded `TradeEvent`s, including transactions with four events.

This means raw event count and independent transaction count are not interchangeable.

## Frozen methodological change

`MarketTradeObservation` now supports an optional `transaction_key`.

For native Pump observations the transaction key is the Solana signature.

The raw event store still retains every decoded TradeEvent. No event is deleted merely because other events share its signature.

The radar now separately records:

- fast raw event count;
- fast unique wallet count;
- fast unique transaction count when transaction identity is available;
- transaction-identity coverage.

When transaction identity coverage is complete, a movement trigger additionally requires at least **4 unique transactions** in the fast window.

This new threshold is an acquisition-integrity guard, not a profitability-optimized parameter. It prevents one multi-event transaction/bundle from satisfying market-breadth evidence by itself.

If transaction identity is unavailable for a legacy/provider source, missingness remains explicit and the legacy source is not silently reclassified as having zero independent transactions.

## Lifecycle improvement

The native Pump adapter also decodes official `CreateEvent` payloads and persists market lifecycle observations. This allows `fresh_market_burst` to use a causal token start timestamp instead of guessing token age from first observed trade.

## Bridge behavior

The new acquisition bridge is:

`Pump notification -> persist raw trade/lifecycle -> load causal 300s token state -> transaction-aware radar -> opportunity episode`

The bridge does **not** freeze `decision_as_of`.

`decision_as_of` remains reserved for the later enrichment stage after mandatory execution/risk/regime/wallet-evidence attempts have completed. This preserves the true information-availability clock.

## No economic retuning

No P&L, future token outcome, return label, win rate or economic replay was consulted to make this amendment.

The change is therefore an acquisition-integrity correction based on observable stream structure, not outcome-driven detector tuning.

## Next validation gate

Run a short bounded live radar smoke and measure:

- decoded trades and lifecycle events;
- SOL-eligible vs filtered events;
- idempotent/replayed eligible events;
- evaluated tokens;
- radar hits;
- unique hit tokens;
- unique opportunity episodes;
- trigger-kind and direction distributions.

Passing that smoke validates `stream -> radar -> episode` plumbing only. It does not establish edge.
