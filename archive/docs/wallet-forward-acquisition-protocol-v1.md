# Wallet Forward Acquisition Protocol v1

## Status

**PRE-REGISTERED RESEARCH PROTOCOL / READ ONLY.**

This protocol exists to increase the chance of obtaining a non-empty causal Wallet Forward sample without selecting wallets after seeing forward outcomes. It does not use PnL, win rate, return, profit factor, published leaderboard performance, or any post-T0 result.

The immediate objective is narrower than economic validation:

> obtain at least one genuinely forward-observed BUY that can pass through enrollment and the event-scoped Jupiter quote path under a frozen cohort.

A non-empty sample is not evidence of edge.

## Frozen acquisition universe

The candidate universe is the 13-address public research cohort already recorded in:

`wallets/research-cohort-public-2026-08-31.txt`

No address may be added to the next evaluation cohort because it becomes active after T0. New addresses can be researched for a later protocol version, but not injected into an already frozen evaluation window.

## Separation of acquisition and evaluation

The workflow has two distinct phases.

### 1. Acquisition / eligibility phase

All measurements occur before T0. They may be used to decide which wallets are technically suitable to monitor in the next run.

Allowed evidence:

- our own Solana RPC / SQLite successful swaps;
- latest successful swap time;
- recent swap counts and active-day recurrence;
- local strategy fingerprint fields;
- sequence/roundtrip coverage;
- complete-like sizing-cycle count;
- observed transaction intensity;
- DEX/behavioral diversity.

Forbidden evidence:

- any transaction occurring after T0;
- forward returns from the evaluation window;
- PnL, win rate, profit factor or future token performance;
- choosing a wallet because it traded after the run started;
- replacing a quiet wallet mid-run with a newly active wallet.

### 2. Evaluation phase

The selected addresses, T0, Wallet Forward manifest, polling interval, enrollment window, follow-up window, quote delays and copy notional are frozen before outcomes are observed.

The evaluation run never modifies its cohort in response to activity or profitability.

## Standardized pre-T0 refresh

Before selecting the next cohort, run the same shallow refresh for all 13 candidates:

```powershell
python wallet_strategy_lab.py `
  --file wallets/research-cohort-public-2026-08-31.txt `
  --sync-onchain `
  --pages 3 `
  --json
```

The same page depth is used for every candidate. Do not deepen only a wallet that looks interesting before the cohort is frozen.

The output must be saved as acquisition evidence before the next Wallet Forward run.

## Eligibility rule v1

A wallet is eligible for the next forward cohort only from pre-T0 data and should satisfy all of the following where the local sample supports the metric:

1. at least 20 successful supported swaps in the local sample;
2. roundtrip share >= 50%;
3. at least 3 complete-like sizing cycles;
4. observed activity is not `sparse`;
5. observed activity is not above the project's current copyability ceiling of roughly 20 swaps/day;
6. evidence of recurring recent activity rather than a single isolated historical burst;
7. no critical sequence-quality flag that makes the behavioral sample uninterpretable.

Recent-activity evidence must be evaluated before T0. The preferred v1 definition is:

- latest successful swap no more than 48 hours before cohort freeze; and
- at least 2 distinct active UTC days in the previous 7 days.

This is intentionally recurrence-based rather than "who is trading right now".

If local backfill is too shallow to support these exact recency fields for a candidate, mark the criterion as insufficient evidence rather than guessing.

## Cohort size and deterministic selection

Target size for the next run: **up to 5 wallets**.

Reason: three wallets produced repeated zero-sample windows, while monitoring the full 13-address universe at a 10-second sequential RPC cadence would unnecessarily increase observation lag and provider load.

If more than five wallets are eligible, selection is deterministic and non-economic:

1. rank by number of distinct active UTC days in the previous 7 days, descending;
2. then by successful swaps in the previous 72 hours, descending;
3. then by age of latest successful swap, ascending;
4. use wallet address lexicographically only as a final tie-break;
5. prefer one wallet per fingerprint signature before filling remaining slots by the same rank, to reduce behavioral concentration.

No profitability field participates in this ordering.

If fewer than three wallets satisfy the rule, do not start the long evaluation run. Treat that as an acquisition-universe problem and expand/research the universe under a future pre-registered protocol version.

## Freeze artifact

Before T0, preserve:

- acquisition timestamp;
- source candidate file;
- exact selected addresses;
- pre-T0 fingerprint/recency metrics used by the rule;
- reasons for inclusion/exclusion;
- Git commit SHA;
- SQLite database identity/path used for selection.

The selected wallet file must be treated as immutable for that evaluation run.

## Next evaluation run

Once a cohort of 3-5 wallets is frozen, keep the existing enrollment-aware protocol:

- polling: 10 seconds;
- RPC commitment: `confirmed`;
- enrollment: 4 hours;
- follow-up: 6 hours;
- Jupiter quotes enabled;
- delays: 0 / 15 / 30 / 60 / 120 seconds;
- copy notional: USDC 25;
- quote-only unless a public taker is explicitly configured;
- RESEARCH / READ ONLY.

The primary gate for this next run is structural, not economic:

- run reaches `COMPLETED`;
- enrollment cutoff is frozen;
- >=1 enrolled forward BUY exists;
- the BUY is linked to the expected event-scoped quote attempts;
- RPC degradation, if any, remains auditable;
- causal readiness is classified by the existing readiness/post-run tooling.

Do not interpret profitability from a tiny non-zero sample.

## Pre-registered handling of n=0

A zero-BUY run is a valid `NO_CAUSAL_SAMPLE` result and must remain in the record.

Do not change wallets during or immediately after the window because another wallet happened to trade.

For the first v1 cohort, allow **one additional independent 10-hour window with the exact same frozen cohort and parameters** if the first window produces zero enrolled BUYs.

If both windows produce zero enrolled BUYs, stop and redesign the acquisition universe/protocol before spending another long run. Do not keep repeating until a trade appears.

This prevents optional sample hunting while still distinguishing one quiet window from a structurally inactive cohort.

## Interpretation guardrails

This protocol is only intended to solve sample acquisition and technical causal-path validation.

It does not prove:

- that selected wallets are profitable;
- that their future trades have edge;
- that copy trading them is executable at observed quotes;
- that a larger cohort is better economically;
- that convergence predicts returns;
- that quote-only Jupiter observations equal fills.

Economic claims remain blocked until sufficient forward sample, causal replay, execution stress and shadow validation exist.
