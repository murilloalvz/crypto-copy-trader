# Rust Signal Plane Live Shadow V2 — Transport-Isolated Ingress

Status: **systems-only shadow; no economic verdict; V68 remains frozen**.

## Motivation

Live Shadow V1 Identity Plane did not start acquisition in its first run because the
single shared WebSocket session acknowledged Pump and then died before PumpSwap
subscription acknowledgement with a keepalive ping timeout.

That run did not evaluate the Identity Plane.

V2 isolates transport so network receive work cannot be blocked by Carbon decoding,
Python/Rust Radar comparison, or async identity resolution, and one market surface no
longer shares a WebSocket session with the other.

## Frozen live topology

```text
Alchemy Solana streaming
    |
    +-- WSS session A: Pump logsSubscribe --------+
    |                                             |
    +-- WSS session B: PumpSwap logsSubscribe ----+--> bounded ingress queue (8192)
                                                        |
                                                        v
                                              Carbon canonical decoder
                                                        |
                                              causal market adapters
                                                        |
                                      +-----------------+----------------+
                                      |                                  |
                              Python indexed Radar               Rust indexed Radar
                                      |                                  |
                                      +----------- parity/latency -------+

Unknown PumpSwap pool
    -> Async Identity Plane (primary SOLANA_RPC_URL only)
    -> getMultipleAccounts batch <= 64
    -> in-memory causal identity
    -> usable only by events received after the RPC response
```

## Transport contract

- Pump and PumpSwap use independent WebSocket connections.
- Each connection carries exactly one logsSubscribe.
- Commitment is `confirmed`.
- There is no automatic reconnect in V2.
- Each reader timestamps the notification immediately after `recv()`.
- Readers do no Carbon, Radar, persistence, RPC, audit, or outcome work.
- Readers use non-blocking admission into one bounded queue of 8192 notifications.
- A full queue produces an explicit ingress drop and FAIL; the reader never waits for
  downstream work while holding the socket receive loop.
- After the 120s source cutoff, readers stop and the consumer drains only notifications
  already admitted before the cutoff.
- Final ingress depth must be zero.
- Drain-after-source latency is reported.

## Identity Plane causal contract

Unchanged from V1:

- the trade that discovers an unknown pool remains MISSING;
- no retrospective backfill;
- one async lookup admission per unknown pool per run;
- identity observed time is the local RPC response time;
- only later events may consume it;
- primary configured SOLANA_RPC_URL only, no silent fallback;
- no SQLite/persistence/Jupiter/research work is added to the Signal Plane hot path.

## Frozen PASS gates

PASS requires all of the following:

1. Pump subscription ACK exactly once.
2. PumpSwap subscription ACK exactly once.
3. Two isolated transport sessions active.
4. Pump reader reaches the source-duration cutoff.
5. PumpSwap reader reaches the source-duration cutoff.
6. Zero Pump ingress drops.
7. Zero PumpSwap ingress drops.
8. Bounded ingress queue is fully drained after source close.
9. Zero transport reader errors.
10. Pump notifications observed.
11. PumpSwap notifications observed.
12. Canonical events decoded.
13. Adapted trades reach both Signal Plane kernels.
14. At least one trade decision point compared.
15. Python/Rust trigger/features parity exactly 100%, zero mismatches.
16. Zero Carbon decode failures.
17. At least one unknown PumpSwap pool enqueued to Identity Plane.
18. At least one async pool RPC request attempted.
19. At least one async pool identity resolved.
20. Zero Identity Plane queue overflow.
21. Zero async RPC batch failure.
22. Zero fatal/signal-process errors.

## Interpretation

A PASS establishes only that the transport-isolated Rust Signal Plane + async Identity
Plane works under this live systems window while preserving frozen Radar semantics.

A PASS does not establish profitable edge and does not authorize V68.

The next edge question after a PASS is whether coverage of PumpSwap trades improves
materially while source->signal latency and queue age stay bounded.

## Prohibited rescue

Do not:

- reconnect/retry this run until a preferred result appears;
- change queue capacity after seeing the run and call it the same protocol;
- backfill missing trades;
- change Radar/economic thresholds;
- use V68 or Participant Quality to rescue a systems failure;
- claim economic edge from systems latency or coverage alone.
