# Rust Signal Plane Live Shadow V3 — Server-Heartbeat Transport

Status: **systems-only shadow; no economic verdict; V68 remains frozen**.

## Why V3 exists

V2 successfully proved that:

- Pump and PumpSwap can run on independent WebSocket sessions;
- ingress isolation and the bounded queue work;
- Rust/Python Radar parity remained 100%;
- the async PumpSwap Identity Plane resolved unknown pools causally and allowed later
  trades to become ADAPTED;
- no ingress drops occurred.

However, both independent sessions closed with the same client-side keepalive timeout:

```text
ConnectionClosedError: sent 1011 ... keepalive ping timeout
```

Alchemy documents that its WebSocket servers send pings to clients and that clients do
not need to originate their own keepalive pings. V3 therefore disables the
`websockets` library's client-originated keepalive ping loop.

This is a transport fix only. Radar, economic thresholds, Participant Quality, V68,
Identity Plane causal policy and provider selection are unchanged.

## Frozen transport topology

```text
Alchemy Solana streaming
    |
    +-- WSS Pump -------------------------------+
    |                                          |
    +-- WSS PumpSwap ---------------------------+--> bounded ingress queue (8192)
                                                   |
                                                   v
                                           Carbon decoder
                                                   |
                                      causal market adapters
                                                   |
                                      +------------+-----------+
                                      |                        |
                              Python indexed Radar      Rust indexed Radar
                                      |                        |
                                      +------ parity ----------+

Unknown PumpSwap pool
    -> async Identity Plane
    -> primary SOLANA_RPC_URL getMultipleAccounts
    -> in-memory causal identity
    -> usable only for later events
```

## Heartbeat policy

Frozen V3 connection settings:

- `ping_interval=None`
- `ping_timeout=None`
- `close_timeout=5`
- `max_size=16 MiB`
- `max_queue=1024`

No client-originated WebSocket keepalive ping loop is used.

Each market-surface reader instead has an application-stream idle watchdog:

- idle timeout = **30 seconds**;
- the watchdog is based on time since the last application message received by that
  reader;
- no automatic reconnect is permitted in V3;
- a 30s idle timeout is a transport FAIL.

Pump and PumpSwap remain separate sessions.

## Causal / edge safety

Identity Plane policy is unchanged:

- unknown-pool triggering trade remains MISSING;
- no retrospective backfill;
- async identity observed time is local RPC response time;
- only later events may consume it;
- one lookup admission per unknown pool per run;
- primary configured RPC only, no silent fallback.

No economic logic is changed.

## New latency attribution

V3 reports:

- ingress queue wait p50/p95/p99/max;
- Pump ingress queue wait;
- PumpSwap ingress queue wait;
- target extraction service time;
- Carbon roundtrip time;
- existing canonical->signal and source->signal latency.

This is diagnostic only. No latency number may rescue failed parity, transport or
causal gates.

## Frozen PASS gates

All V2 gates remain required:

1. both subscriptions ACK exactly once;
2. two isolated sessions active;
3. both readers reach the full 120s source cutoff;
4. zero ingress drops;
5. ingress fully drains after source close;
6. zero reader errors;
7. Pump and PumpSwap traffic observed;
8. canonical events decoded;
9. adapted trades reach both kernels;
10. at least one trade decision point compared;
11. Python/Rust parity exactly 100%, zero mismatches;
12. zero Carbon decode failures;
13. Identity Plane enqueues at least one unknown pool;
14. Identity Plane attempts at least one RPC pool request;
15. Identity Plane resolves at least one causal identity;
16. zero Identity Plane queue overflow;
17. zero async RPC batch failure;
18. zero fatal/signal-process errors.

V3 does not add a throughput or latency threshold. The new stage timings are for
diagnosing where source->signal delay is spent.

## Interpretation

A PASS means the server-heartbeat transport survived the full window while preserving
the frozen Signal Plane semantics and causal Identity Plane behavior.

It does not establish economic edge and does not authorize V68.

## Prohibited rescue

Do not:

- re-enable client keepalive pings after seeing the result and call it the same protocol;
- change the 30s idle watchdog after the run;
- change queue size after the run;
- reconnect/retry until a preferred result appears;
- backfill MISSING trades;
- modify Radar or economic thresholds;
- claim edge from latency alone.
