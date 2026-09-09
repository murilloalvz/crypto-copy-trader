# Market-First Research Readiness — 2026-09-09

## Verdict

**MARKET-FIRST PIPELINE: RESEARCH-READY AFTER COVERED LIVE INPUT; ECONOMIC EDGE NOT EVALUATED.**

The project now has a causal, score-free Market-First path from maintained protocol decoding to immutable episode research snapshots.  The remaining blocker for real regime replay is not another detector or another score: it is explicit continuous collector coverage from a fresh acquisition run.

This checkpoint does not authorize live money, revive V68, rank opportunities, calibrate confidence, or combine Market-First with Social/Event-First.

## Validated stack

```text
maintained Carbon Pump/PumpSwap decoding
        ↓
canonical market observations
        ↓
IndexedMarketSignalKernel
        ↓
MarketProtocolFactsV0
        +
OpportunitySnapshotCoreV1
        +
PumpCreationModeFactsV0
        ↓
MarketIntelligenceBaselineV0
        +
explicit collector coverage
        ↓
causal fixed-bin intensity
        ↓
coverage-aware River Page-Hinkley (research only)
        ↓
MarketRegimeResearchFactsV0
        ↓
frozen MarketEpisodeResearchSnapshotV0
        ↓
future outcomes joined only after T0
```

## Component status

### Maintained decoders

- Carbon Pump.fun semantic parity: PASS 150-event corpus contribution.
- Carbon PumpSwap semantic parity: PASS 150-event corpus contribution.
- Decision: ADOPT maintained decoders; custom decoding is no longer the preferred production direction.

### Signal kernel

- indexed in-memory kernel: 100% semantic parity against the frozen Radar in short and long-horizon differential replay;
- 7,200/7,200 long-horizon decisions exact;
- 2,558 late inserts and 1,138 compactions exercised;
- synthetic capacity materially above 7.5k events/s target with zero backlog at the frozen target loads.

Decision: production-valid on this research branch; do not add Rust/process sharding without evidence.

### Market intelligence baseline

`MarketIntelligenceBaselineV0` composes:
- protocol/lifecycle state;
- causal flow windows;
- participant breadth/repetition where identity coverage is sufficient;
- signed USD notional / imbalance where coverage permits;
- price response;
- observation lag;
- causal execution quote/liquidity/impact evidence.

It contains no score, confidence, recommendation, TAKE/SKIP, Social evidence, or outcome.

Full-suite gate after introduction: PASS.

### Liquidity-normalized flow

**NOT AVAILABLE YET by design.**

Current flow notionals are USD while protocol reserves are raw token/quote units.  A ratio across those units would be dimensionally invalid.  The baseline therefore exposes explicit missingness instead of fabricating a feature.

Next valid implementation requires matched-unit quote flow + quote reserve with mint/decimals/provenance.

### Mayhem Mode

Pump.fun exposes Mayhem as a creation-time protocol fact, and Carbon's maintained Pump `CreateV2` decoder exposes `is_mayhem_mode`.

`PumpCreationModeFactsV0` therefore accepts only explicit creation-instruction evidence.  No amount of flow, activity, or wallet behavior may infer Mayhem.  Unknown remains `None`; conflicting explicit evidence fails closed.

### Regime / earliness

Existing-solutions-first benchmark compared maintained River detectors with no outcome fitting and no parameter tuning.

Frozen synthetic behavior:
- stable stream: Page-Hinkley 0 false alarms; ADWIN 0;
- persistent abrupt up/down: Page-Hinkley delay 8, ADWIN delay 11;
- short 8-point pulse: Page-Hinkley ignored it; ADWIN fired after the pulse;
- gradual increase: Page-Hinkley first delay 46, ADWIN 43.

Decision: River Page-Hinkley defaults (`mode=both`) are the first descriptive baseline candidate.  This is not an economic verdict and defaults are not frozen production parameters.

### Coverage boundary

The key scientific rule is now explicit in code:

> no event observed != observed zero events.

A zero-intensity bin exists only when an acquisition component explicitly asserts continuous coverage for the entire bin and that coverage assertion itself was available at T0.  Otherwise the bin is `MISSING`.

A MISSING gap resets Page-Hinkley rather than joining regimes across unknown time.

`MarketCollectionCoverageStoreV0` persists these assertions in the research plane and keeps the first persisted evidence identity canonical on replay.

### Episode research unit

`MarketEpisodeResearchSnapshotV0` requires:
- already-frozen `decision_as_of`;
- exact token identity across all inputs;
- all feature surfaces at exactly that T0;
- no regime detection after T0;
- explicit missingness when regime or Mayhem evidence is absent.

This is the object future outcome analysis should join against.  Feature construction and outcome collection remain separate.

## What existing historical data can and cannot do

The existing Helius historical transaction corpus is valid for decoder semantics and transaction/event content.  It is **not** proof of continuous live collector coverage.

Therefore it can support:
- decoder parity;
- event/schema studies;
- protocol fact extraction from the captured transactions;
- non-continuous descriptive analysis.

It cannot safely support:
- zero-filled per-second activity series;
- absence-of-trade claims between sparse sampled signatures;
- a coverage-valid continuous Page-Hinkley replay.

Do not repair this limitation by filling missing seconds with zeros.

## Next valid acquisition

The next useful market-data run should be a read-only/free live or shadow collector that records, from the acquisition boundary itself:

1. exact run key;
2. source/provider and subscription scope;
3. connection/subscription state;
4. covered market/chain-time intervals only while completeness is defensible;
5. explicit gaps during disconnect/reconnect/error periods;
6. transaction/event observations with `chain_time` and real `observed_at`;
7. decoded Pump `CreateV2.is_mayhem_mode` when present;
8. no outcome-dependent filtering.

Only after this run should real covered intensity/regime replay begin.

## Same-day engineering ceiling

The engineering architecture can reasonably be taken today to:

```text
covered read-only acquisition contract
→ persisted coverage
→ canonical observations
→ score-free Market Intelligence
→ coverage-aware regime evidence
→ frozen MarketEpisode research snapshots
→ ready-to-collect forward outcomes
```

What cannot be honestly completed from code alone today:
- a proven profitable Market-First edge;
- calibrated confidence;
- an Opportunity Ranker validated prospectively;
- Social/Event-First validation;
- convergence validation;
- execution/fill economics;
- live-money authorization.

Those require fresh observations and prospective outcome evidence, not more architecture.

## Frozen next experiment

**MARKET-FIRST COVERED SHADOW ACQUISITION V0**

Purpose: obtain the first continuous, causally covered Market-First sample suitable for real regime and episode replay.

Promotion requirements before interpreting economics:
- collector coverage intervals are persisted from source state, never reconstructed later;
- gaps remain gaps;
- exact mint and dual clocks preserved;
- no dropped-event silence masquerades as coverage;
- Mayhem fact is explicit/unknown;
- MarketEpisode snapshot frozen before outcomes;
- outcomes collected separately;
- no threshold tuning during acquisition.

V68 remains `NOT_EVALUATED` and is not part of this experiment.
