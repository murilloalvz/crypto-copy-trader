# Opportunity Snapshot Core v1 — causal review 2026-09-03

## Status

**RESEARCH DESIGN / PAPER / READ ONLY.**

This review was performed while Wallet Forward v2 Run 2 was still active. Nothing here changes the active run, its cohort, enrollment, follow-up, quote delays, notional or runtime.

## Review objective

Audit the experimental Opportunity Snapshot Core before it is allowed anywhere near a future strategy. The review focuses on leakage, clock semantics, missingness, granularity, execution freshness and whether a feature can be interpreted more strongly than the source data allows.

## Finding 1 — dual-clock flow bug

### Problem

The first experimental implementation used `observed_at` both to decide whether an event was available and whether it belonged to a recent flow window.

That is causal in the weak sense that no future observation leaks backward, but it is wrong as a description of market microstructure. Example:

- trade happened on-chain at 10:00:00;
- collector only discovered/backfilled it at 10:08:15;
- snapshot is built at 10:08:20;
- old implementation could count that event as part of the last 10 seconds of flow.

The bot truly knows about the old trade at 10:08:15, but the trade is not fresh 10-second market flow.

### Correction

Flow inclusion now requires BOTH:

```text
observed_at <= decision_as_of
AND
decision_as_of - window < chain_time <= decision_as_of
```

Availability uses observation time. Market-window membership uses event/chain time.

Price ordering inside the window is also based on event time only after the availability gate is satisfied.

Method version was bumped to:

`opportunity_snapshot_core_v1_1_dual_clock`

## Finding 2 — partial coverage could look more complete than it was

### Problem

A window with two trades but only one known wallet/price/notional could still expose statistics calculated from the known subset. Those statistics may be mathematically correct for the subset but misleading as features for the whole window.

### Correction

The Core now exposes explicit coverage:

- `wallet_identity_coverage_pct`;
- `notional_coverage_pct`;
- `price_coverage_pct`.

Conservative semantics:

- buy/sell notional and imbalance are unavailable unless notional is complete for the window;
- return is unavailable unless price is complete for the window;
- repeated-wallet share is unavailable unless wallet identity is complete for the window;
- partial coverage remains visible through quality flags instead of being silently imputed.

Unique-wallet counts with partial identity remain counts of **known** wallets only and must never be interpreted as complete participation counts unless coverage is 100%.

## Finding 3 — historical quote freshness was implicit

### Problem

A causal quote with `observed_at <= as_of` is known, but the latest known quote can still be stale. Causality alone is not freshness.

### Correction

Execution surface now exposes:

- latest buy/sell observation age relative to decision time;
- latest buy/sell market-data age relative to decision time;
- min/max provider-reported swap notional where available;
- `mixed_quote_notionals` when quote sizes are materially heterogeneous;
- `partial_quote_notional_metadata` when notional provenance is incomplete.

The Core deliberately does **not** invent a universal freshness threshold yet. Freshness limits must be predeclared per experiment and tested against execution outcomes rather than tuned after seeing PnL.

## Finding 4 — nested windows are correlated

Windows 10s/30s/60s/300s are useful state summaries but they are nested. They are not independent observations and should not be used naively as a claim of acceleration.

For a future acceleration feature, prefer matching non-overlapping intervals, for example:

```text
current 30s:       (T-30, T]
previous 30s:      (T-60, T-30]
acceleration = current / previous
```

Keep the raw nested windows, but calculate acceleration from explicit non-overlapping baselines.

## Finding 5 — decision time must include feature acquisition latency

A future decision cannot define T0 as wallet detection time and then attach market/risk/provider responses that arrived afterward.

Required causal timeline:

```text
source trade chain_time
    -> wallet observed_at
    -> feature requests start
    -> each provider response observed_at
    -> decision_as_of
    -> execution quote/build/submit/land
```

`decision_as_of` must be no earlier than every feature used by the decision. The time spent gathering intelligence becomes part of real copy latency and can destroy otherwise attractive edge.

This is especially important when using REST APIs after a wallet event. A sophisticated model is not allowed free instantaneous information.

## Finding 6 — raw trades and aggregate provider frames must not be conflated

Raw trade feeds can preserve:

- event/chain time;
- observation time;
- side;
- wallet identity;
- notional;
- price.

An aggregate API response such as a provider's `10s/30s/60s` frame is a different evidence object. It should preserve:

- provider;
- requested frame;
- request/response observation time;
- provider timestamp if supplied;
- aggregate counts/volume/wallets;
- missing fields.

Do not manufacture fake raw events from aggregate frames. If aggregate features are added, they should be a separate provenance-aware channel and can later be compared against raw-flow features.

## Finding 7 — quote-key/event linkage needs exact identity

While preparing the replication audit, a separate risk was found in the existing quantity-aware replay CLI: it built a list of quote keys, loaded quote rows sorted by observation time, then zipped the caller key order to the returned row order.

Those two orders are not contractually the same. A quote can therefore be attached to the wrong event if key order and timestamp order differ.

The new replication audit loads each exact quote key independently and never relies on row-order alignment. A regression test explicitly uses reversed timestamp/key order.

Before Run 1 x Run 2 economic conclusions are finalized, replay results should be regenerated through the exact-key path. Existing Run 1 quantity-aware numbers remain useful provisional evidence but will be re-audited rather than trusted blindly.

## What remains intentionally unimplemented

- no Opportunity Score;
- no BUY/SELL threshold;
- no model training;
- no automatic Pump.fun/X integration;
- no graph-derived independence claim;
- no automatic freshness gate;
- no raw/aggregate provider fusion;
- no shadow/live execution.

## Review decision

The Core is methodologically stronger after this review, but it remains an isolated research prototype until the Wallet Forward v2 replication is audited.

If Run 2 supports moving to the next data-collection gate, the next implementation should prioritize provenance-aware event-driven collection and preserve the full latency chain from trigger to decision.