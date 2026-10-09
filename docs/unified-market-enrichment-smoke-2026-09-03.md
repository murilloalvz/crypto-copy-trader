# Unified Market Enrichment Smoke — 2026-09-03

Run: `unified-market-smoke-20260903-01`

Mode: PAPER / RESEARCH / READ ONLY.

## Result

The smoke did not crash, but it is **NOT a live pass**.

Observed summary:

```text
requested_duration=120s
elapsed=239.4s
notifications={'pumpswap': 4153, 'pump': 2280}
persisted_trades={'pumpswap': 2678, 'pump': 2213}
affected_tokens=253
raw_radar_hits={'pump': 468}
unique_episodes=28
opened_by_source={'pump': 28}
enrichment_admitted=28
bundle_wallets_total=0
bundle_flow30_total=0
risk_missing=28
pumpswap_historical_pool_hits=90
pumpswap_run_store_hits=15
cache_hits=6370
network_hydrations=100
hydration_successes=100
failures=2815
budget_skips=2815
```

## Findings

1. `bundle_flow30_total=0` and `bundle_wallets_total=0` despite thousands of persisted trades is an integration/timing defect, not evidence that the episodes lacked market participants.
2. The smoke built local bundles using wall-clock processing time. Because the queue accumulated backlog, the 30s flow window had already moved past the trigger-time observations by the time enrichment ran.
3. The requested 120s run consumed 239.4s because the consumer drained queued work after the acquisition deadline instead of stopping at the deadline and reporting backlog.
4. PumpSwap radar evaluation redundantly resolved pools a second time after persistence. Successful mappings normally hit cache, but budget-exhausted pools were retried and inflated `hydration_failures` / `budget_skips` telemetry.
5. No PumpSwap radar episodes opened in this smoke. This is not yet classified as a detector failure because the backlog and redundant resolution path contaminated the operational measurement.

## Corrective action

Before another live smoke:

- anchor the local acquisition-context bundle to the episode trigger availability time when no external enrichment provider is being called;
- stop the bounded smoke at its deadline and report queue backlog instead of draining it;
- make PumpSwap persistence return resolved trade metadata so the radar bridge does not call pool resolution again;
- preserve the actual causal `observed_at` from pool identity resolution when evaluating PumpSwap flow;
- keep detector thresholds frozen.

No economic thresholds are changed by this fix.
