# Multichain Launch Burst Contract V0

Status: **shared scientific envelope only**. This does not merge strategies, selectors, features, outcomes or execution contracts across chains.

## Why this exists

The project now has independent Market-First launch research on at least:

- Solana / Pump;
- Robinhood Chain / Pons V2.

A shared envelope is useful for orchestration, storage, audit and later comparison, but a dangerous abstraction would silently turn protocol-specific facts into fake equivalents. V0 therefore standardizes **metadata and causal contracts**, not market meaning.

## Common envelope

Every wrapped snapshot carries:

- chain namespace and optional chain id;
- protocol namespace;
- stratum;
- launch and token identifiers;
- local anchor / cutoff / snapshot clocks;
- horizon;
- explicit quote-unit metadata;
- feature namespace;
- the original namespaced feature dictionary;
- provenance and data-quality flags;
- protocol-specific extension containing the complete source snapshot;
- `feature_only`, `economic_outcomes_opened`, and `selector_frozen` flags.

The source snapshot is retained as canonical JSON inside the extension so adaptation is lossless at the JSON artifact boundary.

## Feature namespaces stay separate

Examples:

- `solana.pump.launch_burst_shadow_v0:signed_flow_over_event_reserve`
- `robinhood.pons_v2.launch_burst_v0:signed_quote_flow_over_activity`

These are **not aliases**. The first sums trade quote-size / event reserve ratios; the second is raw signed quote flow divided by raw gross quote activity. A later research hypothesis may relate them, but the multichain contract must never rename one into the other.

## Quote units

Raw quote fields are comparable only when both snapshots explicitly identify:

1. `unit_kind = raw_quote_asset_units`;
2. the same semantic quote asset;
3. the same decimals.

Unknown metadata stays `None` and blocks comparison. It is never replaced by zero or guessed from context.

Robinhood Pons native quote is protocol-defined native ETH and therefore may carry semantic asset `ETH`, 18 decimals. Custom-pair tokens remain their contract address with semantic identity/decimals missing unless causal metadata is supplied.

The frozen Solana feature snapshot records whether raw quote aggregation was valid but does not itself expose the concrete quote-asset identity. The adapter therefore requires external causal metadata before raw-quote comparison is allowed.

## Explicit normalization only

Cross-asset comparison such as SOL flow vs ETH flow in USD requires an explicit normalization object containing:

- source feature name;
- semantic feature name chosen by the research contract;
- conversion factor;
- common unit;
- normalization evidence availability clock;
- provenance.

Normalization evidence must have been available **at or before the feature cutoff**. A later price cannot backfill an earlier snapshot.

Matching common units alone are insufficient: semantic feature names must also match.

## Current adapters

### Solana / Pump

Consumes the frozen snapshot shape used by `OnlinePumpFeatureState`:

- `observed_t0_wall_ns`;
- `decision_cutoff_wall_ns`;
- `evidence_window_seconds`;
- `features`.

All source fields are retained. Quote identity/decimals remain missing unless explicitly supplied.

### Robinhood / Pons V2

Consumes `PonsBurstSnapshotV0.to_dict()` output. Native ETH quote metadata is protocol-defined; custom pairs remain non-headline and incomplete unless their quote metadata is supplied causally.

## Hard scientific guards

V0 rejects:

- snapshot freeze before causal cutoff;
- cutoff inconsistent with anchor + horizon;
- `feature_only=true` together with `economic_outcomes_opened=true`;
- raw quote comparison with missing/different quote semantics;
- normalized comparison with different common units;
- normalized comparison with different semantic feature names;
- normalization evidence arriving after the feature cutoff.

## Non-goals

V0 does not:

- merge Solana and Robinhood cohorts;
- copy the Solana `0.08` threshold to Robinhood;
- pick a common primary horizon;
- define a cross-chain score;
- claim reserve-normalized and activity-normalized flow are equivalent;
- normalize assets automatically;
- choose a chain;
- open outcomes;
- modify either chain's frozen/prospective research branch.

A future comparison experiment must preregister exactly which independently validated features and execution contracts are being compared.