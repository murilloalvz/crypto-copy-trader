# Public Wallet Candidate Cohort — 2026-08-31

## Status

RESEARCH INPUT ONLY. This file records why a first broader wallet cohort was assembled. It is not a profitability ranking and must not be treated as validated copyability evidence.

The executable address list is in `wallets/research-cohort-public-2026-08-31.txt`.

## Why this cohort exists

The Solana Tracker Data API quota is exhausted, while Wallet Strategy Lab and forward RPC collection can continue without that Data API. Instead of waiting for the quota reset, we can study a transparent public seed cohort and validate the wallets ourselves from Solana RPC/SQLite.

The cohort intentionally mixes different apparent activity profiles. The purpose is to discover recurring behavioral archetypes, not to select the biggest published PnL.

## Provenance

Addresses were collected from public web pages that publish Solana trader leaderboards or public wallet research. On 2026-08-31, SmartMoneyDEX publicly listed several of the addresses in its Solana leaderboard, including `3tc4...J4Xk`, `DKgv...yciK`, `636N...axGV`, `7SDs...BseHS`, `9jyq...AVVz`, `2tga...Aoxw`, and `2Rss...Zjajq`. Independent public explorer/profile pages were found for some addresses, including Solscan/CoinStats for `3tc4...J4Xk`, Solscan/CoinStats/OKX for `DKgv...yciK`, and Solscan/CoinStats for `9jyq...AVVz`.

A public wallet-research thread indexed on the web also names `2Rss...Zjajq`, `8fSn...EyLJ`, `5wT...bsS5`, `DNfu...eBHm`, `B8Cd...i4dd`, and `Gf9X...5Pbd` as wallets worth tracking historically. Those historical performance claims are NOT imported into our model and are not assumed current.

`7mPti...csxTH` remains in the cohort as our existing first case study/control.

## Reliability rule

External labels such as "whale", "insider", "smart money", reported PnL, win rate, or best trade are treated only as sourcing hints. They are not ground truth. A wallet can have stale performance, transfers, multiple accounts, bot activity, incomplete public accounting, or a strategy that cannot survive our detection delay.

For this project, evidence begins only after our own pipeline observes:

1. supported DEX swaps from RPC;
2. chronological sequence coverage;
3. enough clean roundtrips/sizing cycles for a fingerprint;
4. forward observation latency;
5. entry/holding/exit context where price coverage is adequate;
6. eventually performance reconstructed without leakage and stressed for execution.

## First run

After pulling the branch:

```powershell
python wallet_strategy_lab.py --file wallets/research-cohort-public-2026-08-31.txt --sync-onchain --pages 3
```

This is intentionally a shallow first pass. Do not immediately increase pages for every wallet. First inspect which wallets produce useful supported swaps and sequence coverage; deeper backfill should be spent only on informative cases.

Then compare all wallets that now have enough local data:

```powershell
python wallet_strategy_compare.py --all-local --min-swaps 20
```

For forward latency research, select a smaller diverse subset after the fingerprints are visible and run the existing wallet forward watcher rather than monitoring all candidates blindly.

## Selection policy for the next subset

A candidate is interesting for deeper research when it contributes information, not merely because it looks profitable externally. Prefer wallets that satisfy several of these:

- enough supported swaps for a non-empty fingerprint;
- chronological roundtrip share around or above 50%;
- at least three complete-like sizing cycles;
- behavior distinct from wallets already studied;
- repeated signature shared by another evidence-ready wallet;
- activity recent enough for forward monitoring;
- manageable transaction frequency for our RPC polling budget.

Very high-frequency wallets should not be automatically rejected. They can define useful archetypes, but may later fail copyability because latency/slippage destroys the edge.

## Guardrail

No result from this cohort modifies `wave_v3_volume_integrity`, exit policies, or live behavior. Cross-wallet recurrence is a hypothesis generator only. Any strategy derived from it must pass causal replay, execution stress, and shadow validation first.
