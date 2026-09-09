# Yellowstone Raw Stream v2

Purpose: obtain a decoder-parity corpus from the transaction stream itself, without the rejected `logsSubscribe -> getTransaction` fan-out.

## Scope

Research-only sidecar. It does not call Radar, SQLite, V68, route/execution code, or any signing endpoint.

Pipeline:

```text
Yellowstone-compatible gRPC
        |
        v
Pump / PumpSwap transaction filters
        |
        v
SubscribeUpdateTransaction
(transaction + meta + slot + index)
        |
        v
exact protobuf SubscribeUpdate bytes
        |
        v
JSONL/Base64 corpus
```

The protobuf payload is preserved exactly so later Rust/Carbon parity work can decode the same provider update rather than a Python-normalized approximation.

## Provider neutrality

The client uses the standard Yellowstone `Geyser.Subscribe` API and `x-token` metadata. Provider tokens are read only from `YELLOWSTONE_X_TOKEN`; do not put them in commands, files, screenshots, or commits.

The first candidate is Alchemy mainnet gRPC because, as of 2026-09-09, it is Yellowstone-compatible and pay-as-you-go rather than requiring a ~$499/month gRPC tier. This is a benchmark candidate, not a production provider verdict.

## Setup

```powershell
python -m pip install -r benchmarks\yellowstone_raw_stream_v2\requirements.txt
python -m benchmarks.yellowstone_raw_stream_v2.generate_proto
```

`generate_proto` downloads `geyser.proto` and `solana-storage.proto` from pinned upstream commit:

`rpcpool/yellowstone-grpc@1bf1377f8ffd6919d3579b597b33ad980a214a7f`

Generated stubs and downloaded proto files remain ignored local research artifacts.

## Environment

For Alchemy:

```powershell
$env:YELLOWSTONE_ENDPOINT = "https://solana-mainnet.streaming.alchemy.com"
$env:YELLOWSTONE_X_TOKEN = "<API KEY>"
```

Keep the token private.

## Bounded parity smoke

The initial run is bounded by both wall-clock duration and transaction count. It stops at whichever happens first, so a busy market does not create an unnecessarily large or expensive file.

```powershell
New-Item -ItemType Directory -Force -Path artifacts\yellowstone_raw_stream_v2 | Out-Null

python -m benchmarks.yellowstone_raw_stream_v2.capture `
  --out artifacts\yellowstone_raw_stream_v2\yellowstone-pump-pumpswap-v2.jsonl `
  --duration-seconds 30 `
  --max-transactions 500 `
  --commitment confirmed
```

The capture subscribes only to successful, non-vote transactions that include the Pump or PumpSwap program account.

## Decoder-parity validity

A corpus is marked `valid_for_decoder_parity=true` only when:

- transaction updates were captured;
- at least one Pump update is present;
- at least one PumpSwap update is present;
- no transaction update lacked transaction info;
- there were no local write errors;
- there were no gRPC stream errors.

This validity flag means the file is suitable for same-input decoder comparison. It does **not** prove provider production latency, global coverage, reconnect correctness, or economic edge.

## Next experiment

If the corpus is valid:

```text
same protobuf transaction update
        |                 |
        v                 v
our decoder         Carbon decoder
        |                 |
        +--------+--------+
                 v
          canonical parity
```

Correctness comes before throughput benchmarking.
