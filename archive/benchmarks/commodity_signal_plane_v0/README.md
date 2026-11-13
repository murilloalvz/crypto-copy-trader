# Canonical State/Signal Kernel Benchmark v0

Purpose: test the architectural hypothesis that the frozen Market Opportunity Radar can run from a bounded, memory-first canonical state without synchronous SQLite/research work in its critical path.

This is an **additive offline benchmark**. It does not change the V9 pipeline, detector thresholds, V68, route research, persistence semantics, or live behavior.

## What v0 proves

Given the same canonical `MarketTradeObservation` / `MarketLifecycleObservation` trace, compare:

1. an unbounded in-memory reference state that delegates decisions to the frozen Radar; and
2. a bounded memory kernel that retains only the Radar's 300-second causal horizon.

The benchmark requires exact trigger/feature parity at every canonical trade decision point and reports measured service time plus a deterministic single-worker queue simulation at `1x`, `1.25x`, `1.5x`, `2x`, and `MAX` (all arrivals at time zero).

Reported metrics include p50/p95/p99 service and queue wait, sustainable events/s, queue/outstanding high-water, oldest outstanding item age, backlog at source end, drain time, CPU time, and Python peak traced memory.

## What v0 does NOT prove

It does **not** benchmark Carbon decoders or a Yellowstone provider. Persisted market observations are already normalized and do not retain the raw Solana transaction/meta/instruction payload required for a valid decoder comparison.

It also evaluates the kernel once per canonical trade record. Production Pump/PumpSwap bridges evaluate at notification/transaction boundaries, so v0 is a **kernel-equivalence** test, not bridge-notification parity.

Carbon Pump.fun/PumpSwap decoder parity is a separate v1 that must start from a raw transaction trace.

## Trace modes

### Persisted real run

The exporter reuses `market_trade_observations` and `market_lifecycle_observations` from an existing acquisition run. No network call or new prospective run is made.

Because persisted `observed_at` is second-resolution, equal-second ingress order cannot be recovered exactly. The exporter therefore uses a deterministic tie-break and marks the trace:

`order_quality = reconstructed_from_second_resolution_observed_at`

This trace is appropriate for state-kernel parity and capacity characterization, but not for raw decoder/ingress parity.

### Deterministic synthetic trace

A synthetic generator creates Pump/PumpSwap canonical trades with bursts, hot-asset concentration, multi-event transaction identities, and Pump lifecycle observations. It is intended for a fast fail-closed smoke before using a real persisted run.

## Commands

From the repository root:

```powershell
python -m unittest tests.test_commodity_signal_plane_v0 tests.test_market_opportunity_radar -v

python -m benchmarks.commodity_signal_plane_v0.benchmark synthetic `
  --out artifacts\commodity_signal_plane_v0\synthetic-10k.jsonl `
  --events 10000 `
  --seed 68

python -m benchmarks.commodity_signal_plane_v0.benchmark run `
  --trace artifacts\commodity_signal_plane_v0\synthetic-10k.jsonl `
  --out artifacts\commodity_signal_plane_v0\synthetic-10k-report.json
```

Then reuse the high-load V68 systems-aborted acquisition (economic hypothesis remains NOT_EVALUATED):

```powershell
python -m benchmarks.commodity_signal_plane_v0.benchmark export `
  --run-key route-research-v68-prospective-flow60-buy-share-20260909-02-B `
  --out artifacts\commodity_signal_plane_v0\v68-02-b.jsonl

python -m benchmarks.commodity_signal_plane_v0.benchmark run `
  --trace artifacts\commodity_signal_plane_v0\v68-02-b.jsonl `
  --out artifacts\commodity_signal_plane_v0\v68-02-b-report.json
```

If that run-key is not present in the local SQLite database, do not rerun V68. The synthetic result remains valid for the harness, and another already-persisted systems run can be exported later.

## Promotion rule

v0 is ready to support the architecture decision only when:

- exact reference/shadow parity is 100%;
- zero correctness exceptions occur;
- the memory kernel has bounded queue behavior at representative load;
- `1.5x` expected load has meaningful latency/capacity headroom;
- overload behavior is explicit in the report rather than hidden by eventual post-source drain.

If parity is 100% with strong headroom, the next experiment is **raw transaction trace + Carbon Pump.fun/PumpSwap decoder parity v1**. If parity fails, fix only the canonical state semantics before any provider/Rust work. If the memory kernel itself saturates too early, optimize/partition the state kernel before introducing Carbon.
