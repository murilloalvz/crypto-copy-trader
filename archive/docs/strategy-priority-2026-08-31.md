# Strategy priority — 2026-08-31

## Priority decision

The main strategy-research priority is now **Opportunity Intelligence**, with Wallet Strategy Intelligence first and Social/X Intelligence as the next sensor layer.

This does **not** replace or retune `wave_v3_volume_integrity`. The existing Wave entry remains frozen while its forward cohort continues whenever the discovery provider is available.

## Research thesis

```text
market structure / Wave
        +
wallet behavior
        +
social / X context
        ↓
causal opportunity context
        ↓
predeclared strategy hypotheses
        ↓
replay + costs/latency/liquidity stress
        ↓
concurrent shadow
        ↓
possible Strategy Router later
```

## Current status

### Wallet Strategy Intelligence

- single-wallet on-chain profiling: IMPLEMENTADO;
- entry context: IMPLEMENTADO;
- multi-day holding context: IMPLEMENTADO;
- observed exit timing/path context: IMPLEMENTADO;
- exit sizing: IMPLEMENTADO;
- multi-wallet deterministic Strategy Lab: IMPLEMENTADO;
- broad high-quality wallet sourcing without Data API credits: still constrained;
- cross-wallet strategy claims: NOT VALIDATED yet.

### Social / X Intelligence

- causal event model with `created_at` and `observed_at`: IMPLEMENTADO;
- anti-lookahead snapshot selection: IMPLEMENTADO;
- causal 5m/15m/60m descriptive windows: IMPLEMENTADO;
- offline JSONL context CLI: IMPLEMENTADO;
- live X collector: PLANNED;
- mint/entity resolution: PLANNED;
- social outcome replay: PLANNED;
- social score: intentionally not implemented.

### Forward / provider operations

- hybrid monitor remains the normal forward collector when Solana Tracker Data API discovery is available;
- Data API credit exhaustion currently prevents new discovery;
- official `monitor_existing.py` fallback is implemented for price/exit tracking of already-existing signals without Data API discovery;
- price-only runtime does not replace forward signal collection.

## Next high-information tasks

1. Run the full unit suite after pulling the latest branch changes.
2. Use Wallet Strategy Lab on a broader explicit wallet cohort as soon as addresses are available.
3. Preserve source/provenance and cohort-entry time for every wallet to reduce survivorship bias.
4. Build the live social collector only after choosing an X API budget/query scope.
5. Persist `observed_at` for every social event and never reconstruct it from `created_at` in replay.
6. Add token/mint entity resolution before joining social events to market outcomes.
7. Compare independent evidence sets rather than immediately summing them into one score.
8. Promote only predeclared hypotheses that survive causal replay and execution stress to shadow.

## Non-goals right now

- no live trading;
- no automatic strategy switching;
- no lowering Wave filters to manufacture sample;
- no declaring 7mPti or any single wallet a universal strategy template;
- no broad expensive X firehose before proving targeted collection has useful information density;
- no historical "best policy per trade" router, which would introduce selection leakage.
