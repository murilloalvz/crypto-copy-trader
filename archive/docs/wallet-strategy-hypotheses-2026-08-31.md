# Wallet Strategy Hypotheses — frozen 2026-08-31

## Purpose

Freeze the current behavioral hypotheses before additional forward observations arrive. This is meant to reduce hindsight tuning. These are research hypotheses, not trading rules and not claims of profitability.

## H1 — 7mPti: one-day mixed exit

Current descriptive evidence:

- 94 swaps / 36 tokens;
- 72.2% observed roundtrips;
- median first exit 18.5h;
- multi-sell 42.3%;
- reentry 19.2%;
- 21 complete-like cycles;
- six complete-like multi-sell cycles with median first tranche / runner 50% / 50%.

Frozen hypothesis:

> The wallet primarily behaves as a longer-horizon position manager rather than a scalper, with a meaningful staged-exit submode and occasional reentry.

Predeclared descriptive checks once at least 10 new forward roundtrips exist:

- median first exit should remain above 6h;
- multi-sell share should remain at least 25%;
- reentry should remain below 40%.

Failing these checks weakens the current archetype. Passing them still does not prove edge.

## H2 — Gf9X: ultra-short single-exit candidate

Current descriptive evidence:

- 71 swaps / 36 tokens;
- only 36.1% observed roundtrips;
- median first exit 5.3min;
- multi-sell 15.4%;
- reentry 7.7%;
- 10 complete-like cycles;
- PumpSwap 83.1% of observed swaps.

Frozen hypothesis:

> The wallet is a distinct ultra-short archetype in which most observed completed positions are exited quickly and usually in one sell, with rare reentry.

Predeclared descriptive checks once at least 10 new forward roundtrips exist:

- median first exit should remain below 15min;
- multi-sell share should remain at or below 25%;
- reentry should remain below 15%.

The main current weakness is sequence coverage. Historical backfill should improve coverage, not move thresholds after seeing outcomes.

## H3 — 3tc4: bursty ultra-short staged/reentry candidate

Current descriptive evidence:

- 93 swaps but only 5 tokens;
- ~0.2 day historical observation window;
- 80% observed roundtrips;
- median first exit 1.2min;
- scale-in 100%;
- multi-sell 50%;
- reentry 50%;
- four complete-like cycles;
- median first tranche / runner 12.5% / 87.5%;
- PumpSwap 92.5%.

Frozen hypothesis:

> The observed burst represents a genuinely different ultra-short/high-frequency behavior with repeated scale-in, staged exits and reentry, rather than merely one concentrated episode.

This is the weakest of the three hypotheses because token diversity and time coverage are very small.

Predeclared checks once the sample reaches both at least 10 tokens and at least 10 complete-like cycles:

- median first exit should remain below 15min;
- multi-sell share should remain at least 40%;
- reentry should remain at least 40%;
- median first tranche among complete-like multi-sell cycles should remain at or below 75%.

If the broader sample does not preserve those traits, the current staged/reentry archetype should be rejected or reclassified rather than rescued by changing the thresholds.

## What the next forward watch is testing

The first 30-second forward watch of 7mPti, Gf9X and 3tc4 is primarily an observability experiment:

1. can public RPC polling consistently notice new wallet actions;
2. what is the actual chain_time -> observed_at latency distribution;
3. is 30-second polling remotely adequate for the ultra-short candidates;
4. can new actions later be assembled into causal roundtrips without historical look-ahead.

It is not yet a profitability test.

## Promotion rule

No wallet archetype moves into bot strategy logic from this document alone. Promotion requires, in order:

1. adequate descriptive evidence;
2. causal replay with predeclared logic;
3. execution stress with realistic latency/cost/liquidity assumptions;
4. forward/shadow confirmation;
5. evidence that the archetype adds value versus simpler controls.
