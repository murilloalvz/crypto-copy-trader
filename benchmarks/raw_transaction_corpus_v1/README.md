# Raw Transaction Corpus v1

Purpose: capture a short, bounded, read-only Pump/PumpSwap corpus with enough raw Solana transaction/meta/instruction data to compare the existing decoders against Carbon on the **same transactions**.

This is a research sidecar. It does not call V68, does not write SQLite, does not modify the V9 pipeline, and does not emit or execute trades.

## Why this exists

`canonical_market_trace_v0` starts after decode/normalization. It proved that the frozen Radar can run from bounded in-memory state with exact parity, but it cannot validate Carbon decoders because raw transaction/meta/instructions were not persisted.

This v1 corpus records:
- Pump and PumpSwap `logsSubscribe` receipt;
- exact `time.time_ns()` and `time.monotonic_ns()` receipt clocks;
- source venue/program, signature and slot;
- raw notification logs;
- `getTransaction` JSON transaction + meta;
- hydration attempts/errors.

The ingestion queue is bounded. Any queue overflow or hydration gap makes the corpus `valid_for_decoder_parity=false`; loss is never silently accepted.

## Capture

```powershell
python -m benchmarks.raw_transaction_corpus_v1.capture `
  --rpc-url "$env:SOLANA_RPC_URL" `
  --out artifacts\raw_transaction_corpus_v1\raw-tx-v1.jsonl `
  --duration-seconds 120 `
  --commitment confirmed `
  --hydrate-workers 8 `
  --queue-size 2048
```

Expected footer:
- `queue_overflow = 0`
- `hydrate_missing = 0`
- `hydrate_errors = 0`
- `hydrated == queued`
- `valid_for_decoder_parity = true`

Do not run an economic/V68 acquisition for this corpus. The next step is an offline same-transaction decoder parity adapter: current Pump/PumpSwap decode vs Carbon Pump/PumpSwap decode.
