# Rust Signal Plane Live Shadow V5 — Ordered Signal Batch + Post-Run Parity Audit

Status: **systems-only capacity correction; no economic verdict; V68 remains frozen**.

## Evidence that opened V5

The 30-minute V4.1 soak entered acquisition successfully but failed sustained capacity:

- Python/Rust trigger parity: 30,200 / 30,200 = 100%
- ingress queue high-water: 8,192 / 8,192
- Pump ingress drops: 1,455
- PumpSwap ingress drops: 38,356
- ingress queue wait p95: ~29.09 s
- Rust source->signal p95: ~29.52 s
- Carbon roundtrip p95: ~2.04 ms
- target extraction p95: ~0.164 ms
- Rust internal service p95: ~5.00 ms
- Identity Plane requested/resolved: 456 / 456

Interpretation: the bounded ingress queue and provider readers were not the compute bottleneck.
The live shadow itself serialized Python Radar verification plus per-event Rust stdin/stdout IPC
inside the production-equivalent consumer path. That audit work became load-bearing and saturated
the queue.

Do not rescue V4.1 by increasing the queue or tuning batch size.

## V5 hypothesis

If the live hot path:

1. preserves canonical event order;
2. sends all adapted observations from one canonical batch to Rust in one ordered IPC request;
3. lets Rust mutate its state sequentially in that exact order;
4. removes Python reference computation from the live hot path;
5. replays the exact same TraceRecords through Python only after acquisition ends;

then live throughput should improve without changing Radar semantics.

## Frozen live hot path

```text
Pump WSS -----+
              |
PumpSwap WSS -+-> bounded ingress 8192
                    |
                    v
              no-wait ingress microbatch <=32 notifications
                    |
                    v
                 Carbon
                    |
                    v
          Python causal adapters / identity availability
                    |
                    v
         ordered signal batch (one IPC)
                    |
                    v
          Rust indexed Signal Plane
                    |
                    v
              live signal result
```

Python Radar is not in this live path.

## Rust batch semantics

The Rust stream transport accepts:

```text
signal_batch {
  batch_id,
  records: [ordered signal records]
}
```

Rust processes each record sequentially through the same frozen `StreamKernel` state and returns:

```text
signal_batch_result {
  batch_id,
  count,
  batch_service_ns,
  results: [per-record signal_result]
}
```

No per-record parallel mutation is allowed.

The batch response order must equal input sequence order.

The externally visible signal-ready clock in V5 is the **batch response wall time**, not an
internal per-record timestamp. This prevents understating IPC/batch visibility latency.

## Post-run parity audit

For every live Rust record, V5 retains one exact `TraceRecord` plus its Rust trigger snapshot.

After acquisition and transport teardown:

- create a fresh Python `IndexedWindowRadarState`;
- replay every retained TraceRecord in original sequence order;
- compare each trade trigger to the retained Rust trigger;
- require exact 100% parity and zero mismatch;
- require audit record count == live Rust signal record count;
- require audit trade decision count == live Rust trade decision count.

Python audit time is reported but is not part of live source->signal latency.

## Contracts unchanged

V5 does not change:

- detector or Radar thresholds;
- causal clocks;
- Pump/PumpSwap adapters;
- Identity Plane no-backfill semantics;
- V4.1 startup barrier;
- server-heartbeat policy;
- ingress queue capacity 8192;
- ingress microbatch cap 32;
- economic features, V68 bins/gates, Jupiter semantics or outcomes.

## PASS gates

All V4.1 transport/identity gates remain required, plus:

1. at least one Rust signal batch is exercised;
2. Rust batch record accounting exactly equals live signal record accounting;
3. post-run Python audit consumes every Rust live record;
4. post-run Python audit consumes every Rust live trade decision;
5. trigger parity = 100%, zero mismatch.

No throughput/latency threshold is added to a 120s smoke.

For a long soak, zero ingress drops and full requested reader duration remain mandatory.

## Stop rule

Do not:

- increase ingress capacity to rescue saturation;
- tune the microbatch cap from V5 results;
- reintroduce live Python parity;
- loosen exact trigger parity;
- use V68 until sustained systems capacity passes.

If V5 still saturates, the next investigation is inside the remaining Python canonical adapter /
identity preparation boundary or the Carbon->Rust process boundary, not queue inflation.
