# Carbon Runtime / Signal Plane Replay v1 — Decision

Date: 2026-09-09

## Decision

**Classification: `ADAPT_CARBON_RUNTIME_BOUNDARY`**

Use Carbon 2.0.0 as a commodity datasource/decoder/runtime shell, but do **not** place slow
or awaitable persistence, research, enrichment, reporting, or other blocking work inside
Carbon's central processor loop.

The target hot-path boundary is a bounded, observable, constant-time handoff into
separate downstream work.

This decision is independent of provider selection, paid gRPC, V68 economics, Social/Event
research, and live execution.

## Evidence

Carbon release evaluated:

- version: `2.0.0`
- source release commit: `e901103c93833c9c79407cb4321561e30796ad51`
- Rust: `1.96.1`

GitHub Actions evidence:

- workflow: `Carbon runtime replay v1`
- successful run: `34396395162`
- job: `102617069922`
- frozen replay events: `5,000`
- target paced source rate: `5,000 events/s`
- Carbon input channel: `256`
- downstream handoff buffer: `1,024`
- artificial slow service: `5 ms every 100th event`

All frozen checks passed:

- pipeline correctness: PASS
- handoff accounting: PASS
- inline HOL reproduced: PASS
- representative async isolation: PASS
- representative zero drops: PASS
- burst drop accounting explicit: PASS

Key measurements on the CI runner:

| Scenario / metric | Result |
| --- | ---: |
| inline fast pipeline p95 | 0.0231155 ms |
| inline slow pipeline p95 | 5.3822833 ms |
| event immediately after slow inline work, p50 | 6.440415 ms |
| inline slow pipeline outstanding high-water | 42 |
| handoff slow pipeline p95 | 0.022765 ms |
| handoff slow drops | 0 |
| handoff slow pipeline outstanding high-water | 10 |
| handoff slow downstream outstanding high-water | 37 |
| unpaced handoff burst drops | 3,875 / 5,000 |
| unpaced handoff burst downstream high-water | 1,025 |

The absolute timings are CI-machine-specific. The architectural result is the relative
behavior: sparse 5 ms inline work propagated delay to unrelated subsequent events, while
the same work behind the bounded asynchronous handoff left Carbon's paced hot-path p95
essentially unchanged and produced zero representative-load drops.

## Direct source finding

Carbon 2.0.0 `Pipeline::run` receives updates from a bounded Tokio MPSC channel and awaits
`self.process(...)` in the central receive loop. Matching processors/pipes are also awaited.
The synthetic replay therefore isolates and validates the scheduling consequence of that
implementation: slow inline processors create global head-of-line blocking.

## Architectural consequence

Target Market Signal Plane boundary:

```text
provider / replayable datasource
          ↓
Carbon datasource + maintained decoders
          ↓
canonical causal event adapter
          ↓
memory-first Signal Kernel
          ↓
bounded + observable constant-time handoff
       ↙                         ↘
fast signal path          async research plane
                          persistence/enrichment
```

Hot-path invariant:

> No slow or awaitable I/O, database write, research enrichment, report generation, or
> other non-constant-time downstream service may execute inline in Carbon's central
> processor path.

A bounded `try_send` handoff is not automatically lossless. The burst scenario deliberately
showed saturation and explicit drops. Production promotion therefore requires explicit
buffer-pressure telemetry and a recovery/degraded-state policy; silent drops are forbidden.
A durable external queue such as NATS/Kafka is still **deferred** until an actual process or
durability requirement is demonstrated.

## Component decisions after v1

- Carbon Pump.fun decoder: **ADOPT**
- Carbon PumpSwap decoder: **ADOPT**
- Carbon stock runtime with arbitrary inline slow processors: **REJECT AS-IS**
- Carbon datasource/runtime shell with strict hot-path boundary: **ADAPT**
- custom Rust runtime rewrite: **DEFER**
- SQLite on hot path: **REMOVE from target**
- SQLite research/audit plane: **KEEP**
- paid gRPC migration: **DEFER**
- V68: **FROZEN / NOT_EVALUATED**
- live money: **DEFER**

## What this does not prove

This benchmark intentionally used synthetic `BlockDetails` updates to isolate Carbon runtime
scheduling. It does not yet prove full Pump/PumpSwap end-to-end throughput through raw
transaction ingestion, maintained decoder, canonical adapter, memory-first kernel, and
signal emission.

The next integration experiment should therefore test the target Market Signal Plane as a
whole, while preserving the strict runtime boundary established here.
