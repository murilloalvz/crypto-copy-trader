# Solana Launch Burst — Control-Taker Economic Simulation V0

Isolated no-capital route-shadow simulation for the frozen Solana Launch Burst hypothesis.

## Scope

This benchmark does **not** modify or unblock the official V4 funded-taker economic gate.
It preserves the frozen route contract: `pump_launch`, 5s evidence, `signed_flow_over_event_reserve >= 0.08`, no confirmation, +2s entry latency, US$25 notional, 20 bps fee + 100 bps adverse slippage per side, and fixed exit +60s from observed entry.

Frozen route contract hash:

`3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d`

The simulator discovers a public on-chain USDC owner satisfying the already-frozen control floors and supplies **only the public address** to Jupiter so a candidate BUY can be assembled. It never has a private key, never signs and never submits a transaction.

## Primary and exploratory outputs

Primary benchmark: `FIXED_60S_ROUTE_PAPER`.

Exploratory comparison: `PREREGISTERED_SMART_EXIT_V0`.

The smart policy is committed before outcomes:

- +20% net route return -> sell 25%
- +50% -> sell 25%
- +100% -> sell 25%
- final 25% runner -> 10% trailing drawdown after +100%
- any unsold remainder closes at +300s
- route observations at +5, +10, +20, +30, +45, +60, +90, +120, +180, +240, +300 seconds from entry
- no stop-loss
- no adaptive tuning

The grid is discrete, so this claims first-observed-on-grid behavior, not continuous first touch.

## Environment

Use the existing project `.env` or set:

```powershell
$env:HELIUS_API_KEY="..."
$env:JUPITER_API_KEY="..."
$env:SOLANA_RPC_URL="..."
```

Optional:

```powershell
$env:SOLANA_RPC_FALLBACK_URLS="https://rpc-a.example,https://rpc-b.example"
```

Never commit API keys.

## Preflight

```powershell
python -m benchmarks.launch_burst_prospective_route_live_v4.no_funds_assembly_diagnostic
```

This should confirm provider assembly with a public funded control. It remains diagnostic-only.

## Smoke

```powershell
python -m benchmarks.launch_burst_control_taker_sim_v0.run --duration-seconds 300
```

## Research run

```powershell
python -m benchmarks.launch_burst_control_taker_sim_v0.run --duration-seconds 900
```

The process can remain active after acquisition closes while the last selected episodes finish their preregistered +300s path.

## Artifacts

Each run creates the existing V2 raw/processed evidence plus:

- `route-input-v2.json`
- `route-result-v2.json` — primary fixed +60s result
- `market-paths-v0.json`
- `smart-exit-result-v0.json`
- `simulation-report-v0.json`

A systems PASS means the simulation pipeline worked. Positive route-shadow PnL is evidence for further validation, not landed fills or realized profit, and it does not change the frozen V4 economic verdict.
