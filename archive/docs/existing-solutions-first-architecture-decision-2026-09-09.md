# Existing Solutions First — architecture decision checkpoint (2026-09-09)

Status: strategic checkpoint; no production migration authorized by this document.

## Decision

The project is no longer optimizing the V1→V9 acquisition stack as a presumed final production architecture. That stack is frozen as a correctness/reference baseline while commodity alternatives are benchmarked.

Permanent decision loop for major components:

`SEARCH -> UNDERSTAND -> BENCHMARK/VALIDATE -> ADOPT/ADAPT/REJECT -> BUILD only what remains necessary`

Current provisional classifications:

- Geyser / Yellowstone protocol: **ADOPT** interface candidate.
- Managed Yellowstone/LaserStream providers: **BENCHMARK**, choose from measured latency/coverage/recovery/cost.
- Carbon Pump.fun and PumpSwap decoders: **ADOPT candidate**, pending raw-transaction parity.
- Carbon datasource/metrics primitives: **ADOPT/ADAPT candidate**.
- Carbon whole pipeline runtime: **BENCHMARK**, not assumed optimal for this workload.
- custom Rust runtime: **DEFER**.
- SQLite in signal-ready critical path: **REPLACE/REMOVE from target architecture**.
- SQLite in research plane: **KEEP while adequate**.
- current Market Opportunity Radar: **FROZEN BASELINE**, not presumed final production detector.
- V68 economic hypothesis: **NOT_EVALUATED and FROZEN**; no new run until the new intelligence stack makes it relevant again.

Target separation:

`Solana stream -> minimal decode/normalize -> bounded in-memory Signal Plane -> evidence/signal`

and asynchronously:

`canonical events/signals -> persistence/audit/research/outcomes/analytics`

Market-First and Social/Event-First remain independent research/acquisition tracks. Convergence is a third optional hypothesis only after independent evidence supports it.

## Immediate experiment sequence

1. Canonical State/Signal Kernel Benchmark v0: prove bounded memory-state equivalence/headroom without SQLite/research in the measured path.
2. Raw Transaction + Carbon Decoder Parity v1: only after raw Solana tx/meta/instruction trace exists.
3. Provider bake-off: same machine/window, compare delivery latency, coverage, duplicates, gaps, reconnect/replay and cost.
4. Intelligence family benchmarks, one at a time: launch lifecycle, liquidity-normalized flow, regime/change detection, participant structure.
5. Build the Market Signal Plane only from components that survive those comparisons.

Frozen meanwhile: Tailfix V10+, Radar threshold expansion, new economic thresholds/features, new wallet heuristics/scores, new exits, full Social implementation, production Rust rewrite, definitive provider migration, NATS/Kafka, V68, and live-money execution.
