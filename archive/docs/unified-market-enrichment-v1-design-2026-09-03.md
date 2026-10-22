# Unified Market Enrichment v1 — Design Freeze — 2026-09-03

Mode: PAPER / RESEARCH / READ ONLY.

## Goal

Validate the smallest live path that can turn market-first acquisition into a causal opportunity evidence bundle without paying enrichment cost for every raw radar hit.

Target path:

```text
Pump bonding + PumpSwap
-> normalized market observations in one acquisition run
-> Market Opportunity Radar v1.1
-> Opportunity Episode
-> exactly-once episode enrichment admission
-> shared flow snapshot + dynamic wallet evidence
-> later: Jupiter execution + causal hazard provider
-> freeze decision_as_of only after required provider attempts finish
```

## Frozen semantics

1. Pump and PumpSwap share the same market observation store and acquisition run key.
2. Raw radar hits remain persisted, but expensive enrichment is admitted once per opportunity episode.
3. Pump bonding `CreateEvent` is the v1 canonical token-birth lifecycle event.
4. PumpSwap `CreatePoolEvent` is a venue/pool lifecycle event and MUST NOT redefine token age or unlock `fresh_market_burst` by itself.
5. PumpSwap pool identity can be reused across runs only when that identity was already known by the current `as_of`. Conflicting historical identities remain visible errors.
6. A trade received before its PumpSwap pool identity is resolved cannot be treated as fully identified before the identity resolution time.
7. Risk remains explicit missingness until a causal hazard provider is wired. Flow concentration is not a substitute for a rug/manipulation probability.
8. The current unified smoke intentionally does not call Jupiter or freeze `decision_as_of`; it validates acquisition, episode admission and local evidence-bundle plumbing only.
9. No detector threshold is changed by these plumbing/capacity changes.
10. No BUY/SELL score or recommendation is introduced.

## PumpSwap capacity response

The live PumpSwap smoke resolved 837/837 trades but required 92 network hydrations in about 120 seconds. A fixed lifetime budget of 100 hydrations therefore cannot be the production multi-hour policy.

v1 response:

- reuse causally known pool identities across runs;
- keep bounded network hydration in smoke/runtime wrappers;
- retain timeout and negative-cache protection;
- measure historical-store hits, cache hits, network hydrations, failures and budget skips;
- choose any future long-run rate/concurrency budget before the 12h protocol is frozen, not from P&L.

## Current smoke acceptance questions

The short unified smoke should answer only:

- can both streams coexist without crashing/backpressure failure?;
- do both venues persist into one causal market surface?;
- does PumpSwap produce radar episodes through established acceleration without fake fresh-token lifecycle?;
- is enrichment admission once-per-episode?;
- does the local bundle contain shared flow and wallets actually present?;
- does historical PumpSwap pool reuse reduce live hydration demand?;
- is missing execution/risk explicit rather than fabricated?

It does not measure edge, profitability, fills or entry quality.

## Next gate after smoke PASS

Wire episode-scoped provider enrichment:

1. bounded Jupiter execution quote attempts;
2. minimal causal token-hazard interface/provider;
3. resolved historical wallet outcomes when available;
4. explicit provider status/missingness;
5. final `decision_as_of = max(actual required evidence availability times)`;
6. short true end-to-end smoke;
7. only then freeze the first 12h acquisition/evaluation protocol.
