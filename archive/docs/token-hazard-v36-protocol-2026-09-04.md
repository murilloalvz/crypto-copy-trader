# Crypto Copy Trader — Token Hazard v36 Protocol

Date: 2026-09-04
Mode: **PAPER / RESEARCH / READ ONLY**

## Purpose

Validate causal token-hazard acquisition while funded Jupiter transaction assembly is externally
blocked. This protocol does **not** waive the funded-executability gate and does not start the
official economic cohort.

## Frozen market path

v36 reuses the v34 systems path:

- frozen `market_opportunity_radar_v1_1_tx_aware` detector;
- v33 hedged batched PumpSwap hydration;
- v34 proof-based late continuation demotion;
- same first-persisted episode semantics;
- same no-retroactive-enrollment/replay rules;
- same v30 11-condition systems-latency gate.

No detector threshold, episode window, reservation/FIFO rule or worker profile is tuned from hazard
outcomes.

## Hazard provider

Provider: `solana_tracker_token_info`
Purpose: `token_hazard_v1`
Endpoint: Solana Tracker `GET /tokens/{mint}`

Capture rules:

- first 12 newly admitted episodes only;
- 2 isolated hazard workers;
- provider timeout 8 seconds;
- one provider attempt per episode;
- STARTED persisted before provider I/O;
- terminal result immutable;
- replay cannot silently recall provider;
- provider work is off the market acquisition path;
- no Jupiter `/order`, no signing, no `/execute`, no transfer.

Normalized descriptive fields include:

- provider risk score;
- rugged status;
- Jupiter-verified flag;
- top10/dev/snipers/bundlers/insiders percentages when returned;
- mint/freeze authority presence when returned;
- provider risk factors;
- explicit data-quality flags.

No risk threshold is used to accept/reject an episode in v36.

## Causal rules

- hazard `observed_at` is the local acquisition clock after the provider response;
- `hazard.observed_at` cannot precede episode first-trigger observation;
- an enrichment bundle at time `as_of` may use hazard evidence only when
  `hazard.observed_at <= as_of`;
- later provider evidence is never backfilled into an earlier decision bundle;
- CONFIG_MISSING / PROVIDER_ERROR / UNAVAILABLE / NORMALIZATION_ERROR remain explicit.

## v36 hazard-provider PASS gate

The hazard-provider integration is PASS only when all are true in a fresh run:

1. selected episodes > 0 (`0 => INCONCLUSIVE_NO_SAMPLE`);
2. terminal provider coverage = 100%;
3. CONFIG_MISSING = 0;
4. hazard worker errors = 0;
5. reused attempts = 0;
6. causal clock violations = 0;
7. at least one AVAILABLE normalized hazard observation exists.

Separately, the same run must still be evaluated against the frozen **11 systems-latency gates**.
Hazard-provider PASS does not imply economic edge, funded executability, decision readiness or live
trading readiness.

## Frozen live command

```powershell
python unified_market_hazard_smoke_v36.py --run-key unified-market-hazard-smoke-20260904-36 --duration-seconds 120 --commitment confirmed --max-hydrations 1500 --rpc-timeout-seconds 3 --pump-batch-size 32 --pump-batch-max-wait-ms 25 --pump-prepare-workers 12 --pumpswap-workers 256 --pumpswap-prepare-submitters 64 --pumpswap-prepare-executor-workers 32 --pumpswap-writer-batch-size 32 --pumpswap-writer-batch-max-wait-ms 10 --max-concurrent-resolutions 18 --queue-size 5000 --continuation-batch-size 32 --continuation-batch-max-wait-ms 5 --default-io-workers 32 --hydration-batch-size 64 --hydration-batch-max-wait-ms 5 --hedge-endpoints 2 --max-hazard-episodes 12 --hazard-workers 2 --hazard-timeout-seconds 8 --hazard-max-attempts 1
```

A reused run key is not a valid fresh provider smoke.

## What remains blocked

Even if v36 passes:

- funded Jupiter executable assembly remains `BLOCKED_BY_FUNDING` until a funded dedicated taker
  demonstrates at least one persisted assembled transaction under the frozen executable protocol;
- official `decision_as_of` must not be frozen yet;
- official +5m/+15m/+60m economic outcomes must not start yet;
- 12h collection remains blocked;
- shadow/live money remains blocked.
