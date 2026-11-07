# Carbon Decoder Parity v1

Research-only same-payload correctness benchmark for Pump.fun and PumpSwap.

This benchmark does **not** change production acquisition, Radar, persistence, V68, wallet
scoring, exits, signing, or execution.

## Frozen corpus

The preflight-approved corpus is expected to contain:

- 166 raw transactions;
- 79 Pump `TradeEvent`;
- 2 Pump `CreateEvent`;
- 29 PumpSwap `BuyEvent`;
- 40 PumpSwap `SellEvent`;
- 150 target events total.

The event denominator is the contextual `Program data:` payloads emitted while the matching
Pump/PumpSwap program is the active Solana runtime invocation. Merely referencing a program
address is not enough.

## Carbon version

The runner pins the immutable crates.io releases:

- `carbon-pumpfun-decoder = 2.0.0`
- `carbon-pump-swap-decoder = 2.0.0`

Carbon 2.0.0 release commit reference:

`e901103c93833c9c79407cb4321561e30796ad51`

Carbon 2.0.0 declares Rust `1.96.1` as its minimum supported Rust version.

## Scientific boundary

```text
same raw transaction
        |
        v
Solana meta.logMessages
        |
        v
runtime invocation stack
        |
        v
same exact Program data payload
        |
        +-------------------+
        |                   |
        v                   v
our Python decoder      Carbon 2.0.0
        |                   |
        v                   v
canonical event         canonical event
        +---------+---------+
                  |
                  v
            exact parity
```

This isolates decoder correctness from transport, provider latency, persistence, database,
Radar, and economic logic.

## Run

From the repository root:

```powershell
python -m unittest discover -s tests -p "test_carbon_decoder_parity_v1.py" -v
```

Prepare identical event inputs and our canonical output:

```powershell
python -m benchmarks.carbon_decoder_parity_v1.parity prepare `
  --corpus "artifacts\free_historical_corpus_v2\pump-pumpswap-balanced-166.jsonl" `
  --carbon-input "artifacts\free_historical_corpus_v2\carbon-decoder-input-v1.jsonl" `
  --ours-out "artifacts\free_historical_corpus_v2\ours-canonical-events-v1.jsonl"
```

The prepare stage must report:

- `contextual_target_events = 150`
- `our_decoded_events = 150`
- `our_decode_errors = 0`
- `program_log_stack_errors = 0`
- `frozen_counts_match = true`
- `valid_for_carbon_decoder_run = true`

Check Rust:

```powershell
rustc --version
cargo --version
```

Carbon 2.0.0 requires Rust 1.96.1 or newer. If Rust is already installed through rustup:

```powershell
rustup update stable
```

Build and run the Carbon side:

```powershell
cargo run --release `
  --manifest-path benchmarks\carbon_decoder_parity_v1\rust_runner\Cargo.toml `
  -- `
  "artifacts\free_historical_corpus_v2\carbon-decoder-input-v1.jsonl" `
  "artifacts\free_historical_corpus_v2\carbon-canonical-events-v1.jsonl"
```

Then compare:

```powershell
python -m benchmarks.carbon_decoder_parity_v1.parity compare `
  --ours "artifacts\free_historical_corpus_v2\ours-canonical-events-v1.jsonl" `
  --carbon "artifacts\free_historical_corpus_v2\carbon-canonical-events-v1.jsonl"
```

## PASS criterion

`PASS_CARBON_DECODER_PARITY_V1` requires:

- exactly 150 frozen target events;
- Carbon output for every event;
- zero Carbon decode failures;
- zero missing events;
- zero extra events;
- zero duplicate event keys;
- exact semantic parity on all canonical fields;
- valid Carbon 2.0.0 footer.

Any mismatch is investigated individually. Do not tune the corpus or denominator after seeing
results.

Performance benchmarking is deliberately deferred until correctness passes.
