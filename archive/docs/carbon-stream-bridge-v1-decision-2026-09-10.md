# Carbon stream bridge v1 decision — 2026-09-10

## Decision

**ADOPT / KEEP `ndjson_stdio_microbatch_v1` as the current local Python↔Rust Carbon composition seam.**

This decision is limited to local IPC + Carbon decode. It is not a provider/network, chain-completeness, PumpSwap pool-context, economic-edge, or real-money result.

## Frozen v0 result

The original persistent per-event NDJSON stdio bridge was tested at a preregistered 5,000 events/s gate with exact accounting/order, p95 <= 25 ms and p99 <= 75 ms.

At 5,000 events/s it decoded 5,000/5,000 events with zero decode/input errors and zero order violations, but accumulated roughly 230 in-flight events and produced p95 latency around 40.7 ms. Lower 1,000 and 2,500 events/s points were approximately 0.07 ms p95.

**v0 per-event stdio is therefore REJECTED at the frozen 5k/s gate.** Thresholds were not relaxed after observing the failure.

## v1 hypothesis

Keep Carbon 2.0.0 unchanged and modify only the local transport boundary:

- persistent NDJSON stdio;
- bounded microbatches;
- max configured batch size = 16;
- max producer batch-wait target = 1.0 ms;
- source availability clock starts before batching;
- 5,000 events at 5,000 events/s;
- >= 90% achieved source rate;
- zero loss, reorder, decode failure, or input error;
- p95 <= 25 ms;
- p99 <= 75 ms.

## Invalid first v1 attempt

The first v1 execution did not exercise the intended batching hypothesis: the Python source pacer busy-spun at a 200 microsecond interval and starved the batch-writer thread under the GIL. Evidence included nearly one batch per event and producer batch waits around an order of magnitude above the frozen 1 ms target.

That execution is classified as a **benchmark harness scheduling defect**, not a transport verdict. The only repair was to make the synthetic source pacer yield the GIL. Batch size, batch-wait target, target rate, p95 gate, p99 gate, Carbon version, semantics, accounting requirements, and order requirements were unchanged.

## Corrected frozen v1 result

GitHub Actions run `34524576474`:

- classification: `PASS_CARBON_STREAM_BRIDGE_V1`;
- Carbon decoder: 2.0.0;
- Carbon release commit: `e901103c93833c9c79407cb4321561e30796ad51`;
- input events: 5,000;
- decoded events: 5,000;
- decode failures: 0;
- input errors: 0;
- order violations: 0;
- footer accounting: valid;
- achieved ingress: 5,000.817 events/s;
- batches sent: 832;
- batch size p50/p95/max: 6 / 6 / 7;
- max in-flight events: 8;
- producer batch wait p50/p95/p99/max: 1.018 / 1.121 / 1.132 / 1.380 ms;
- round-trip latency min/p50/p95/p99/max: 0.126 / 0.737 / 1.241 / 1.279 / 1.583 ms.

The corrected run clears the frozen p95 and p99 gates by a wide margin while preserving exact accounting and ordering.

## Architectural implication

The current Python↔Rust boundary is no longer a demonstrated bottleneck at the tested 5k/s local load. Therefore:

- do not rewrite the already-fast Python `IndexedMarketSignalKernel` in Rust merely to remove this boundary;
- do not adopt a paid streaming provider merely to avoid this local IPC seam;
- keep the bridge bounded and observable;
- keep research, persistence, external APIs, and slow enrichment out of the hot path.

Carbon itself exposes Rust-native datasource infrastructure, and the Solana/Agave Rust ecosystem provides a `logsSubscribe` Pubsub client. A same-runtime Rust acquisition+decode path remains a future simplification candidate, but **the v1 PASS removes it as an urgent requirement**. It should only be revisited if integrated/live evidence shows the current seam is materially limiting the product.

## Next gate

Measure the integrated local path under load:

`bounded microbatch bridge → Carbon decode → protocol/matched-unit adaptation → MarketTradeObservation → IndexedMarketSignalKernel`

Use Pump event-native quote context so the benchmark isolates the local composition seam rather than PumpSwap pool-context availability. Preserve the same 5,000 events/s load and the same 25/75 ms local latency envelope before observing the result.
