# Launch Burst Sniper V1

Prospective high-precision selector layered on top of the frozen Launch Burst V4 route-shadow experiment.

## What stays frozen

- Pump launch stratum.
- 5 second evidence window.
- Baseline selector: `signed_flow_over_event_reserve >= 0.08`.
- +2 second entry latency.
- US$25 notional.
- Frozen fees/slippage/route-quality contract.
- Fixed +60s exit as the primary benchmark.
- SMART-LADDER-25 is exploratory only.

The Sniper does not decide which provider routes are collected. V4 collects the normal frozen baseline universe first; the preregistered Sniper rule is then evaluated as a strict subset using the feature snapshot that was already frozen before provider quotes.

## Offline validation

From repository root:

```powershell
python -m unittest tests.test_launch_burst_sniper_v1 tests.test_launch_burst_sniper_runtime_enrichment_v1 tests.test_launch_burst_sniper_compare_v1 -v
```

Optional full suite:

```powershell
python -m unittest discover -s tests -q
```

## Prospective screening run

Required `.env` values remain the same as the V4 simulation:

- `HELIUS_API_KEY`
- `JUPITER_API_KEY`
- `SOLANA_RPC_URL`
- optional `SOLANA_RPC_FALLBACK_URLS`

Run:

```powershell
python -m benchmarks.launch_burst_control_taker_sim_v0.run_v4_sniper_v1 --duration-seconds 900
```

The command automatically applies:

- the existing Jupiter negative-price-impact semantics correction;
- the canonical Pump `wallet` enrichment;
- frozen SMART-LADDER-25 path capture;
- fixed +60s baseline accounting;
- preregistered Sniper V1 comparison.

It prints a compact summary and writes full artifacts under:

`artifacts/launch_burst_control_taker_sim_v4_sniper_v1/...`

Key artifact:

`sniper-comparison-v1.json`

## How to read the first run

The first 900s acquisition is a screening run, not proof of edge.

- `<10` usable primary Sniper route results: insufficient sample.
- `10-29`: descriptive directional read only.
- `>=30`: eligible to justify a fresh independent replication run.

Do not retune thresholds from the screening result.

The most useful fields are:

- `baseline_selected_count`
- `primary_selected_count`
- `primary_selection_rate_pct_of_baseline`
- `fixed_60s_primary_benchmark.baseline`
- `fixed_60s_primary_benchmark.primary_sniper`
- `fixed_60s_primary_benchmark.counterfactual_skip`
- `fixed_60s_primary_benchmark.primary_minus_baseline`
- `primary_selector_diagnostics.reason_counts`
- `screening.status`

A positive `counterfactual_value_of_skipping_usd` means the baseline trades rejected by the Sniper were net harmful inside that route-shadow sample. A negative value means the filter skipped net-positive baseline PnL.

## Scientific boundary

`PASS_LAUNCH_BURST_CONTROL_TAKER_SIM_V4_SNIPER_V1` means the systems/accounting comparison completed. It does **not** mean real-money profitability was established.

The public control address is still used only for read-only Jupiter assembly. No private key is required, and no transaction is signed or submitted.

## Robinhood Chain

The selector consumes normalized feature names, so the comparison/accounting framework can be reused later on Robinhood Chain. The existing repo already has `multichain_market_contract_v59`, `robinhood_pons_adapter_v62`, `pons_curve_state_progress_v64`, and `pons_launch_quality_evidence_v67`.

Do not reuse Solana thresholds directly. Robinhood/Pons requires feature-parity evidence and a separate preregistration before activation.
