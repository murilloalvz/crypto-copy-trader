# Wallet Forward Acquisition v2 — Result (2026-09-02)

## Status

**COHORT FREEZE PASSED / RESEARCH READ ONLY.**

The v2 pre-T0 acquisition protocol produced a valid frozen cohort of 3 wallets without relaxing the preregistered eligibility thresholds.

## Provenance

- protocol: `wallet_forward_acquisition_v2`
- acquisition cutoff: `1788359597`
- selection git head: `46fe09aac9a92107d803ce631e1f9c906b9bd82f`
- database: `data\copytrader.db`
- candidate universe: `wallets\research-cohort-public-v2-2026-09-02.txt`
- candidate count: 27
- uniform backfill depth: up to 6 pages
- target cohort size: 3-5
- selected count: 3

## Frozen cohort

1. `7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH`
2. `3tc4BVAdzjr1JpeZu6NAjLHyp4kK3iic7TexMBYGJ4Xk`
3. `2RssnB7hcrnBEx55hXMKT1E7gN27g9ecQFbbCc5Zjajq`

Do not replace or add wallets based on post-cutoff activity.

## Eligibility snapshot

### 7mPtiLMhn9…

- successful supported swaps: 102
- active UTC days in previous 7d: 7
- swaps in previous 72h: 9
- latest successful swap age: ~2.8h
- observed rate: 1.0/day
- roundtrip share: 76.9%
- complete-like sizing cycles: 25
- fingerprint: `one_day|mixed_exit|occasional_reentry|moderate`

### 3tc4BVAdzj…

- successful supported swaps: 163
- active UTC days in previous 7d: 5
- swaps in previous 72h: 141
- latest successful swap age: ~14.2h
- observed rate: 20.0/day
- roundtrip share: 75.0%
- complete-like sizing cycles: 13
- fingerprint: `ultra_short|mixed_exit|rare_reentry|high_frequency`

This wallet sits exactly at the current copyability ceiling and remained eligible under the frozen rule. The rule excludes activity above the ceiling, not equal to it.

### 2RssnB7hcr…

- successful supported swaps: 31
- active UTC days in previous 7d: 3
- swaps in previous 72h: 9
- latest successful swap age: ~14.3h
- observed rate: 2.0/day
- roundtrip share: 91.7%
- complete-like sizing cycles: 11
- fingerprint: `ultra_short|single_exit_dominant|rare_reentry|moderate`

## Notable exclusions

The thresholds were not relaxed after seeing the result.

- `Gf9XgdmvNH…`: 120 swaps, 7 active days and 24 complete-like cycles, but 46.8% roundtrip plus low sequence coverage → excluded.
- `DKgvpfttzm…`: 74 swaps and recent activity, but 44.4% roundtrip plus low sequence coverage → excluded.
- `pndujwi7Be…`: 56 swaps, 90% roundtrip and 7 complete-like cycles, but 28/day → excluded for activity above the copyability ceiling.
- `4UwK5AE6Dj…`: 50% roundtrip but only 10 swaps, 2 complete-like cycles and 1 active day → excluded.

## RPC acquisition quality

All 27 candidates completed the acquisition refresh with `sync=ok`. The collection used both configured public RPC endpoints where fallback was needed. No candidate was selected through a partial or failed pre-T0 sync.

## Decision

**ACQUISITION GATE v2 = PASSED.**

The next forward evaluation may use only the frozen 3-wallet cohort above with the existing enrollment-aware protocol:

- polling: 10s
- RPC commitment: `confirmed`
- enrollment: 4h
- follow-up: 6h
- Jupiter quote snapshots: enabled
- quote delays: 0 / 15 / 30 / 60 / 120s
- copy notional: USDC 25
- quote-only unless taker is explicitly configured
- RESEARCH / READ ONLY

Primary objective of the next run remains structural causal-path validation, not profitability inference:

1. run reaches `COMPLETED`;
2. enrollment cutoff freezes correctly;
3. at least one enrolled forward BUY is observed;
4. the BUY is linked to the expected event-scoped Jupiter quote attempts;
5. RPC degradation remains auditable;
6. no economic conclusion is drawn from a tiny sample.

If the next full window produces zero enrolled BUYs, one additional independent 10h window is allowed with the exact same cohort and parameters. If both are zero, stop and redesign the acquisition protocol instead of repeatedly sampling until activity appears.
