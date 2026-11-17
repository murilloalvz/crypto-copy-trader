# Rust Signal Plane Live Shadow V4.1 — Startup Barrier

Status: **systems-only startup hardening; no economic verdict; V68 remains frozen**.

## Why V4.1 exists

The first 30-minute V4 soak did not enter acquisition. Pump opened and delivered three
notifications, while the PumpSwap WebSocket failed during the opening handshake:

```text
pumpswap_logs:TimeoutError:timed out during opening handshake
```

The run therefore did not evaluate long-duration Signal Plane stability.

The installed `websockets` client defaults to a finite opening-handshake timeout. V4.1
makes startup explicit and fail-closed without adding reconnect or retry behavior.

## Frozen startup contract

1. Start both independent WebSocket connection attempts.
2. Each connection uses `open_timeout=30s`.
3. Do not subscribe until **both** WebSocket opening handshakes have succeeded.
4. Once both sockets are open, release one shared subscribe barrier.
5. Require Pump and PumpSwap `logsSubscribe` ACKs independently within 20s.
6. Do not start acquisition until both subscription ACKs exist.
7. Require pre-acquisition ingress queue depth = 0.
8. Only then:
   - define `discovery_start_wall_ns`;
   - validate bootstrap evidence against that start;
   - define `deadline = acquisition_start + requested_duration`;
   - release both readers into the live receive loop.

No automatic retry or reconnect is permitted in V4.1.

## Unchanged contracts

V4.1 does **not** modify:

- Rust Signal Plane semantics;
- Python/Rust parity contract;
- no-wait microbatch cap = 32;
- bounded ingress queue = 8192;
- server-heartbeat policy;
- 30s application idle watchdog;
- PumpSwap Identity Plane;
- causal no-backfill rule;
- detector thresholds;
- V68 bins, economic gates, provider pacing, outcomes or route semantics.

## Startup observability

The report adds:

- per-surface socket-open counters;
- open-barrier PASS;
- subscription-barrier PASS;
- acquisition-start counters;
- open barrier latency;
- subscription barrier latency;
- pre-acquisition queue depth;
- explicit configured opening and ACK timeouts.

A startup failure before acquisition is a **systems/provider startup failure**. It does not
constitute Signal Plane parity evidence, Identity Plane evidence, or economic evidence.

## Soak interpretation

A valid long soak requires:

- both startup barriers PASS;
- acquisition actually started on both readers;
- full requested duration elapsed on both readers;
- zero transport reader errors;
- zero ingress drops;
- exact ingress accounting;
- drained queue;
- 100% Python/Rust parity;
- Identity Plane resolution gates PASS.

V68 remains blocked until the accepted Signal Plane is integrated into the actual V68
acquisition path through a separate systems-only bridge.
