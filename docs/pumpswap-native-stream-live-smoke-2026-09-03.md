# PumpSwap Native Market Stream — Live Smoke 2026-09-03

Status: **PASS — acquisition/pool-resolution plumbing only**

Mode: **PAPER / RESEARCH / READ ONLY**

Run:

```text
pumpswap-smoke-20260903-01
```

Command executed on the user's real local machine:

```text
python pumpswap_market_stream_smoke.py --run-key pumpswap-smoke-20260903-01 --duration-seconds 120 --commitment confirmed --max-hydrations 100 --rpc-timeout-seconds 3
```

Observed summary:

```text
elapsed=120.8s
notifications=749
decoded_trades=837
buys=472
sells=365
create_pools=0
persisted_trades=837
duplicate_or_replayed=0
unresolved_trades=0
resolution_pct=100.0%
persisted_lifecycle=0
unique_pools=150
unique_wallets=737
create_event_pools=0
pool_cache_hits=685
pool_store_hits=60
hydration_attempts=92
hydration_successes=92
hydration_failures=0
actual_network_hydrations=92
hydration_budget_skips=0
negative_cache_skips=0
max_hydrations=100
rpc_timeout=3s
```

## Interpretation

The smoke validates that the native PumpSwap adapter can receive live program logs, decode BuyEvent/SellEvent traffic, resolve `pool -> base_mint` causally, and persist normalized market observations without guessing token identity.

Observed live properties:

- all 837 decoded trades were persisted;
- all 837 trades were resolved to token identity;
- zero unresolved trades;
- zero hydration failures;
- 150 unique pools and 737 unique wallets were observed in about two minutes;
- 92 previously unknown pools required account hydration;
- after resolution, repeated trades were predominantly handled through cache/store reuse.

This is an **operational PASS**, not evidence of alpha, profitability, fill quality, or economic executability.

## Important capacity finding

The smoke consumed 92 of the configured 100 hydration attempts in 120.8 seconds. The `max_hydrations=100` smoke budget is therefore suitable as a short safety bound but **must not be reused as a fixed total budget for a multi-hour acquisition run**.

Before a long run, the production acquisition path must use bounded hydration mechanics that scale with elapsed time and preserve coverage, for example:

- persistent pool identity reuse across runs when the identity was already causally known before the new run;
- explicit rate/throughput budgets rather than a single run-total cap;
- bounded concurrency and timeout;
- negative-cache TTL for failed/unresolvable pools;
- hydration latency/failure/coverage telemetry.

No detector thresholds or economic rules are changed from this smoke.

## Decision

**NATIVE PUMPSWAP ACQUISITION + CAUSAL POOL RESOLUTION: LIVE SMOKE PASS.**

Next gate is not another standalone PumpSwap smoke. The next useful work is to unify Pump bonding + PumpSwap into the market-first acquisition/radar pipeline, then add episode-scoped bounded enrichment and a short end-to-end smoke before any 12h run.
