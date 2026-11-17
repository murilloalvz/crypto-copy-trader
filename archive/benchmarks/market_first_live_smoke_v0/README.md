# Market-First LIVE Smoke v0

Operational-only 5-minute smoke for the frozen Market-First signal/research composition.

This runner is additive. It does **not** change Radar thresholds, the bounded Signal Plane,
Helius Standard WSS acquisition, Carbon decoding, the immutable six-hour discovery contract,
Social/Event-First research, economic hypotheses, signing, or execution.

## Purpose

Exercise one real live path end to end before any six-hour Market-First discovery is opened:

```text
Helius Standard WSS (300 s)
  -> existing WSS reducer
  -> pinned Carbon 2.0.0 decoder
  -> causal receive-order reconstruction
  -> existing matched-unit adapters
  -> MarketTradeObservation / MarketLifecycleObservation
  -> IndexedMarketSignalKernel
  -> run-scoped MarketOpportunityEpisode (only if Radar triggers)
  -> immutable MarketEpisodeResearchSnapshotV0 at first-trigger T0
  -> separate PENDING +5m/+15m/+60m forward outcomes
```

The official CLI duration is fixed at **300 seconds** and has no duration override.
Each run gets a unique `run_id`, `acquisition_run_key`, cohort label and artifact directory.
The six-hour Market Activity discovery registry is never opened or reused by this smoke.

## Causal and missingness rules

- `first_received_wall_ns` from the existing WSS reducer manifest is the local causal receive clock.
- Carbon output is re-ordered by that clock before stateful kernel ingestion because the reducer's
  output file itself is deterministically keyed, not an ingress-order contract.
- PumpSwap trades enter the kernel only when exact pool base/quote identity was already observed
  causally from an earlier decoded `pumpswap_create_pool` event in this smoke. Otherwise the existing
  adapter keeps the event `MISSING_CONTEXT`; no future lookup backfills it.
- USD notional and USD price remain absent when the frozen adapter cannot prove them.
- Pump CreateV2 / Mayhem enrichment is not invented. When unavailable, the T0 fact remains missing.
- No quote provider is called to manufacture execution context at T0.

## Coverage boundary

Helius Standard WSS is still classified as:

`operational_only_not_chain_complete`

A connected/active Standard WSS session is not proof of continuous scientific market coverage.
The smoke therefore writes an explicit `coverage.json` artifact with:

- `chain_complete_coverage_claimed = false`
- `scientific_continuous_coverage_persisted = false`
- `scientific_coverage_interval_count = 0`

It deliberately does **not** insert a fake `continuous_observed` interval into the scientific
coverage store.

## PASS / FAIL

`PASS_MARKET_FIRST_LIVE_SMOKE_V0` requires all of the following operational facts:

- fixed 300-second smoke identity and no six-hour discovery-registry reuse;
- an activated WSS operational shadow that reaches the duration deadline;
- reducer output valid for Carbon decode;
- coherent zero-failure Carbon footer accounting;
- at least one canonical trade reaches the existing indexed kernel;
- no Research Plane persistence error;
- no T0 preparation error for any episode that actually triggers;
- no canonical-manifest pairing error;
- no false chain-complete/scientific-coverage claim;
- clean coordinator shutdown and no fatal stage error;
- no economic verdict.

**Zero Radar trigger episodes does not fail the smoke.** A five-minute operational test is not an
opportunity-count or economic-edge experiment. It only requires that real canonical market trades
exercise the kernel path successfully.

## Artifacts

Each run writes under:

```text
artifacts/market_first_live_smoke_v0/<unique-run-id>/
```

with:

- `wss-trace.jsonl`
- `carbon-input.jsonl`
- `wss-target-manifest.jsonl`
- `carbon-canonical.jsonl`
- `coverage.json`
- `report.json`

The durable T0 snapshots and forward-outcome schedules use the repository's normal Research Plane
SQLite stores under the smoke's unique `acquisition_run_key`; they do not use a six-hour discovery
run/cohort.

## Tests

From the repository root:

```powershell
python -m unittest tests.test_market_first_live_smoke_v0 -v
```

The test suite covers fixed identity/duration, honest coverage, zero-trigger PASS semantics,
fail-closed operational gates, receive-order reconstruction, and T0 immutability after a future
outcome is completed in a temporary SQLite database.

## Live smoke

Prerequisites are the same already-proven Helius WSS and pinned Carbon environment. Confirm the API
key is present and Cargo is available, then run:

```powershell
if (-not $env:HELIUS_API_KEY) { throw "HELIUS_API_KEY não está definido nesta sessão." }
rustc --version
cargo --version
python -m benchmarks.market_first_live_smoke_v0.run
```

The process exits `0` only for `PASS_MARKET_FIRST_LIVE_SMOKE_V0`. The final JSON is also persisted
as `report.json` in the unique artifact directory.

## Promotion rule

Do **not** open or launch the six-hour Market-First discovery from this README.

Only after a real live smoke returns `PASS_MARKET_FIRST_LIVE_SMOKE_V0` should its report/artifacts be
reviewed and the separate immutable six-hour discovery be prepared. A FAIL is diagnosed at the
specific failed operational gate; detector thresholds and scientific denominators are not tuned to
make the smoke pass.
