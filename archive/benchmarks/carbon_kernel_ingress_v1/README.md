# Carbon → Indexed Kernel ingress v1

Purpose: measure the already-selected local composition under load after the bounded Carbon bridge v1 passed its own 5k events/s gate.

This benchmark does **not** change production components. It composes the existing pieces:

`Python source → bounded NDJSON microbatch → Carbon 2.0.0 → Pump matched-unit adapter → MarketTrade adapter → IndexedMarketSignalKernel`

## Frozen protocol

Before observing the result:

- 5,000 deterministic valid Pump TradeEvent payloads;
- target source rate: 5,000 events/s;
- same bridge v1 transport: max batch size 16, max batch-wait target 1.0 ms;
- Pump only, using event-native quote identity/reserve evidence so PumpSwap pool-context availability cannot contaminate the local integration test;
- exact event order and exact accounting;
- every event must decode, adapt through matched-unit and MarketTrade, and reach the indexed kernel;
- local `observed_at` is assigned outside Carbon and must be preserved;
- no USD notional or USD price may be manufactured;
- zero semantic errors, decode failures, input errors, or order violations;
- achieved source rate >= 90% of 5,000 events/s;
- source-availability → completed kernel ingest p95 <= 25 ms;
- source-availability → completed kernel ingest p99 <= 75 ms.

These latency gates intentionally preserve the already-frozen local bridge envelope. Do not relax them after seeing the result.

## Interpretation

A PASS validates the local decode→adapt→kernel composition at this synthetic load. It does not validate Helius network latency, live semantic recall, PumpSwap pool lookup/context coverage, economic edge, or real-money execution.

A failure must be diagnosed by stage. Do not tune thresholds or synthetic semantics against the observed outcome and call it the same hypothesis.
