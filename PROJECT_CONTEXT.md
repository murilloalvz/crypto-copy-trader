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
- second v48 attempt on v53 profile: **A progressed, B SYSTEMS FAIL 10/11 BEFORE B FORWARD COLLECTION; BASE BURNED; ECONOMICS NOT_EVALUATED**
- v54 demand-only resolver admission: **IMPLEMENTED / LIVE NOT STARTED**
- v48 prospective Flow60 holdout: **FROZEN ECONOMIC PROTOCOL / NEW VIRGIN HOLDOUT BLOCKED ON v54 SYSTEMS VALIDATION**
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

## v53 opportunistic prefetch profile

Protocol:
`docs/route-research-v53-opportunistic-prefetch-protocol-2026-09-07.md`

v53 changed only optional ingress prefetch admission:
1. causal cache hit remains free;
2. if the same pool is already resolving, speculative prefetch skips instead of waiting;
3. if the expensive-resolution semaphore has no immediate slot, speculative prefetch skips instead of joining the capacity queue;
4. otherwise it calls the unchanged authoritative resolver path.

### v53 live systems validation

Run:
`route-research-systems-stability-20260907-53`

- PumpSwap received 3926
- Pump received 2494
- radar coverage **100.0%**
- true backlog **0.047%**
- Pump p95 **1867.4ms**
- PumpSwap p95 **2540.6ms**
- result **11/11**
- zero worker errors / drops / hydration-budget skips / reservation-superset violations
- no forward economic collector
- exact causal attribution complete
- demand capacity wait p95 0ms
- demand pool-lock wait p95 977.9ms

This validated v53 as a systems-only profile at that load, but did not prove stability under every later fresh economic subcohort load.

## Second v48 attempt — v53 profile failed in B

Base:
`route-research-prospective-holdout-20260907-48v53`

Because v46 reached B, A had already passed its required subcohort gate. B then failed the unchanged systems gate before B forward collection:

- Pump received 2445
- PumpSwap received 4297
- coverage **97.5%**
- true backlog **2.492%**
- Pump p95 **3050.8ms** — PASS
- PumpSwap p95 **7428.5ms** — FAIL
- result **10/11**
- no worker errors / drops / hydration budget skips / reservation-superset violations
- B forward collector did not start
- v48 acquisition classified `FAIL_V48_FROZEN_V46_ACQUISITION_PATH`

The entire base is burned for prospective validation. Do not inspect/reuse A economics to tune or rescue Flow60.

Same-run clocks:
- self ingress->normalization p95 540.1ms / max 11.080s
- global prefix normalization barrier p95 **4693.2ms**
- normalization->reservation p95 4735.1ms
- demand resolve max **7197.3ms**
- demand pool-lock wait p95 **2401.8ms** / max **6311.4ms**
- demand resolution-capacity wait p95 **0ms**
- resolver capacity waits **0**
- v52 hedge fetch p95 417.0ms
- v52 hedge cleanup p95 448.6ms

Interpretation: this run does not support a global resolution-capacity bottleneck. It does support a same-pool single-flight wait as a major candidate contributor to the long normalization holes.

Important code-level fact: admitted v53 ingress prefetch still calls the exact authoritative `resolver.resolve` path and therefore may own the same per-pool lock used by later causal demand. That speculative ownership is unnecessary for correctness.

## v54 demand-only resolver admission

Protocol:
`docs/route-research-v54-demand-only-resolver-admission-protocol-2026-09-07.md`

v54 removes only speculative resolver ownership from ingress prefetch.

Ingress candidate-pool observation remains diagnostic, but speculative prefetch:
- schedules zero resolver tasks;
- never calls `resolver.resolve`;
- never acquires per-pool lock or resolution semaphore;
- never consumes hydration budget;
- never persists mapping;
- never reserves assets;
- never creates detector evidence.

Authoritative normalization remains unchanged and still owns all cache/history/store/network resolution using the original causal `as_of`.

Frozen in v54:
- detector and episode semantics;
- global reservation order and same-asset FIFO;
- v51 stateful-ready finalizer priority;
- v52 wall deadline/cleanup semantics;
- Pump prepare workers 20;
- provider pacing 650/1000/250ms;
- route-only US$25 / 100bps;
- horizons 300/900/3600;
- v48 Flow60 bins/evaluator.

If v54 fails with high demand pool-lock wait, remaining HOL is authoritative demand-vs-demand single-flight, not speculative ingress work. Do not increase workers blindly or relax FIFO.

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

The Flow60 hypothesis remains prospectively **NOT_EVALUATED**. No failed systems acquisition may be used as an economic verdict.

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
- v48 FAIL/INCONCLUSIVE cannot be rescued by changing bins, horizon or hypothesis on the same holdout
- a partially successful A cannot rescue a B systems failure; the entire v48 base is burned
- systems changes must be justified by same-run dominant clocks, not trial-and-error worker tuning

## Immediate next action

**Do not rerun v48 yet. Do not reuse `route-research-prospective-holdout-20260907-48v53`.**

Run one fresh systems-only v54 after pulling the branch:

`python route_research_systems_stability_v54.py --run-key route-research-systems-stability-20260907-54`

Decision:
- 11/11 + no forward collector -> freeze v54 systems profile, amend v48 acquisition before any new economic data, then use a completely new v48 base key;
- fail -> use the same-run v53 demand pool-lock/capacity telemetry plus v50 barrier clocks. If demand pool-lock remains high with prefetch scheduled=0, investigate authoritative same-pool single-flight; otherwise classify the new dominant clock before changing architecture.
