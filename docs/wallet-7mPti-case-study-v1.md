# Wallet case study v1 — `7mPti...csxTH`

Status: **RESEARCH / DESCRIPTIVE ONLY**. This document records the first wallet whose independently observed entry, holding and exit-sequence evidence started to form a coherent strategy hypothesis. It does **not** authorize copy trading, live execution, changes to `wave_v3_volume_integrity`, or promotion of any exit rule.

## Why this wallet remains interesting

The earlier Solana Tracker profile was a near-miss for direct copyability, but economically robust enough to justify deeper research: 19 profiled positions, positive realized PnL, positive median ROI, limited dependence on the best winner, and only the conservative liquid-capital gate below threshold. When Solana Tracker Data API credits were exhausted, research continued through local Solana RPC data plus conservative GeckoTerminal market-price proxies.

## On-chain execution sample

Observed local sample:

- 61 successful swaps across 25 tokens over 63.91 days;
- 26 buys / 35 sells;
- 17/25 chronological buy→sell roundtrips (68.0%);
- 5 buy-only tokens and 3 sell-only tokens;
- no observed sell-before-first-buy case in this window;
- median 2 actions per token;
- scale-in in 5.9% of observed roundtrips;
- multiple sells in 35.3% of roundtrips;
- multiple sells without re-entry in 23.5%;
- median same-token sell gap 1.8 days, with 53.3% of sell gaps >=1 hour;
- re-entry after first sell in 11.8%, with median re-entry gap 5.4 days;
- median first exit after first observed buy: 1.2 days;
- median buy→last-observed-sell span: 2.6 days;
- median global swap gap: 13.7 hours.

DEX mix in the local sample: PumpSwap 25, Jupiter v6 18, Meteora DLMM 7, Raydium CLMM 4, Pump.fun 3, Orca Whirlpool 2, Raydium CPMM 2.

### Execution interpretation

The observed behavior is inconsistent with a pure sniper/scalper archetype. The cleanest current description is: **usually one initial buy, little scale-in, multi-hour/day holding, occasional staged selling, and relatively rare re-entry**. Multiple sells are separated widely enough that at least part of the pattern is unlikely to be explained only by transaction fragmentation.

## Entry-context research

A time-spread sample of 12 first observed buys produced 11 usable price contexts.

Descriptive medians before the observed buy:

- pre-5m: +0.5%;
- pre-15m: +1.3%;
- pre-60m: -3.5%;
- position inside prior 60m range: 25.4%;
- prior 60m amplitude: 13.3%.

Other entry observations:

- pre-15m >= +5%: 25.0%;
- pre-15m <= -5%: 0.0%;
- entry near the top of the prior 60m range: 18.2%;
- heuristic labels: 6 `mixed_neutral`, 3 `insufficient_price_context`, 2 `momentum_breakout_like`.

Median market movement after the observed buy was 0.0% at +5m, -3.6% at +15m and -3.8% at +60m.

### Entry interpretation

There is no evidence yet for a single simple rule such as "buy strong momentum" or "buy a sharp dip". The current hypothesis is weaker and more defensible: **entries often occur in the lower part of the recent hourly range without requiring a sharp immediate selloff or explosive short-term momentum**. Price context alone probably does not explain token selection.

The two strongest momentum-like cases had opposite +60m outcomes (+14.3% and -56.2%), which is direct evidence against promoting a naive momentum-copy rule from this sample.

## Multi-day holding-context research

The same 12-entry sampling design produced 11 usable multi-day observations.

Median checkpoint returns:

- +6h: +2.3%;
- +24h: +2.2%;
- +48h: -14.9%;
- +72h: -10.0%.

Path statistics:

- median 24h MFE: +26.2%;
- median 24h MAE: -16.7%;
- median 72h MFE: +31.9%;
- median 72h MAE: -29.4%;
- positive at +24h: 55.6% of entries with that horizon available;
- positive at +72h: 44.4%;
- <= -30% at +24h: 22.2%.

Several tokens exhibited very large favorable excursions followed by substantial giveback. Examples include observed 72h MFE of +184.2% and +423.0%, while another token never recovered the proxy entry price and reached an 86% adverse excursion. Hourly MFE is not guaranteed executable liquidity and can include short-lived wicks.

### Holding interpretation

A passive fixed 48–72h hold does not look attractive in this small sample: checkpoint medians deteriorate after the first day. At the same time, favorable excursions inside the holding window are materially larger than the fixed +24h endpoint. Combined with the wallet's median first observed exit near 1.2 days, this makes **exit timing / staged realization** a more promising research hypothesis than "perfect entry timing".

## Current strategy hypothesis — not a trading rule

The best-fitting descriptive story today is:

`speculative token selection → mostly single entry → tolerate substantial volatility → wait for expansion → begin realizing around the first day when opportunity appears → sometimes distribute remaining sales over hours/days → rare later re-entry`

This is a hypothesis assembled from independent on-chain sequence, entry-context and holding-path evidence. It still lacks exact fill prices, historical liquidity/market cap, reliable token-age/launch context, position sizing, and full realized PnL reconstruction.

## Next experiment: align actual observed sells with the price path

The next high-information test is `wallet_exit_context.py`. It extracts the first clean observed cycle per token, separates later re-entry instead of merging cycles, prices the first and last observed sells with minute candles, and reconstructs a conservative hourly path before the first sell.

It will measure:

- proxy return at the first observed sell;
- proxy return at the last sell of the first cycle;
- first/last sell timing;
- MFE/MAE before the first sell using only completed hourly candles;
- first-sell price versus the best fully observed pre-exit hourly peak;
- multi-sell behavior and last-vs-first sell change;
- path completeness so truncated histories are not silently treated as complete.

Suggested command, with the operational monitor stopped:

```powershell
python wallet_exit_context.py `
  7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH `
  --tokens 12
```

Interpretation target:

- **profit-trigger-like:** first sales cluster after meaningful favorable excursions and at positive proxy returns;
- **time-trigger-like:** first sales cluster around a similar duration even with widely different returns;
- **runner/staged-realization-like:** first sale often occurs after a favorable move while later sales remain materially separated and can capture different parts of the path;
- **weak/heterogeneous:** sell timing and returns show no stable relationship, implying the apparent pattern is not yet strategy-like.

## Hard limitations

- The first observed local buy may not be the wallet's historical first buy if backfill is incomplete.
- GeckoTerminal minute/hour candles are market proxies, not exact wallet fills.
- The current dominant/cache-selected pool can differ from the historical execution pool.
- MFE/MAE based on hourly high/low does not prove executable size at that price.
- Current liquidity and market-cap snapshots cannot be substituted for historical entry-time conditions.
- Sample sizes remain small and wallet-specific.
- No finding here changes the frozen `wave_v3_volume_integrity` baseline or validates live trading.
