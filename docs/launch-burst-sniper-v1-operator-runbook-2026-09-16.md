# Launch Burst Sniper V1 — Operator Runbook

Date: 2026-09-16
Mode: RESEARCH / READ ONLY / NO-CAPITAL ROUTE-SHADOW

## Frozen identities

Do not edit these values for the V1 screening.

- Launch Burst route contract: `3d172e7b5f6f70703fe6f14d1734246c111513a82a7b74ad2811edfe4d6d494d`
- Sniper policy: `60a480a90365eae8abfcb55787345b41573fc1d2632d17c344741e93e36f490a`
- SMART-LADDER-25 V0 policy: `638d6440868c8b0dcbb91fe317be9a5181a11eee2be38ead65adff3ba9bdb818`
- Screening duration: exactly `900` seconds
- Primary outcome benchmark: fixed `+60s` route-paper
- SMART-LADDER-25: exploratory only

The runner rejects an in-place duration change and rejects policy files whose frozen identity changed, even if an edited file was re-hashed.

## Required environment

The local `.env` must contain valid values for:

- `HELIUS_API_KEY`
- `JUPITER_API_KEY`
- `SOLANA_RPC_URL`

`SOLANA_RPC_FALLBACK_URLS` remains optional.

Never paste `.env`, API keys, or secret material into a report/chat.

## Step 1 — Sync the validated research branch

```powershell
git switch research/solana-burst-economic-sim-v0
git pull origin research/solana-burst-economic-sim-v0
git log -1 --oneline
```

Do not run an older local copy after the branch head was promoted.

## Step 2 — Standalone read-only support preflight

```powershell
python -m benchmarks.launch_burst_sniper_v1.preflight
```

Required classification:

`PASS_LAUNCH_BURST_SNIPER_V1_PREFLIGHT`

The preflight must show all support gates true. It:

- validates the exact frozen Sniper and SMART-LADDER policies;
- validates the frozen route fixture/contract;
- checks required environment configuration;
- discovers a public funded control address using mint-filtered Helius holder discovery;
- checks owner SOL balances in bounded `getMultipleAccounts` batches rather than one RPC call per holder;
- asks Jupiter to assemble a known-liquid control transaction and a representative Burst transaction;
- signs nothing;
- submits nothing;
- opens no economic outcome.

If this preflight does not PASS, do not start the 900s screening. Repair only the support/configuration blocker and rerun the preflight unchanged.

## Step 3 — Frozen 900s screening

Only after the standalone preflight PASS:

```powershell
python -m benchmarks.launch_burst_control_taker_sim_v0.run_v4_sniper_v1 --duration-seconds 900
```

The live runner repeats the support preflight immediately before acquisition and reuses exactly the public control that passed both assembly probes. It fails closed before acquisition if the support preflight no longer passes.

The public control is only read-only assembly scaffolding. It is not the official V4 funded taker, does not open the official funded-taker gate, and must not be interpreted as landed execution or realized PnL.

## What is collected

One baseline acquisition is used for the comparison.

The frozen Launch Burst baseline still controls provider dispatch:

- `pump_launch`
- 5s evidence window
- `signed_flow_over_event_reserve >= 0.08`
- +2s entry latency
- US$25 notional
- frozen fees/slippage/price-impact semantics

Sniper V1 is applied afterward to the feature snapshot that was already frozen before provider quotes. It must remain a strict subset of the baseline universe.

The strict comparator requires:

- route input/result PASS types;
- unique episode keys;
- exact episode-key parity;
- exact token-mint parity per episode;
- no SMART-LADDER orphan episode;
- exact frozen policy hashes.

## Sniper V1 primary selector

All predicates are required inside the frozen 5s snapshot:

1. `signed_flow_over_event_reserve >= 0.08`
2. `event_count >= 5`
3. `directional_flow_efficiency >= 0.50`
4. `wallet_identity_coverage_pct >= 80%`
5. `wallet_gross_flow_coverage_pct >= 80%`
6. `unique_buy_wallet_count >= 3`
7. `top_wallet_gross_flow_share_worst_case_pct <= 60%`
8. `transaction_identity_coverage_pct >= 80%`
9. `unique_transaction_count >= 3`

The worst-case wallet concentration assigns all unidentified gross flow to the largest identified wallet. Missing required evidence is not imputed.

## Result interpretation

Keep three verdict domains separate.

### SYSTEMS / SUPPORT

A provider/RPC/control-discovery/assembly failure is an infrastructure/support result. It is not a losing trade and is not evidence against the market hypothesis.

### SCIENTIFIC

A valid comparison requires the frozen universe, clocks, policies and exact source parity to remain intact. Any mutation or artifact mismatch invalidates the comparison rather than producing an economic verdict.

### ECONOMIC PROXY

Fixed +60s route-paper is the primary benchmark. SMART-LADDER-25 is exploratory. Both remain no-capital route-shadow evidence, not landed fills or realized PnL. The official V4 funded-taker economic verdict remains unchanged.

## Frozen sample interpretation

- fewer than 10 usable primary route results: `INSUFFICIENT_PRIMARY_SAMPLE`
- 10–29: descriptive directional read only; replication is not armed
- 30 or more: sample-size eligible for a fresh independent replication; edge is still not established

Do not relax thresholds after seeing this screening. Do not silently extend the same sample. A longer/fresh run requires a separate preregistration before acquisition.

## What to preserve after the run

Preserve the complete generated run directory, especially:

- the wrapper simulation report;
- route input;
- fixed +60s route result;
- market paths;
- SMART-LADDER-25 result;
- Sniper comparison report;
- processed/raw evidence referenced by the V4 report.

Do not hand-edit generated JSON artifacts.

## What to report for review

Send the final compact console JSON plus the path to the generated `simulation-report-v4-sniper-v1.json`.

At minimum preserve/report:

- top-level classification;
- support preflight classification/gates;
- baseline/primary/diagnostic selected counts;
- source-integrity block;
- screening status and usable count;
- fixed +60s baseline and Sniper metrics;
- counterfactual skipped-trade metrics;
- rejection-reason counts;
- SMART-LADDER exploratory section;
- artifact paths.

Do not report API keys or `.env` contents.
