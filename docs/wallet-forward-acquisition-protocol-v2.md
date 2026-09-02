# Wallet Forward Acquisition Protocol v2

## Status

**PRE-REGISTERED RESEARCH PROTOCOL / READ ONLY.**

Protocol v1 was executed on 2026-09-02 and correctly blocked the long Wallet Forward run because only 2 of 13 candidate wallets satisfied the frozen eligibility rule. This v2 protocol is registered before any v2 forward-evaluation T0.

The v1 result is preserved. v2 does not reinterpret or overwrite it.

## Why v2 exists

The v1 acquisition audit showed that the main blocker was not simply absence of transactions. Several candidates had recent activity but insufficient local BUY/SELL sequence coverage for the frozen copyability rule.

Examples from the v1 audit:

- `7mPti...csxTH`: eligible;
- `3tc4...J4Xk`: eligible;
- `Gf9X...5Pbd`: active and otherwise informative, but roundtrip coverage remained below the frozen 50% threshold;
- `DKgv...yciK`: recent activity, but low roundtrip coverage and insufficient complete-like sizing;
- multiple candidates produced too few supported swaps under the shallow local history.

The response is **not** to lower the threshold after seeing the result.

v2 changes acquisition coverage only:

1. expand the pre-T0 candidate universe;
2. deepen the same RPC backfill uniformly for every candidate;
3. keep the v1 eligibility thresholds and deterministic selection rule unchanged.

## Frozen candidate universe

The executable v2 universe is:

`wallets/research-cohort-public-v2-2026-09-02.txt`

It contains:

- all 13 addresses from the v1 universe; and
- 14 additional public Solana addresses recorded before v2 T0.

The additional addresses were sourced on 2026-09-02 from the public SmartMoneyDEX categories/leaderboard pages. External labels, published PnL, win rate and ranking are candidate-sourcing hints only. None of those economic fields is imported into the eligibility calculation.

The source snapshot was chosen before any v2 forward outcomes existed. No wallet may be added because it becomes active after v2 T0.

## Uniform pre-T0 refresh

Every address in the 27-wallet universe receives the same maximum backfill depth:

- `--sync-onchain`
- `--pages 6`

This replaces v1's 3-page acquisition refresh.

The deeper uniform history is intended to reduce left-censoring of BUY/SELL sequences. It is not permission to selectively deepen only wallets that nearly pass.

RPC failures remain auditable. A wallet whose standardized pre-T0 refresh is partial or failed is excluded rather than guessed.

## Eligibility rule

The v1 rule is retained without relaxation. A wallet must satisfy all applicable criteria from pre-T0 RPC/SQLite evidence:

1. at least 20 successful supported swaps;
2. roundtrip share >= 50%;
3. at least 3 complete-like sizing cycles;
4. activity bucket is not `sparse`;
5. observed intensity does not exceed the current acquisition ceiling of roughly 20 swaps/day;
6. latest successful swap no more than 48 hours before freeze;
7. at least 2 distinct active UTC days in the previous 7 days;
8. no critical sequence-quality blocker such as `sequence_coverage_low`;
9. standardized pre-T0 sync must complete successfully.

No PnL, return, win rate, profit factor or post-T0 token performance participates.

## Cohort selection

Target: **3 to 5 wallets**.

If more than 5 wallets are eligible, preserve the existing deterministic non-economic ordering:

1. distinct active UTC days in the previous 7 days, descending;
2. successful swaps in the previous 72 hours, descending;
3. latest successful swap age, ascending;
4. wallet address lexicographically as final tie-break;
5. prefer fingerprint diversity before filling remaining slots.

If fewer than 3 wallets pass v2, the long forward run remains blocked. Do not reduce thresholds or inject newly active wallets.

## Freeze artifacts

The v2 freeze must persist:

- protocol version `wallet_forward_acquisition_v2`;
- cutoff timestamp;
- Git HEAD;
- SQLite path;
- candidate file;
- uniform page depth;
- all candidate pre-T0 metrics;
- inclusion/exclusion reasons;
- exact selected addresses.

Expected outputs:

- `wallets/forward-cohort-v2.txt`
- `wallet-forward-acquisition-v2.json`
- optional console capture `wallet-forward-acquisition-v2.txt`

The selected wallet file becomes immutable for the associated forward evaluation.

## Command

After syncing the repository and explicitly selecting the real research database:

```powershell
$env:DATABASE_PATH = "data\copytrader.db"

python wallet_forward_cohort_freeze.py `
  --protocol-version wallet_forward_acquisition_v2 `
  --file wallets/research-cohort-public-v2-2026-09-02.txt `
  --sync-onchain `
  --pages 6 `
  --max-wallets 5 `
  --min-wallets 3 `
  --output-wallets wallets/forward-cohort-v2.txt `
  --output-json wallet-forward-acquisition-v2.json
```

## Forward gate after a successful freeze

Only if 3-5 wallets are frozen should the existing enrollment-aware Wallet Forward experiment run again.

The evaluation parameters remain unchanged:

- polling 10 seconds;
- RPC commitment `confirmed`;
- enrollment 4 hours;
- follow-up 6 hours;
- Jupiter quote delays 0 / 15 / 30 / 60 / 120 seconds;
- copy notional USDC 25;
- RESEARCH / READ ONLY.

The immediate success criterion remains structural: obtain at least one truly forward enrolled BUY linked to the causal quote path in a `COMPLETED` run. A small non-zero sample is not evidence of economic edge.

## n=0 handling

If the first v2 forward window produces zero enrolled BUYs, allow one additional independent 10-hour window with the **same frozen v2 cohort and parameters**.

If both are zero, stop. Do not continue until a trade appears.

## Guardrail

Protocol v2 changes acquisition breadth and uniform local-history depth only. It does not modify strategy logic, Wave signals, exit policies, forward outcomes, or live execution.
