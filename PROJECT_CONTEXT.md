# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado permanece em `docs/`.

## Estado canônico

- Repositório: `murilloalvz/crypto-copy-trader`
- Branch: `feat/exit-engine-v1`
- Modo: **PAPER / RESEARCH / READ ONLY**
- Tese ativa: **market-first Solana Opportunity Intelligence / Opportunity Engine**
- Detector/economia v48 permanecem congelados.

Fluxo:
`market -> radar -> causal episode -> enrichment -> research decision -> forward outcomes -> economic validation -> shadow`

## Status atual

- Unified Market Latency v42: **FORMAL PASS 11/11**
- v44 practical provider-paced path: **PASS 11/11**
- v46 dual prospective discovery: **2/2 PASS / COMPLETE**
- v47 causal feature discovery + robustness: **COMPLETE**
- first fresh v48 attempt: **SYSTEMS ABORT 9/11 BEFORE FORWARD COLLECTION; ECONOMICS NOT_EVALUATED**
- v49-v52: systems-only investigation/amendments; no Flow60 economic verdict
- v53 opportunistic prefetch profile: **LIVE SYSTEMS PASS 11/11 / CAUSAL ATTRIBUTION COMPLETE**
- v48 prospective Flow60 holdout: **FROZEN ECONOMIC PROTOCOL / v53 ACQUISITION WIRED / FRESH ECONOMIC RUN PENDING**
- profitable economic edge: **NOT ESTABLISHED**
- funded executable BUY: **BLOCKED_BY_FUNDING**
- official executable outcomes/shadow/live: **NOT RELEASED**

## Frozen systems gate

ALL must pass:
1. no worker errors
2. drops 0
3. reference asset episodes 0
4. radar coverage >=95%
5. true backlog <=5%
6. Pump p95 <=5s
7. PumpSwap causal pipeline p95 <=5s
8. hydration budget skips 0
9. bundles nonempty
10. replay/audit valid
11. reservation superset violations 0

Do not relax the 5s threshold.

## Systems investigation summary

### v50c

- PumpSwap received 7141 / 120s
- coverage 98.9%
- true backlog 1.097%
- Pump p95 2.077s — PASS
- PumpSwap p95 **15.508s — FAIL**
- result **10/11**
- exact causal attribution accepted
- submit->dependency-ready p95 **12.988s**
- finalize ready queue p95 **9.467s**
- dominant clock `per_asset_dependency`

### v51

Stateful-ready work receives priority over already-demoted continuation audit while keeping one finalizer, one stateful commit executor, same-asset FIFO and global reservation order unchanged.

Live:
- PumpSwap p95 7.658s — FAIL
- result 10/11
- global prefix normalization barrier p95 7.655s

Interpretation: v51 reduced the downstream ready-queue HOL but exposed a separate upstream normalization/reservation HOL.

### v52

The existing 3s PumpSwap RPC timeout became a true hedged decision wall deadline while real network capacity remains occupied until already-running non-cancellable losers drain.

Live:
- PumpSwap p95 7.981s — FAIL
- result 10/11
- hedge deadline expirations 0
- hedge fetch p95 431.8ms / max 663.6ms
- hedge cleanup p95 221.9ms / max 587.1ms
- self normalization max 13.044s
- global prefix barrier p95 5.786s

Conclusion: external hedge transport did not explain the 8-13s normalization tail in that run.

## v53 validated systems profile

Protocol:
`docs/route-research-v53-opportunistic-prefetch-protocol-2026-09-07.md`

v53 changes only optional ingress prefetch admission:
1. causal cache hit remains free;
2. if the same pool is already resolving, speculative prefetch skips instead of waiting;
3. if the expensive-resolution semaphore has no immediate slot, speculative prefetch skips instead of joining the capacity queue;
4. otherwise it calls the unchanged authoritative resolver path.

Skipped prefetch is not canonical unresolved evidence and does not consume hydration budget, persist mappings, reserve assets or create detector evidence. Authoritative normalization is unchanged.

### v53 live — accepted systems validation

Run:
`route-research-systems-stability-20260907-53`

Load/system result:
- PumpSwap received 3926
- Pump received 2494
- radar coverage **100.0%**
- true backlog **0.047%**
- Pump p95 **1867.4ms**
- PumpSwap p95 **2540.6ms**
- result **11/11**
- zero worker errors / drops / hydration-budget skips / reservation-superset violations
- no forward economic collector

Causal attribution:
- ingress/normalization/reservation/submit = 3926/3926/3926/3926
- barrier_attribution_complete=True
- lifecycle_attribution_complete=True
- causal_clock_attribution_acceptable=True
- self normalization p95 348.4ms / max 3095.8ms
- global prefix barrier p95 1662.2ms
- submit->dependency-ready p95 2800.9ms
- descriptive dominant clock `per_asset_dependency`

v53 resolver evidence:
- network hydrations 69; successes 69; failures 0
- singleflight waits 27
- demand capacity wait p95 0ms
- demand pool-lock wait p95 977.9ms
- prefetch pool-lock wait p95 0ms
- prefetch capacity wait p95 0ms
- prefetch skipped pool-busy 40; skipped capacity 0

Interpretation: the systems profile is now accepted for prospective acquisition. Do **not** continue latency tuning merely to improve an already-passing benchmark. Future systems redesign is justified only if instability recurs under the frozen profile.

## v48 prospective Flow60 holdout — frozen economic experiment

Protocol:
`docs/route-research-v48-prospective-flow60-holdout-protocol-2026-09-06.md`

Feature: `flow60_event_count`

Bins:
- LOW <=25
- MID 26..47
- HIGH >47

Primary horizon: **900s only**
Primary contrast: **LOW vs HIGH**
MID/300s/3600s cannot rescue primary failure.

Subcohort design remains frozen:
- A then B sequentially;
- cap 40 / minimum 30 research decisions each;
- provider pacing 650/1000/250ms;
- route-only BUY US$25 / 100bps;
- exact-output SELL horizons 300/900/3600;
- each A/B independently must pass systems/collector/lineage gates.

Primary support requires LOW>=5 and HIGH>=5 AVAILABLE at 900s in each A/B subcohort.

Primary PASS requires all:
1. median LOW > HIGH in A
2. median LOW > HIGH in B
3. median LOW > HIGH in ALL
4. LOW median >0 in A and B
5. LOW PF >1 in A and B
6. aggregate LOW PF >1
7. aggregate LOW mean_without_best >0

### Frozen systems amendment before fresh economic collection

The v48 runner now installs the prospectively validated v53 systems entry point **only during the v46 acquisition call** and restores the original globals afterward.

Frozen acquisition systems parameters include:
- Pump prepare workers 20;
- v51 stateful-ready priority;
- v52 3s hedge decision wall deadline with cleanup-capacity retention;
- v53 opportunistic-only prefetch.

Unchanged by this amendment:
- detector version/thresholds;
- Flow60 definition/bins;
- 900s primary horizon;
- LOW-vs-HIGH gate;
- support minimums;
- provider pacing;
- cap/minimum;
- route notional/slippage;
- forward label definition;
- `primary_gate_v48` evaluator.

Regression tests lock the wiring/restoration and frozen economic constants.

The Flow60 hypothesis is still **prospectively NOT_EVALUATED** because v53 was systems-only and started no forward collector.

## Scientific invariants

- discovery != validation
- systems PASS != economic edge
- wallet is post-episode evidence, not whitelist
- no backfill / retroactive enrollment
- missingness remains explicit
- first persisted trigger remains canonical
- no blind worker tuning
- route availability != assemblable transaction != landed transaction != fill
- route-only return != realized P&L
- no post-hoc v48 retuning
- systems-aborted run before collector produces no economic verdict
- no live money without robust forward evidence
- no hidden RPC oversubscription
- optional prefetch may be skipped; authoritative normalization may not be skipped
- v53 systems PASS freezes the acquisition profile; do not optimize it from future economic outcomes
- v48 FAIL/INCONCLUSIVE cannot be rescued by changing bins, horizon or hypothesis on the same holdout

## Immediate next action

**Stop systems latency tuning. Run the true fresh v48 prospective economic holdout on the validated v53 acquisition profile.**

Use a completely fresh base key; prior burned v48 keys must not be reused.

Recommended fresh key:
`route-research-prospective-holdout-20260907-48v53`

Command:
`python route_research_prospective_holdout_v48.py --run-key route-research-prospective-holdout-20260907-48v53`

This run may take through both A/B acquisition windows plus 3600s forward horizons. Do not interrupt after A if its gate passes; v46 will fail closed automatically if a subcohort fails.
