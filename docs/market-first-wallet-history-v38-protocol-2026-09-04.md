# Market-First Wallet History v38 — Strict Pre-T0 Protocol

Date: 2026-09-04

Mode: **PAPER / RESEARCH / READ ONLY**

## Purpose

Build wallet intelligence for the market-first Opportunity Engine without reusing contaminated
wallet-first labels and without pretending that a market opportunity outcome is the wallet's own
realized PnL.

The causal order remains:

```text
market movement
-> opportunity episode T0
-> wallets causally present
-> only prior evidence already resolved before this T0
-> execution / hazard / flow / wallet bundle
-> decision_as_of
-> future outcome
```

Wallet identity never admits an episode and never becomes an acquisition allowlist.

## Two different concepts must remain separate

### Wallet-owned historical outcome

An actual prior outcome attributable to the wallet itself, with defensible entry/exit clocks and
coverage. This is represented by the legacy-compatible `HistoricalWalletOutcome` contract.

No current official market-first loader populates this field because the project does not yet have a
complete causal reconstruction of each wallet's own realized entry/exit PnL.

### Market-first wallet/opportunity association

A wallet was causally observed participating in a prior market opportunity and that prior opportunity
later obtained an official executable quote-to-quote forward label.

This is represented by `HistoricalWalletOpportunityAssociation`.

Its return means:

```text
prior opportunity executable BUY quote
-> exact predeclared forward horizon
-> executable SELL quote
-> quote-to-quote opportunity return
```

It does **not** mean:

- the wallet bought at our entry quote;
- the wallet sold at our forward quote;
- the wallet held for the selected horizon;
- the wallet realized that PnL;
- our transaction landed or filled on-chain.

The field is therefore named `executable_quote_return_pct`.

## Allowed official sources

`src/opportunity_wallet_market_history.py` may use only persisted market-first evidence:

1. `market_opportunity_episodes` with frozen `decision_as_of`;
2. Jupiter entry provider attempt `jupiter_swap_v2_order / entry_executable_buy_v1`;
3. entry attempt status `AVAILABLE` with `assembled_transaction_present=True`;
4. persisted executable BUY quote belonging to the prior token and observed no later than the prior
   `decision_as_of`;
5. `opportunity_forward_outcomes` for one exact predeclared horizon;
6. forward status `AVAILABLE` with an executable SELL quote;
7. persisted market observations to recover wallet participation in the same 30-second causal window
   used by Opportunity Wallet Intelligence.

## Sources explicitly forbidden as official labels

The loader does not read or adapt:

- old wallet-first Discovery/Copyability scores;
- Solana Tracker historical PnL leaderboards;
- exploratory v2/v3 wallet PnL results;
- legacy `wallet_forward_*` research outputs;
- partial on-chain wallet research that does not establish complete realized PnL;
- later candles or synthetic/backfilled prices.

Those artifacts remain research history only.

## Strict pre-T0 rule

For current episode T0:

```text
current_t0 = current_episode.first_trigger_observed_at
```

A prior association is usable only if:

```text
prior decision_as_of < current_t0
prior forward outcome observed_at < current_t0
prior exit quote observed_at < current_t0
```

Equality is excluded. Current clocks are second-granularity in these stores, so evidence observed in
the same second as T0 has ambiguous ordering and must not be promoted to pre-T0 knowledge.

`history_cutoff` may be earlier than T0 for conservative replay, but it may never be moved after T0.

The enrichment bundle independently enforces the same strict rule. This prevents a future caller from
bypassing the official loader and manually injecting post-T0 association evidence.

## Horizon rule — no cherry-pick / no silent fallback

Official supported horizons remain:

- 300 seconds;
- 900 seconds;
- 3600 seconds.

One wallet-history snapshot may contain associations for only **one** predeclared horizon.

If +15m is requested and only +5m is AVAILABLE, the loader returns missing history for +15m. It does
not silently choose +5m, the best historical return, or whichever label happens to exist.

The project has not promoted one horizon as the final wallet-history feature merely because old
exploratory results looked better at that horizon. Any future choice must be predeclared for the
experiment or compared as separate feature variants.

## Missingness semantics

Missing history is not a loss and not strategy failure.

Examples of explicit exclusions:

- entry executable quote unavailable;
- entry provider completion after the prior decision clock;
- assembled transaction absent;
- forward outcome missing for the requested horizon;
- forward outcome not AVAILABLE;
- outcome not known strictly pre-T0;
- exit quote missing/invalid/not pre-T0;
- current wallet not present in the prior opportunity.

If no valid official history exists:

```text
no_valid_market_first_history_sample
```

is the correct evidence state.

## Current expected state

Funded Jupiter executable assembly is still `BLOCKED_BY_FUNDING`, so no official market-first
`decision_as_of` / executable forward cohort has been released yet.

Therefore the current local database is expected to produce zero valid official market-first wallet
associations. That is **expected/inconclusive**, not a failed wallet signal.

## Files

- `src/opportunity_wallet_intelligence.py`
- `src/opportunity_wallet_market_history.py`
- `src/opportunity_episode_enrichment.py`
- `wallet_market_history_diagnostic_v38.py`
- `tests/test_opportunity_wallet_market_history.py`
- `tests/test_opportunity_wallet_history_enrichment_guard.py`

## Diagnostic

The diagnostic is SQLite-only and read-only. It performs no RPC/provider calls and no writes.

Example against the v37 run:

```powershell
python wallet_market_history_diagnostic_v38.py --run-key unified-market-onchain-hazard-smoke-20260904-37 --horizon-seconds 300 --max-episodes 12
```

Expected current classification, while no official funded market-first history exists:

```text
INCONCLUSIVE_NO_OFFICIAL_MARKET_FIRST_HISTORY_SAMPLE
```

A future `PASS_HAS_STRICT_PRE_T0_MARKET_FIRST_HISTORY` only means valid causal association history is
present. It does not prove predictive value or economic edge.

## Promotion rule

Wallet association evidence becomes a useful strategy feature only after enough official forward
history exists to test incremental value with time separation and activity/placebo controls.

Required future question:

> after controlling for the market movement and flow that caused us to inspect this token, does prior
> market-first history of the wallets currently present add out-of-sample predictive information?

Until that is demonstrated, wallet history is descriptive evidence, not a buy rule.
