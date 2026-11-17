# Wallet Forward v2 Run 1 — Quantity-Aware Economic Replay (2026-09-02)

## Status

**ACCOUNTING FIX VALIDATED / DESCRIPTIVE ONLY / RESEARCH READ ONLY.**

This document records the re-evaluation of the completed run
`wallet-forward-1788360461-8a3986f9` after replacing the legacy economic replay shortcut
`one SELL = one FIFO BUY lot` with conservative quantity-aware source-inventory accounting.

It does **not** establish economic edge, copyability, fill quality, shadow readiness or live
readiness.

## Provenance

- source run: `wallet-forward-1788360461-8a3986f9`
- run status: `COMPLETED`
- frozen enrollment BUYs: 4
- full-run actions: 15
- follow-up-only BUYs: 5
- quote mode: `proxy`
- replay notional: USDC 25 per enrolled BUY
- replay cost assumption: 100 bps slippage per side (existing `EconomicReplayConfig` default)
- quantity-aware implementation commit: `a48c4ab3c8c19a71405323e4a22bd56bc7b73e88`
- CI on implementation branch: 443 tests passed + `compileall`
- CI on `feat/exit-engine-v1`: 443 tests passed + `compileall`

The completed run itself previously passed:

- post-run audit: 10/10 steps, zero non-zero exits;
- causal integrity: `CAUSAL_BOUNDARY_CLEAN`;
- BUY quote completeness: 45/45 expected probes, 45 success, zero missing/failure;
- finality: 15/15 finalized success;
- replay data gate: `CAUSAL_REPLAY_SAMPLE_READY`.

## Why the accounting fix was required

The current forward observation schema already persists exact source-wallet quantity evidence:

- `token_delta_raw`;
- `token_balance_before_raw`;
- `token_balance_after_raw`;
- `token_decimals`;
- `token_quantity_flags`;
- `source_reduction_fraction`.

However, the previous replay still treated each BUY as one event lot and each SELL as closing only
one FIFO lot. This became observably wrong in the real forward run.

For wallet `3tc4BVAdzjr1JpeZu6NAjLHyp4kK3iic7TexMBYGJ4Xk` and token
`5TVs7xhYKUoyLtKG4hB15WNa6LB9jnJkca2txcDSpump`, the enrolled source inventory evolved as:

```text
BUY obs 33: 0 -> 4,904,251,429,769 raw
BUY obs 34: 4,904,251,429,769 -> 7,696,907,006,006 raw
BUY obs 35: 7,696,907,006,006 -> 10,185,053,986,291 raw
SELL obs 41: 10,185,053,986,291 -> 0 raw
source_reduction_fraction = 1.0
```

The SELL therefore liquidated the entire observed source position built by the three enrolled BUYs.
Closing only the first FIFO BUY was not an economically faithful representation of the observed
inventory path.

## New conservative semantics

The replay now uses quantity-aware accounting for wallet/token clusters with quantity metadata.

- A complete observed source reduction can close all eligible, trackable copy lots for the same
  wallet/token.
- A partial source reduction is mirrored proportionally only when the pre-SELL source inventory is
  fully attributable to trackable copy inventory.
- Follow-up-only BUYs never become economic copy entries, but their observed quantities remain in
  the inventory timeline so later SELLs cannot be falsely attributed to enrolled lots.
- Pre-existing/non-copy inventory makes partial allocation ambiguous; affected copy lots are
  censored instead of receiving invented exits.
- Missing/inconsistent quantity metadata remains explicit and conservative.
- Event-scoped causal quotes and proxy/executable separation are unchanged.
- Legacy runs without quantity metadata retain the old FIFO path for auditability rather than being
  silently rewritten.

## Before / after — run 1

### Legacy event-lot replay

| Delay after detection | Closed | Open | Censored | Mean net return |
|---:|---:|---:|---:|---:|
| +0s | 1 | 0 | 3 | +0.52% |
| +15s | 1 | 0 | 3 | +1.36% |
| +30s | 0 | 0 | 4 | n/a |
| +60s | 1 | 1 | 2 | +2.97% |
| +120s | 0 | 1 | 3 | n/a |

Those positive `n=1` values were accounting artifacts and must not be treated as evidence of
strategy performance.

### Quantity-aware replay

| Delay after detection | Closed | Open | Censored | Mean net | Median net | Win rate | Profit factor |
|---:|---:|---:|---:|---:|---:|---:|---:|
| +0s | 3 | 0 | 1 | -28.76% | -40.40% | 33.3% | 0.0060 |
| +15s | 3 | 0 | 1 | -30.37% | -45.76% | 33.3% | 0.0148 |
| +30s | 0 | 0 | 4 | n/a | n/a | n/a | n/a |
| +60s | 3 | 0 | 1 | -25.36% | -33.61% | 33.3% | 0.0376 |
| +120s | 0 | 0 | 4 | n/a | n/a | n/a | n/a |

For the three closed `5TVs...pump` lots, the individual net returns are:

- +0s: `+0.52%`, `-40.40%`, `-46.41%`;
- +15s: `+1.36%`, `-45.76%`, `-46.71%`;
- +60s: `+2.97%`, `-45.43%`, `-33.61%`.

At +30s and +120s there is no eligible causal SELL quote inside the replay wait rules, so no exit is
invented and the lots remain censored. The enrolled `J8PS...pump` position also has no source SELL
inside the completed run and remains right-censored.

## Interpretation

The accounting correction changes the descriptive result materially. This is evidence that the old
`n=1` positive replay was not a reliable economic summary and that observed source quantities are
required before interpreting repeated BUYs and aggregate exits.

The new negative values are **also not a strategy verdict**. The sample contains only four enrolled
BUYs, three of them are the same wallet/token cluster, quotes are proxy-only, and the data remain
highly dependent. The result is useful as a validation of accounting correctness and as a warning
against event-row pseudo-sample inflation, not as an estimate of future expected return.

## Gate decision

**QUANTITY-AWARE ACCOUNTING GATE = PASSED.**

The project may now use the corrected replay for descriptive cost/latency research. Economic
promotion remains blocked.

Before another long forward collection or any shadow promotion, keep the next decision focused on
sample formation and execution realism:

1. preserve the frozen run as evidence;
2. do not retune wallets/delays based on these returns;
3. keep proxy vs executable/landing/fill claims separate;
4. accumulate a larger independent enrolled sample before strategy inference;
5. maintain right-censoring, dependence and missingness explicitly;
6. shadow/live remain blocked.
