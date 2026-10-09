# Carbon Runtime / Signal Plane Replay Benchmark v1

Purpose: decide whether Carbon 2.0.0 should be adopted as the stock Market Signal Plane
runtime, adapted behind a hot-path handoff boundary, or rejected.

This benchmark is additive and offline. It does **not** change the frozen Market Radar,
V68, economics, live acquisition, provider choice, or execution.

## Result

CI run `34396395162` produced:

`ADAPT_CARBON_RUNTIME_BOUNDARY`

At 5,000 paced events/s:

- stock fast Carbon pipeline p95: `0.0231155 ms`;
- 5 ms inline stall every 100 events raised pipeline p95 to `5.3822833 ms`;
- the event immediately after a stalled event had p50 `6.440415 ms`;
- the same slow work behind the bounded async handoff left pipeline p95 at `0.022765 ms`;
- representative handoff drops: `0`;
- unpaced burst saturated the 1,024 handoff buffer and produced `3,875` explicit,
  reconciled drops out of 5,000 events.

Decision: use Carbon as datasource/decoder/runtime shell **with a strict bounded and
observable hot-path handoff**. Do not run slow persistence, enrichment, research, reports,
or other awaitable I/O inline in Carbon's central processor loop. A production boundary
must never silently drop on saturation.

See `docs/carbon-runtime-replay-decision-2026-09-09.md` for the decision record.

## Why this exists

`PASS_CARBON_DECODER_PARITY_V1` established exact semantic correctness for the maintained
Carbon Pump.fun/PumpSwap decoders on the frozen corpus:

- 150/150 exact events;
- 100% canonical event parity;
- zero decode failures;
- zero missing/extra/duplicate events.

Decoder correctness does not automatically validate the Carbon runtime.

At Carbon release `2.0.0` / commit
`e901103c93833c9c79407cb4321561e30796ad51`, `Pipeline::run` receives updates from a
bounded Tokio MPSC channel and then awaits `self.process(...)` in one central loop.
Each matching pipe in `process` is also awaited. This v1 therefore tests the practical
consequence of putting slow work inline and whether an explicit asynchronous handoff
isolates that work without silent loss at representative load.

## Frozen scenarios

Default protocol:

- 10,000 events;
- 200 us source interval = 5,000 target events/s;
- Carbon input channel = 256;
- slow service = 5 ms every 100th event;
- async handoff buffer = 1,024.

Four scenarios are run:

1. `inline_fast` — stock Carbon loop, no artificial slow processor.
2. `inline_slow` — stock Carbon loop, 5 ms inline stall every 100 events.
3. `handoff_slow` — Carbon processor does constant-time `try_send`; slow service runs
   in a downstream worker at the same representative source rate.
4. `handoff_burst` — same handoff but unpaced source to expose bounded-overload
   behavior and verify that drops, if any, are explicit and reconciled.

No threshold may be changed after seeing a result in order to rescue a classification.

## Classification

`ADAPT_CARBON_RUNTIME_BOUNDARY` requires all of:

- exact source -> Carbon processing counts;
- zero Carbon processing order violations;
- exact handoff accounting (`enqueued + dropped == processed`);
- worker completion exactly equals handoff-enqueued;
- zero worker order violations;
- zero representative-load handoff drops;
- inline 5 ms stalls reproduce at least 1 ms p95 and immediate-bystander inflation
  relative to the fast baseline;
- representative async-handoff Carbon p95 stays within
  `max(3x fast_p95, fast_p95 + 1 ms)`;
- burst overload remains explicitly accounted.

Interpretation:

- `ADAPT...`: keep Carbon datasource/decoder/runtime shell, but never put slow
  persistence/research/enrichment in the central hot-path processor. Use a bounded,
  observable handoff into downstream work.
- `INCONCLUSIVE...`: frozen stall did not reproduce the expected inline HOL; inspect
  instrumentation and rerun unchanged.
- `REJECT_OR_INVESTIGATE...`: correctness/accounting/isolation failed.

This benchmark does not authorize paid gRPC, live money, V68, or a production migration.

## Run

From repository root, with the Python venv active:

```powershell
python -m unittest tests.test_carbon_runtime_replay_v1 -v

python -m benchmarks.carbon_runtime_replay_v1.suite `
  --out-dir "artifacts\carbon_runtime_replay_v1"
```

The suite generates `Cargo.lock` on first run if absent, builds the Rust runner with
`--locked`, executes all four frozen scenarios, writes individual reports plus
`suite-report.json`, and prints the verdict.

The CI workflow commits the generated
`benchmarks/carbon_runtime_replay_v1/rust_runner/Cargo.lock` after the frozen verdict passes,
so the dependency resolution is preserved byte-for-byte from the successful runner.
