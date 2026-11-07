# Carbon Stream Bridge v0 — frozen result (2026-09-10)

Status: `REJECT_OR_INVESTIGATE_CARBON_STREAM_BRIDGE_V0`.

This result is frozen. The preregistered thresholds MUST NOT be relaxed after observing it.

## Frozen protocol

- persistent Python -> Rust NDJSON stdio bridge;
- pinned Carbon Pump/PumpSwap decoder 2.0.0;
- Carbon release commit `e901103c93833c9c79407cb4321561e30796ad51`;
- 5,000 deterministic valid PumpSwap BuyEvent payloads;
- producer target 5,000 events/s;
- exact output order/accounting required;
- zero decode/input errors required;
- achieved rate >= 90% target;
- round-trip p95 <= 25 ms;
- round-trip p99 <= 75 ms.

## Observed result

```text
achieved_ingress_eps = 5000.8718
input_events = 5000
decoded_events = 5000
decode_failures = 0
input_errors = 0
order_violations = 0
footer_accounting_valid = true
max_inflight_events = 227

round_trip_ms.min = 0.049855
round_trip_ms.p50 = 5.386114
round_trip_ms.p95 = 38.67153845
round_trip_ms.p99 = 41.97884709
round_trip_ms.max = 45.426567
```

## Gate verdict

- semantic/accounting/order: PASS;
- throughput at 5k/s: PASS;
- p99 <= 75 ms: PASS;
- p95 <= 25 ms: **FAIL**.

Therefore the v0 transport is not promoted.

## Interpretation boundary

This is not a Carbon semantic failure and not evidence that the decoder cannot sustain 5k events/s. The failure is in the local bridge latency envelope under this transport/harness. The current implementation flushes stdin and stdout per event, which is a plausible mechanism for syscall/scheduling pressure, but that mechanism is not considered proven until a diagnostic experiment isolates the rate/queue behavior.

No provider/network latency, pool lookup latency, WSS recall, economic edge, or real-money behavior is evaluated here.

## Next experiment

Run the unchanged v0 sidecar at fixed diagnostic source rates of 1,000, 2,500, and 5,000 events/s. This matrix is diagnostic only and does not retroactively redefine the v0 gate. It is intended to show whether tail latency/inflight depth rises with offered load before considering a separately preregistered bounded-microbatch v1 transport.
