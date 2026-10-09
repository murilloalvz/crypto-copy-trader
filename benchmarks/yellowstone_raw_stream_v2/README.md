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

The client uses the standard Yellowstone `Geyser.Subscribe` API and supports:

- TLS (`https://`) or plaintext HTTP/2 (`http://`) endpoints;
- arbitrary gRPC auth metadata header via `YELLOWSTONE_AUTH_HEADER`;
- token auth via `YELLOWSTONE_AUTH_TOKEN` (legacy `YELLOWSTONE_X_TOKEN` also works);
- IP-allowlisted/no-token providers with `YELLOWSTONE_AUTH_HEADER=none`.

Never put provider secrets in commands, files, screenshots, artifacts, or commits.

## Provider order for the current spike

As of 2026-09-09:

1. **ERPC 1-day Geyser gRPC trial** — preferred first raw-mainnet corpus attempt. Full Yellowstone/Geyser transaction stream; IP allowlist; no token metadata. The trial is free, but ERPC requires a temporary EUR 5 card authorization for verification before the trial is started.
2. **Helius LaserStream 2-day trial** — valid second option if ERPC is inconvenient; application is manually reviewed.
3. **Alchemy PAYG** — low recurring cost candidate after free trials; approximately USD 75/TB with no monthly minimum, but requires billing/PAYG access.

Free tiers that only expose RPC/WebSocket, devnet gRPC, or pre-parsed JSON are not substitutes for this raw-mainnet decoder-parity corpus.

## Setup

```powershell
python -m pip install -r benchmarks\yellowstone_raw_stream_v2\requirements.txt
python -m benchmarks.yellowstone_raw_stream_v2.generate_proto
```

`generate_proto` downloads `geyser.proto` and `solana-storage.proto` from pinned upstream commit:

`rpcpool/yellowstone-grpc@1bf1377f8ffd6919d3579b597b33ad980a214a7f`

Generated stubs and downloaded proto files remain ignored local research artifacts.

## Environment — ERPC trial

After ERPC assigns the endpoint and your current public IP has been allowlisted:

```powershell
$env:YELLOWSTONE_ENDPOINT = "<EXACT ERPC ENDPOINT>"
$env:YELLOWSTONE_AUTH_HEADER = "none"
Remove-Item Env:YELLOWSTONE_AUTH_TOKEN -ErrorAction SilentlyContinue
Remove-Item Env:YELLOWSTONE_X_TOKEN -ErrorAction SilentlyContinue
```

Use the endpoint exactly as provided. ERPC supports both HTTPS and plaintext HTTP endpoints; the collector chooses TLS based on the URL scheme.

## Environment — token-auth provider

Example for a provider using `x-token`:

```powershell
$env:YELLOWSTONE_ENDPOINT = "<PROVIDER ENDPOINT>"
$env:YELLOWSTONE_AUTH_HEADER = "x-token"
$env:YELLOWSTONE_AUTH_TOKEN = "<PRIVATE API KEY>"
```

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
