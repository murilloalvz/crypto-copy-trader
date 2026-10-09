# Carbon → Indexed Kernel ingress v1 decision — 2026-09-10

## Decision

**PASS / KEEP the current local composition:**

`bounded NDJSON microbatch → Carbon 2.0.0 → Pump matched-unit adapter → MarketTrade adapter → IndexedMarketSignalKernel`

This closes the synthetic local composition gate at the preregistered 5,000 events/s load. It does not validate provider/network latency, PumpSwap pool-context availability, chain-complete semantic recall, economic edge, or real-money execution.

## Frozen protocol

Before observing the result:

- 5,000 deterministic valid Pump TradeEvent payloads;
- target source rate: 5,000 events/s;
- bridge v1 transport: max batch size 16, max producer batch-wait target 1.0 ms;
- Pump event-native quote context only, avoiding PumpSwap pool-context contamination;
- exact order and exact accounting;
- every event must decode, adapt through matched-unit and MarketTrade, and reach the indexed kernel;
- local `observed_at` assigned outside Carbon and preserved;
- no USD price/notional fabrication;
- zero decode/input/semantic/order errors;
- achieved source rate >= 90% of target;
- source-availability → completed kernel ingest p95 <= 25 ms;
- p99 <= 75 ms.

Thresholds were not changed after observing the result.

## Result

GitHub Actions run `34525177520`:

- classification: `PASS_CARBON_KERNEL_INGRESS_V1`;
- Carbon decoder: 2.0.0;
- Carbon release commit: `e901103c93833c9c79407cb4321561e30796ad51`;
- input / decoded / matched-unit / MarketTrade / kernel ingested: **5,000 / 5,000 / 5,000 / 5,000 / 5,000**;
- decode failures: 0;
- input errors: 0;
- semantic errors: 0;
- order violations: 0;
- footer accounting: valid;
- achieved ingress: **5,000.838 events/s**;
- batches sent: 728;
- batch size p50 / p95 / max: 6 / 8 / 12;
- max in-flight events: 13;
- producer batch wait p50 / p95 / p99 / max: 1.073 / 1.118 / 1.122 / 1.191 ms;
- source → kernel latency min / p50 / p95 / p99 / max: **0.351 / 0.946 / 1.413 / 1.500 / 1.821 ms**;
- kernel retained trade rows: 300;
- tracked assets: 1;
- triggers emitted: 88;
- process return code: 0.

## Interpretation

The current local composition clears the preregistered latency envelope by more than an order of magnitude at 5k events/s while preserving exact semantics and accounting.

Therefore:

- do not rewrite the indexed kernel in Rust for performance now;
- do not replace Carbon or the current local bridge for performance now;
- do not add workers/shards merely to optimize this synthetic path;
- keep persistence, external APIs, research/outcomes, and slow enrichment out of this path;
- focus remaining infrastructure work on genuinely live boundaries: provider delivery and causal PumpSwap pool-context acquisition.

## Next stage

The Market-First pipeline should now move toward a prospective covered live research run. The run must freeze T0 evidence first and collect outcomes separately. It must not create an economic score, recommendation, or threshold tuned from the same outcomes.

The remaining live dependency that can materially affect PumpSwap matched-unit coverage is real pool-identity lookup latency. That measurement should be performed only on a representative connection/environment; school Wi-Fi is not valid performance evidence.
