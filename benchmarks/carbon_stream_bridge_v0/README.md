# Carbon Stream Bridge v0

Purpose: test the smallest live integration seam between the already-approved Python Helius Standard WSS collector and the already-approved Carbon 2.0.0 Pump/PumpSwap event decoders without rewriting either side.

The candidate boundary is:

```text
Helius Standard WSS logsSubscribe
  -> contextual Program data extraction
  -> persistent local NDJSON pipe
  -> pinned Carbon event decoder
  -> canonical event
  -> existing Python protocol adapters / IndexedMarketSignalKernel
```

This benchmark does not call Helius and does not change production. It isolates only persistent local IPC + Carbon event decode.

## Why not a stock Carbon RPC datasource?

The current Helius Free path validated by this project is standard `logsSubscribe`. Carbon 2.0.0 has an `rpc-block-subscribe-datasource`, but Helius documents `blockSubscribe` as unsupported. `logsSubscribe` already exposes the Pump/PumpSwap `Program data` payloads used by the project's live-shadow reducer and Carbon event decoder, so transaction hydration is not required for these event types.

The file-based parity runner remains frozen. `stream_decode_events` includes that runner as the decoder oracle and only adds a persistent NDJSON transport shell; decoder semantics are not reimplemented.

## Frozen benchmark protocol

- Carbon decoder: 2.0.0 / release commit `e901103c93833c9c79407cb4321561e30796ad51`;
- 5,000 deterministic valid synthetic PumpSwap BuyEvent payloads;
- target producer rate: 5,000 events/s;
- exact input/output accounting;
- exact output ordering;
- zero decode failures/input errors;
- achieved producer rate >= 90% of target;
- local round-trip p95 <= 25 ms;
- local round-trip p99 <= 75 ms.

These latency limits are intentionally small relative to the Signal Plane's seconds-scale end-to-end budget but loose enough to avoid treating ordinary CI scheduling jitter as architecture failure.

`PASS_CARBON_STREAM_BRIDGE_V0` supports the persistent local bridge candidate. It does not validate provider latency, WSS completeness, pool lookup latency, economic edge, or live money.

## CI command

```powershell
python -m unittest tests.test_carbon_stream_bridge_v0 -v

cargo build --release --locked `
  --manifest-path benchmarks\carbon_decoder_parity_v1\rust_runner\Cargo.toml `
  --bin stream_decode_events

python -m benchmarks.carbon_stream_bridge_v0.benchmark `
  --binary benchmarks\carbon_decoder_parity_v1\rust_runner\target\release\stream_decode_events.exe `
  --events 5000 `
  --target-rate 5000
```

Linux CI omits the `.exe` suffix.

## Scientific boundary

A PASS means only that Python-to-Rust local streaming is a viable low-overhead composition seam. The next live-shaped experiment must still preserve local `observed_at`, explicit missingness, no retroactive Pool identity backfill, bounded/observable queues, and the independent research-plane handoff contract.
