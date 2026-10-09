# Dual-clock separation — 2026-09-10

## Status

**CLOSED STRUCTURAL BUG / CONTRACT FROZEN**

The live Helius WSS adapter audit exposed 510 `INVALID_EVENT` rows. A read-only diagnostic
showed that all 510 shared exactly one condition:

```text
observed_at - chain_time = -1 second
```

The invalids affected both Pump and PumpSwap. Quote amount, reserve, side, mint and pool
fields did not explain the failures.

The root cause was a scientific/modeling error: the code treated Solana chain Unix time
and the collector machine wall clock as a single synchronized clock domain.

## Correct contract

### Local availability clock

`observed_at` and higher-resolution `observed_wall_ns` answer only:

> Had this evidence actually reached the system by local decision time T0?

They are used for:

- no-lookahead gates;
- no-backfill gates;
- first-seen evidence;
- pool-account identity availability;
- quote/provider evidence availability;
- causal snapshot assembly.

### Chain / market clock

`chain_time` answers only:

> Where does an already-observed on-chain event belong in market-time ordering/windows?

It is used for:

- 10/30/60/300 second market windows;
- chain-time ordering;
- same-domain lifecycle age;
- same-domain reserve/state selection.

A decision with available events derives or receives an explicit `chain_as_of`. In the
Radar/Indexed Kernel streaming path the anchor is monotone per token:

```text
chain_as_of(t) = max(chain_time of same-token trades observed locally by t)
```

A late event may be inserted into older chain time, but it never moves the anchor backward
and never becomes fresh flow merely because it arrived now.

## Forbidden operations

Until an explicit clock-calibration method is implemented and validated:

```text
observed_at >= chain_time                       # NOT a validity invariant
observed_at - chain_time == delivery latency    # NOT valid
local_as_of - window == chain cutoff            # NOT valid
local_as_of - market_started_at == market age   # NOT valid
```

A chain timestamp ahead of the local receive second is valid evidence and is surfaced as a
data-quality diagnostic rather than rejected.

## Compatibility behavior

Legacy fields named `median_observation_lag_seconds` and
`max_observation_lag_seconds` remain on some frozen/public structures for compatibility,
but are `None` under the uncalibrated dual-clock contract and carry explicit missingness.

## Modules aligned

The correction was applied across the causal Market-First path, including:

- Carbon protocol and matched-unit adapters;
- PumpSwap pool identity availability;
- protocol facts;
- matched-unit flow aggregation;
- Opportunity Snapshot Core;
- Market Intelligence baseline/composition;
- market observation store;
- episode enrichment;
- Market Opportunity Radar;
- Indexed Market Signal Kernel;
- bounded/indexed benchmark oracles.

## Validation

On branch `spike/commodity-signal-plane-v0`, commit
`9d70eb7bb1a77df3494f0ff339fb097dba386939` locked the monotone chain-anchor regression
test. GitHub Actions `Market signal kernel production` completed successfully with:

```text
focused/differential tests: 25/25 PASS
full unit suite:            1215/1215 PASS
```

Subsequent research-only WSS tooling changes did not alter production clock semantics.

## Scientific consequence

The original 510 invalid rows must be re-audited from the same immutable Carbon/manifest
artifacts under this corrected contract. No events are silently reclassified by changing
a threshold or denominator. The expected result is that cross-clock skew ceases to be an
`INVALID_EVENT`; each PumpSwap trade still independently requires causal pool identity.

Systems PASS, data availability, signature recall, matched-unit context coverage and
economic edge remain separate verdicts.