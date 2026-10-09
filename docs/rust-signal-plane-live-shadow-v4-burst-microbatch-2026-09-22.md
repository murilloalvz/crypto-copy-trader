# Rust Signal Plane Live Shadow V4 — No-Wait Burst Microbatch

Status: **systems-only shadow; no economic verdict; V68 remains frozen**.

## Motivation

V3 established a clean live PASS with:

- independent Pump and PumpSwap WebSocket sessions;
- server-heartbeat transport with no client-originated keepalive ping timeout;
- zero ingress drops and zero reader errors;
- Rust/Python Radar parity = 100%;
- async PumpSwap Identity Plane resolving 93/93 requested pools;
- PumpSwap adapted coverage = 75.46%;
- Rust source->signal p95 = 7.98 ms;
- Rust canonical->signal p95 = 0.55 ms.

The stage breakdown showed that the dominant pre-signal component was ingress queue wait
(p95 6.66 ms), while Carbon roundtrip and Rust kernel time were already sub-millisecond.

V4 tests whether **draining only the burst already waiting in memory** into one Carbon
microbatch reduces queueing without introducing any intentional coalescing delay.

## Frozen transport topology

```text
Alchemy Solana streaming
    |
    +-- Pump WSS -------------------------------+
    |                                          |
    +-- PumpSwap WSS ---------------------------+--> bounded ingress queue (8192)
                                                   |
                                                   v
                                      take first notification immediately
                                                   |
                              drain only already-ready queue items
                                      max 32 notifications
                                      NO sleep / NO coalesce wait
                                                   |
                                                   v
                                      one Carbon decoder batch
                                                   |
                                      canonical market observations
                                                   |
                                      +------------+-----------+
                                      |                        |
                              Python indexed Radar      Rust indexed Radar
                                      |                        |
                                      +------ exact parity ----+
```

Identity Plane remains asynchronous and outside the Signal Plane hot path.

## Frozen microbatch contract

- max notifications per ingress microbatch = **32**;
- first notification is processed immediately after `queue.get()`;
- only notifications already available via `get_nowait()` are added;
- no sleep, timer or artificial coalescing window is permitted;
- queue ordering is preserved;
- Carbon receives the flattened target-event list in that same queue order;
- per-event source receive timestamps remain unchanged;
- no Radar, adapter or economic threshold changes are allowed.

## Ingress accounting

PASS requires exact accounting:

```text
pump_ingress_enqueued
+ pumpswap_ingress_enqueued
= consumer_notifications
```

The queue must also be empty at report time.

V4 reports:

- queue capacity/high-water/final depth;
- total enqueued and consumed;
- ingress microbatch size distribution;
- Carbon batch event-size distribution;
- queue wait by surface;
- Carbon roundtrip;
- true drain-after-source time.

### Correct drain definition

`drain_after_source_ms` is measured as:

```text
time when the last admitted ingress item is fully consumed
-
the exact 120s source cutoff
```

Reader close handshake, Identity Plane shutdown, Carbon process shutdown and Rust process
shutdown are excluded from this metric.

## Identity latency diagnostics

V4 additionally measures:

- async RPC batch latency;
- first unknown PumpSwap trade receive time -> causal identity ready time.

This is diagnostic only and does not alter causal policy.

The triggering unknown-pool trade still remains MISSING in V4.
No retrospective backfill is allowed.

A later experiment may test a causal pending-release design only if these latency measurements
show that doing so is operationally useful.

## Frozen PASS gates

V4 requires every V3 gate plus:

1. exact ingress accounting;
2. ingress queue empty after source close;
3. at least one ingress microbatch larger than one notification, proving the new path was exercised.

No latency-improvement threshold is part of PASS because V3 and V4 observe different live
market windows.

## Interpretation

A PASS means the no-wait burst microbatch preserves systems correctness and exact Radar semantics
while exercising the optimized ingress path.

Latency changes are descriptive, not a pass/fail rescue.

V4 does not establish economic edge and does not authorize V68.

## Stop rule

After one valid V4 run:

- do not tune batch size from the result;
- do not try 8/16/64 notification caps;
- do not rerun until a preferred latency appears;
- do not change the 30s application idle watchdog;
- do not change Radar/economic thresholds.

The next engineering decision must be based on the frozen V4 evidence:

- if queue wait materially collapses, freeze the transport/consumer architecture;
- if identity-ready latency is small, evaluate a separate causal pending-release hypothesis;
- otherwise stop systems optimization and return to fresh economic-edge testing.
