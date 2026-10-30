# Free historical corpus v2

Purpose: validate decoder semantics without paying for production-grade streaming infrastructure.

This collector uses only standard Helius mainnet RPC methods available on the Free plan:

- `getSignaturesForAddress`
- `getTransaction`

It is deliberately paced and historical. It is **not** a replacement for a production live signal plane.

## Why this exists

The previous live `logsSubscribe -> getTransaction` fan-out was rejected for high-volume acquisition because public RPC hydration produced 429s, queue overflow, and tens-of-seconds delay.

That does **not** make `getTransaction` unsuitable for offline research. Decoder parity only needs complete transactions and metadata; it does not need live delivery.

Research path:

```text
Helius Free historical RPC
        |
        v
recent Pump/PumpSwap signatures
        |
        v
paced getTransaction
        |
        v
raw transaction + meta corpus
        |
        v
our decoder vs Carbon decoder
```

Yellowstone/gRPC remains deferred until live acquisition latency/coverage must be benchmarked.

## Cost guard

As documented by Helius on 2026-09-09:

- Free plan: 1,000,000 credits/month;
- standard RPC call: 1 credit;
- `getSignaturesForAddress`: 1 credit;
- `getTransaction`: 1 credit.

A target of 250 Pump + 250 PumpSwap transactions therefore needs roughly ~500 standard RPC credits plus a handful of signature-page calls, assuming no retries/missing rows.

## Setup

Create a Helius Free account and obtain an API key. Keep it out of shell history, files, screenshots, and commits.

PowerShell:

```powershell
$env:HELIUS_API_KEY = "<YOUR_KEY>"
```

Do not send the key to ChatGPT.

## Small smoke first

```powershell
New-Item -ItemType Directory -Force -Path artifacts\free_historical_corpus_v2 | Out-Null

python -m benchmarks.free_historical_corpus_v2.collect `
  --out artifacts\free_historical_corpus_v2\pump-pumpswap-smoke.jsonl `
  --per-venue 10 `
  --rps 5
```

Expected scale: roughly 20 `getTransaction` calls plus two signature-page calls.

## Decoder corpus

Only after the 10+10 smoke passes:

```powershell
python -m benchmarks.free_historical_corpus_v2.collect `
  --out artifacts\free_historical_corpus_v2\pump-pumpswap-500.jsonl `
  --per-venue 250 `
  --rps 5
```

Do not increase RPS above the Free-plan limit. Five RPS is intentionally conservative relative to the documented 10 RPS account limit.

## Validity

`valid_for_decoder_parity=true` requires:

- at least the requested Pump transaction count;
- at least the requested PumpSwap transaction count;
- zero RPC errors;
- zero local write errors.

Missing transactions are explicitly counted and the reserve candidate set is intended to absorb occasional missing historical rows.

## What this can prove

- our decoder and Carbon can be compared on the same complete transactions;
- canonical mint/side/wallet/amount/lifecycle semantics can be checked;
- no paid real-time provider is required for that correctness experiment.

## What this cannot prove

- production delivery latency;
- full live coverage under bursts;
- reconnect/replay behavior;
- gRPC/provider performance;
- economic edge by itself.

Those are later experiments.
