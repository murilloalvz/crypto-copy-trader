# Crypto Copy Trader — Route Research v41 Structural Hardening

Date: 2026-09-06
Branch: `feat/exit-engine-v1`
Mode: **PAPER / RESEARCH / READ ONLY**

## Why v41 exists

The first live v40 route-only cohort produced useful causal forward labels, but the 120-second
acquisition smoke exposed two structural problems that must be separated from strategy quality:

1. v40 selected 12 episodes, but one had terminal on-chain hazard `PROVIDER_ERROR`. The research
   worker correctly did **not** call Jupiter entry for that episode. The v40 summary nevertheless
   divided Jupiter-entry terminal attempts by all 12 selected episodes and reported 91.7% coverage,
   making an explicit upstream exclusion look like a missing entry call.
2. PumpSwap pipeline p95 regressed to ~36.4s during an unusual unknown-pool burst. Live telemetry
   showed 347 network hydrations / 189 successful batches, while the v32/v33 implementation had one
   daemon batch thread that called `_fetch_batch` synchronously. Therefore only one
   `getMultipleAccounts` batch could be in flight at a time even though the outer resolver already
   budgeted 18 concurrent expensive resolutions.

v41 fixes **accounting and transport plumbing only**. It does not alter detector thresholds,
opportunity T0, episode windows, wallet/hazard features, route-return labels, slippage, notional,
official `decision_as_of`, or any live-money rule.

## Historical v40 result remains historical

The v40 live result is not retroactively rewritten.

### Route-research decision smoke

- selected: 12
- hazard: 11 AVAILABLE / 1 PROVIDER_ERROR
- Jupiter route-only entry attempts: 11 AVAILABLE
- research decisions frozen: 11
- forward outcomes scheduled: 33
- route-only executable violations: 0
- decision clock violations: 0
- official decision mutation violations: 0
- historical v40 classification: `FAIL_ROUTE_ONLY_RESEARCH_DECISION_PLUMBING`

The new read-only diagnostic `route_research_structural_diagnostic_v41.py` exists to determine from
persisted evidence whether that historical failure was a real missing eligible entry or an explicit
upstream hazard disposition. Its output is explanatory only and does not mutate the historical
classification.

### v40 forward collector

- scheduled: 33
- AVAILABLE: 30
- PROVIDER_ERROR: 3
- 10/11 AVAILABLE at each of 300s / 900s / 3600s
- target lateness p95: 1s
- collector errors: 0
- executable semantic violations: 0
- classification: `PASS_ROUTE_ONLY_FORWARD_COLLECTION_COMPLETE`

The same episode produced provider error at all three horizons. The v41 structural diagnostic prints
the exact persisted provider error fingerprint; no causal explanation may be invented before that
persisted message is inspected.

### v40 first route-only economic microcohort

These are causal route-only research returns, **not** landed/fill P&L and not wallet realized P&L.

- 300s: n=10, positive share 40%, mean -22.788%, median -32.044%, PF 0.412
- 900s: n=10, positive share 10%, mean -47.031%, median -50.019%, PF 0.049
- 3600s: n=10, positive share 10%, mean -53.070%, median -50.184%, PF 0.052
- 300s best winner +138.698%; mean without that winner -40.731%; that winner contributed ~86.991%
  of gross positive return.

Classification at every horizon remains `INCONCLUSIVE_SAMPLE_LT_30`.

No detector/score/threshold change is permitted from this microcohort.

## v41 accounting rule

For the route-research decision pipeline, selected episodes are partitioned causally:

```text
selected episode
  -> terminal hazard AVAILABLE
       -> eligible for Jupiter route-only entry
       -> entry terminal disposition
  -> terminal hazard non-AVAILABLE/error
       -> explicit upstream disposition
       -> Jupiter entry MUST NOT be invented
```

Two coverages are reported separately:

1. `selected_terminal_disposition_coverage_pct`
   - denominator: all selected episodes;
   - numerator: explicit terminal hazard exclusions + terminal entry attempts.
2. `entry_terminal_coverage_among_eligible_pct`
   - denominator: hazard-AVAILABLE episodes only;
   - numerator: terminal Jupiter route-only entry attempts.

A terminal hazard provider error is therefore not a missing Jupiter entry.

A genuinely missing entry after an AVAILABLE hazard still fails closed.

Historical v40 summaries are not reclassified by this rule.

## v41 PumpSwap batch transport

New resolver:
`src/pumpswap_parallel_batched_resolver_v41.py`

Previous v32/v33 invariant retained:
- causal cache and stores unchanged;
- per-pool single-flight unchanged;
- hydration budget remains per pool;
- causal `as_of` unchanged;
- global reservation ordering unchanged;
- v33 first-valid hedged endpoint semantics unchanged;
- unresolved provider evidence remains explicit.

Structural change:
- one dispatcher still forms queue-ordered batches;
- up to `hydration_batch_workers` batches can execute concurrently;
- when all lanes are busy, backlog accumulates and is drained into the next batch before dispatch;
- default v41 profile: 8 batch workers, 2 hedge endpoints;
- hard invariant: `hydration_batch_workers * hedge_endpoints <= max_concurrent_resolutions`.

With the frozen default profile:

```text
8 batch workers * 2 hedges = 16 possible endpoint requests
existing max_concurrent_resolutions = 18
```

Therefore v41 uses concurrency that was already inside the configured expensive-work budget instead
of increasing that budget by trial and error.

New diagnostics:
- dispatched batches/items;
- average/max batch size;
- batch inflight high-water;
- batch queue-depth high-water;
- parallel batch service latency.

## v41 fresh live gate

A fresh 120-second v41 smoke must be run. **Code/CI PASS is not live PASS.**

The unchanged Unified Market Latency 11-gate still applies independently:

1. no traceback/worker errors;
2. drops 0;
3. reference asset episodes 0;
4. radar coverage >=95%;
5. true total deadline backlog <=5% of received;
6. Pump radar p95 <=5s;
7. PumpSwap causal pipeline p95 <=5s;
8. hydration budget skips 0;
9. bundles not systematically empty;
10. replay/collision counters auditable;
11. reservation superset violations 0.

Route-research v41 plumbing PASS additionally requires:
- selected > 0;
- 100% terminal disposition coverage across selected episodes;
- 100% entry terminal coverage among hazard-AVAILABLE episodes;
- no hazard wait timeout;
- no config missing;
- no reused entry attempts in a fresh run;
- no research worker errors;
- no route-only executable semantic violations;
- no research decision clock violations;
- no official decision mutation;
- no schedule violations;
- frozen research decisions == AVAILABLE route-only entries;
- exactly 3 scheduled outcomes per frozen research decision;
- at least one AVAILABLE route-only entry, otherwise inconclusive rather than PASS.

Explicit terminal hazard/provider missingness may reduce the number of research decisions without
being misreported as missing entry plumbing.

## What v41 does not prove

Even if both live gates pass, v41 does not prove:
- economic edge;
- profitability after execution costs;
- assemblable funded BUY/SELL;
- token ownership for a taker;
- landing or fill;
- wallet realized P&L;
- predictive value of wallet/hazard/flow features;
- shadow/live readiness.

Funding and official executable validation remain separate gates.
