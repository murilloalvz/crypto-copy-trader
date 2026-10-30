# Carbon Stream Bridge v1

Purpose: test a structurally different local transport boundary after the frozen v0 per-event NDJSON stdio bridge failed its preregistered 5k events/s p95 gate.

The Carbon decoder is unchanged and remains pinned at 2.0.0. Only the local Python↔Rust transport changes.

## Frozen v1 protocol

- target rate: 5,000 events/s;
- events: 5,000 deterministic valid PumpSwap BuyEvent payloads;
- transport: NDJSON microbatches over persistent stdio;
- maximum batch size: 16 events;
- producer maximum batch-wait target: 1.0 ms from first event availability;
- latency clock starts before the bounded batcher so batching delay is included;
- exact event accounting and exact ordering;
- zero decode failures and zero input errors;
- achieved producer rate >= 90% of target;
- p95 <= 25 ms;
- p99 <= 75 ms.

The thresholds intentionally match the frozen v0 gate. They are not relaxed after observing v0.

## Why v1 exists

The v0 diagnostic matrix showed:

- 1,000 events/s: p95 ~0.07 ms, max inflight 1;
- 2,500 events/s: p95 ~0.07 ms, max inflight 1;
- 5,000 events/s: p95 ~40 ms, max inflight >200;
- 5,000/5,000 decoded, zero order violations and zero decode/input failures.

That shape points to load-dependent local IPC/syscall/queue behavior rather than Carbon semantic decode failure. v1 amortizes stdin/stdout flushes across small bounded batches instead of changing the decoder or the scientific gate.

## Interpretation

`PASS_CARBON_STREAM_BRIDGE_V1` supports this local composition seam only. It does not validate Helius network latency, chain completeness, pool lookup latency, economic edge, or real-money execution.

A failure closes v1 under this protocol. Do not tune batch size, wait, or latency thresholds against the observed result and call it the same hypothesis.
