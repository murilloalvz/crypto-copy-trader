# Integrated Market Signal Plane — decision (2026-09-09)

## Verdict

`PASS_INDEXED_MARKET_SIGNAL_PLANE_V1`

The target Market Signal Plane should use:

```text
Carbon datasource / maintained decoders
    -> strict canonical event adapter
    -> indexed memory-first per-asset Radar kernel
    -> bounded observable handoff
    -> async research / persistence / enrichment
```

The frozen Market Opportunity Radar rules and method version remain unchanged.

## Evidence chain

1. `PASS_CARBON_DECODER_PARITY_V1`
   - 150/150 exact target events on the frozen Pump.fun/PumpSwap raw corpus.
   - zero missing, extra, duplicate, or side-inverted canonical events.

2. `ADAPT_CARBON_RUNTIME_BOUNDARY`
   - stock Carbon central processing awaits processors;
   - 5 ms slow inline work produced global HOL;
   - constant-time bounded handoff kept Carbon pipeline p95 near baseline;
   - overload was explicit rather than silent.

3. Initial integrated Python kernel replay
   - canonical adapter: 100%;
   - frozen Radar parity: 100%;
   - original bounded memory kernel capacity was insufficient at the frozen 5k/7.5k rates.

4. Prevalidated candidate
   - 100% frozen Radar parity;
   - removed repeated historical validation;
   - ~2x capacity gain versus same-run baseline;
   - 5k passed, but 7.5k still accumulated backlog.

5. Indexed rolling-window candidate — PASS
   - 10,024 canonical records / 10,000 trade decision points;
   - adapter parity: 100%;
   - indexed Radar parity: 100%;
   - zero indexed mismatches;
   - mean service: ~0.0754 ms;
   - p95 service: ~0.2557 ms;
   - p99 service: ~0.2835 ms;
   - capacity from mean service: ~13,259 events/s;
   - +49.5% capacity versus prevalidated candidate in the same CI run;
   - 5k events/s: zero source-end backlog, queue wait p95 ~0.268 ms;
   - 7.5k events/s: zero source-end backlog, queue wait p95 ~5.015 ms;
   - research handoff: zero drops at 5k and 7.5k;
   - synthetic all-at-once burst: bounded overload produced explicit/reconciled drops.

GitHub Actions run: `34399377138`.

## Structural reason for the gain

The frozen detector only needs the full 300-second horizon to determine the **count** of baseline events. Detailed feature calculations use the 30-second fast window.

The indexed candidate therefore:

- stores per-asset rows ordered by `(chain_time, observed_at, sequence)`;
- uses binary-search boundaries for the 300s / 30s windows;
- counts the 270-second baseline by index distance instead of rescanning it;
- materializes and scans only the 30-second fast window for detailed features;
- preserves late-chain-time insertion semantics;
- fails closed on same-asset `observed_at` regression.

This is algorithmic improvement, not threshold tuning and not worker-count tuning.

## Decisions

### Adopt / adapt

- Carbon Pump.fun decoder: **ADOPT**.
- Carbon PumpSwap decoder: **ADOPT**.
- Carbon datasource/runtime shell: **ADAPT** behind constant-time hot-path boundaries.
- indexed memory-first Radar state: **PROMOTION CANDIDATE** pending broader differential/real-trace parity.
- bounded observable research handoff: **ADOPT pattern**.

### Reject / defer

- slow persistence/enrichment inside Carbon processor: **REJECT**.
- synchronous SQLite in hot path: **REJECT target architecture**.
- custom Rust runtime rewrite: **DEFER**.
- Python thread sharding as a CPU-capacity fix: **DO NOT USE as primary plan**; CPython GIL makes that an unsafe scaling assumption.
- process partitioning/Rust kernel: **DEFER** because single-process indexed candidate already passed 7.5k synthetic headroom.

## Scientific limitations

This PASS is structural/capacity evidence, not economic evidence.

The 10k indexed replay is synthetic and deterministic. Before production promotion, require:

1. differential randomized parity over missingness, late-chain-time inserts, lifecycle availability, and transaction-identity edge cases;
2. parity on an already-persisted real high-load trace if available locally;
3. no change to detector thresholds or method version;
4. no new V68 acquisition merely to validate this implementation.

`V68 ECONOMIC HYPOTHESIS = NOT_EVALUATED` remains unchanged.
