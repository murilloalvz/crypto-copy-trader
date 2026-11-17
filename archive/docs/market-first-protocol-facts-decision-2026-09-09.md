# Market-First protocol facts v0 — decision

Date: 2026-09-09
Branch: `spike/commodity-signal-plane-v0`

## Mission

Add only the protocol-aware causal facts that are still missing after inventorying the existing Market-First stack. Do not create another opportunity score, another episode model, or another generic flow snapshot.

## Existing components kept

- `OpportunitySnapshotCoreV1`: KEEP for 10/30/60/300-second flow windows, notional imbalance, return, lag and field coverage.
- `MarketIntegrityFeatures`: KEEP for participant arrival, repeated participation and top-N buy concentration.
- `MarketOpportunityEpisode`: KEEP as the canonical persisted market episode and `decision_as_of` boundary.
- `IndexedMarketSignalKernel`: KEEP for memory-first frozen-Radar state/decision semantics.
- PONS curve/launch modules: do not port protocol math; reuse only their causal/missingness design principles.

## External protocol evidence

Pump official public docs currently state:

- the bonding-curve account exposes an explicit `complete` field;
- `complete` is set when the curve finishes, so v0 uses that explicit field and never infers completion from a reserve threshold;
- Pump is evolving from SOL-specific reserve naming to quote-reserve naming for additional quote mints, so the canonical v0 schema uses `*_quote_reserves` at the adapter boundary.

PumpSwap official public docs currently state:

- Pump migrations create the canonical PumpSwap pool at index `0`;
- v0 nevertheless requires explicit migration instruction/event/link evidence in addition to index 0, so mere PumpSwap activity cannot manufacture lineage;
- `virtual_quote_reserves` is appended to the pool/event schema;
- protocol quoting uses `effective_quote_reserves = raw quote-vault reserve + virtual_quote_reserves`;
- missing `virtual_quote_reserves` remains missing in v0 instead of silently assuming zero.

Primary references:

- https://pump.fun/docs/bonding-curve
- https://github.com/pump-fun/pump-public-docs/blob/main/docs/PUMP_PROGRAM_README.md
- https://github.com/pump-fun/pump-public-docs/blob/main/docs/PUMP_SWAP_README.md

## Existing-solutions decision for regime detection

EWMA and CUSUM are mature sequential change-detection techniques. NIST documents EWMA as useful for gradual/small shifts and CUSUM as efficient for small mean shifts. They are therefore benchmark candidates, not inventions to replace with an opaque custom score.

Decision:

- simple event-rate / nested-window facts already present in our stack: KEEP;
- EWMA: ADAPT as the first regime-change challenger after protocol facts are replayable;
- CUSUM/Page-Hinkley: ADAPT/BENCHMARK as a second challenger;
- Bayesian online changepoint detection: DEFER until simpler methods fail to provide adequate earliness/precision;
- Hawkes process: DEFER until evidence shows self-excitation modeling adds decision value.

References:

- https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc314.htm
- https://www.itl.nist.gov/div898/handbook/pmc/section3/pmc313.htm

## New v0 boundary

`src/market_protocol_facts.py` owns only:

- causal Pump curve state;
- causal PumpSwap pool state;
- explicit Pump -> PumpSwap migration evidence;
- factual lifecycle label derived from those observations;
- reserve provenance and explicit missingness.

It must not own:

- opportunity score;
- confidence;
- TAKE/SKIP recommendation;
- wallet PnL labels;
- social evidence;
- execution decision;
- economic outcome;
- future/backfilled evidence.

## Frozen lifecycle labels

- `UNKNOWN`
- `PUMP_BONDING_ACTIVE`
- `PUMP_CURVE_COMPLETE`
- `PUMPSWAP_ACTIVE_UNPROVEN_LINEAGE`
- `PUMPSWAP_MIGRATED_CANONICAL`

These are factual evidence states, not quality/risk levels.

## Causal invariants

1. Exact mint only.
2. `chain_time <= as_of` and `observed_at <= as_of` are both required.
3. Future append must not change an earlier snapshot.
4. Late older-chain evidence becomes visible only when observed.
5. Pump completion is never inferred from reserves.
6. PumpSwap activity, pool address or pool index alone never creates migration evidence.
7. Canonical migration requires supported explicit migration evidence and pool index 0.
8. Missing virtual quote reserves remain missing.
9. No score/confidence/recommendation surface exists in the output.
10. Provenance is deterministic and retained.

## Promotion gates

Before composition into episode enrichment:

- targeted tests PASS;
- future-append differential PASS;
- full unit suite PASS because a production `src/` module changed;
- no frozen Radar or V68 economics changed.

## Status

Implementation prepared. Promotion verdict remains `PENDING_VALIDATION` until CI executes the gates above.
