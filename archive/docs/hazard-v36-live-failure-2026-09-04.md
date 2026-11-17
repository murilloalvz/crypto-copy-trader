# Hazard v36 — Live Provider Failure

Date: 2026-09-04  
Run key: `unified-market-hazard-smoke-20260904-36`  
Mode: **PAPER / RESEARCH / READ ONLY**

## Formal result

### Unified market systems latency

**PASS 11/11** in the same v36 run.

Key evidence:
- received: Pump 2940 + PumpSwap 3966 = 6906;
- radar processed: Pump 2940 + PumpSwap 3947 = 6887;
- coverage: 99.7%;
- true deadline backlog: `(6906 - 6887) / 6906 = 0.275%`;
- Pump radar p95: 1.808s;
- PumpSwap pipeline p95: 2.729s;
- drops: 0;
- worker errors: 0;
- reference-asset episodes: 0;
- hydration budget skips: 0;
- reservation superset violations: 0;
- bundles were non-empty and replay/collision telemetry remained auditable.

v34 proof-based demotion remained active:
- demoted pending jobs: 119;
- demoted pending tickets: 119;
- demoted finalizer acknowledgements pending at end: 0.

### Solana Tracker causal token hazard

**FAIL_CAUSAL_HAZARD_PROVIDER**.

Frozen first-12 cohort:
- selected: 12;
- AVAILABLE: 0;
- UNAVAILABLE: 0;
- CONFIG_MISSING: 0;
- PROVIDER_ERROR: 12;
- METADATA_ERROR: 0;
- NORMALIZATION_ERROR: 0;
- terminal coverage: 100%;
- reused attempts: 0;
- hazard worker errors: 0;
- causal clock violations: 0.

The failure is therefore isolated to provider availability for the selected hazard calls. The live summary alone does **not** establish whether the cause was rate limiting, authentication, HTTP status, timeout, network failure, or another provider error.

## Required diagnostic before any provider patch

Use persisted evidence only:

```powershell
python hazard_provider_attempt_diagnostic.py --run-key unified-market-hazard-smoke-20260904-36
```

The diagnostic performs no Solana Tracker or RPC I/O. It groups the already-persisted attempt `error_type` / `error_message` into evidence-based categories such as `RATE_LIMIT`, `AUTH`, `HTTP_404`, `TIMEOUT`, `NETWORK`, or other provider error.

Do not change endpoint, retries, workers, detector, v34 scheduler, v33 resolver, or latency capacity profile until this persisted diagnostic identifies the failure class.

## Provider contract verification

Current Solana Tracker documentation still specifies `GET /tokens/{tokenAddress}` with `x-api-key`, and the token response includes a `risk` object. Therefore the endpoint should not be changed merely because the v36 cohort returned provider errors; the persisted provider reason remains the next source of truth.
