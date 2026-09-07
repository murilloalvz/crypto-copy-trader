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
- v48 prospective Flow60 holdout: **FROZEN / ECONOMICALLY NOT_EVALUATED**
- first fresh v48 attempt: **SYSTEMS ABORT 9/11 BEFORE FORWARD COLLECTION**
- v49 scheduling amendment: implemented / CI pass
- v50 + v50b: v49-profile historical **11/11** systems passes
- v50c: **SYSTEMS FAIL 10/11**, valid attribution, dominant clock `per_asset_dependency`
- v51 stateful-priority finalizer: **IMPLEMENTED / CI PASS / LIVE FAIL 10/11**
- v52 hedged RPC wall-deadline: **IMPLEMENTED / CI PASS / LIVE FAIL 10/11**
- v53 opportunistic prefetch + resolver wait telemetry: **IMPLEMENTED / CI PENDING / LIVE NOT STARTED**
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

## v50/v51 systems evidence

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

v51 gives stateful-ready work priority over already-demoted continuation audit while keeping one finalizer, one stateful commit executor, same-asset FIFO and global reservation order unchanged.

Live run:
`route-research-systems-stability-20260907-51`

- PumpSwap received 1570
- coverage 99.1%
- true backlog 0.929%
- Pump p95 1.577s — PASS
- PumpSwap p95 **7.658s — FAIL**
- result **10/11**
- stateful ready wait p95 2.017s
- demoted ready wait p95 3.398s
- global prefix normalization barrier p95 **7.655s**

Interpretation: v51 reduced the earlier downstream ready-queue HOL, but a separate upstream normalization/reservation HOL remained.

## v52 hedged RPC wall-deadline

Protocol:
`docs/route-research-v52-hedged-rpc-wall-deadline-protocol-2026-09-07.md`

v52 makes the existing 3s PumpSwap RPC timeout a true decision wall-clock bound for each hedged unknown-pool batch while preserving real network capacity until any already-running non-cancellable loser transport drains.

Live run:
`route-research-systems-stability-20260907-52`

Systems:
- elapsed 120.1s
- PumpSwap received 3161
- Pump received 1660
- coverage 97.1%
- true backlog 2.945%
- Pump p95 1.482s — PASS
- PumpSwap p95 **7.981s — FAIL**
- result **10/11**
- no worker errors / drops / hydration-budget skips / reservation-superset violations
- no forward collector

v52 transport evidence:
- wall deadline 3.000s
- deadline expirations **0**
- hedge fetch p95 **431.8ms**, max 663.6ms
- hedge cleanup p95 221.9ms, max 587.1ms
- v41 batch service p95 493.6ms, max 809.4ms

But normalization remained slow:
- self ingress->normalization p95 894.0ms, max **13.044s**
- global prefix normalization barrier p95 **5.786s**, max 12.166s
- normalization->reservation reconstructed p95 5.788s
- descriptive dominant clock `global_sequence_barrier`

Important conclusion:
**the external hedged RPC transport itself does not explain the 8-13s normalization tails in v52.** The v52 working hypothesis is rejected for this run.

Additional resolver/prefetch evidence:
- v49 prefetch scheduled 2629
- prefetch coalesced inflight 544
- singleflight waits 204
- network hydrations 242
- historical pool hits 157

The same resolver is shared by optional prefetch and authoritative normalization. Its ordering is:
`causal cache -> per-pool lock -> global resolution semaphore -> canonical resolver work`.

## v53 opportunistic prefetch

Protocol:
`docs/route-research-v53-opportunistic-prefetch-protocol-2026-09-07.md`

v53 does **not** change authoritative normalization.

It changes only optional v49 ingress prefetch admission:
1. causal cache hit remains free;
2. if the same pool is already resolving, speculative prefetch skips instead of waiting;
3. if the inherited global expensive-resolution semaphore has no immediate slot, speculative prefetch skips instead of joining the capacity queue;
4. otherwise it calls the exact existing `resolver.resolve` path.

A skipped prefetch does not:
- count as unresolved canonical trade;
- set negative cache;
- consume hydration budget;
- persist mapping;
- reserve assets;
- create detector evidence.

Why: optional speculative work must not queue ahead of causal normalization demand. This is narrower and safer than replacing the global reservation watermark.

### v53 same-run diagnostics

v53 also instruments the unchanged resolver synchronization path observationally:
- demand total resolve latency;
- prefetch total resolve latency;
- demand/prefetch per-pool lock wait;
- demand/prefetch resolution-capacity wait;
- capacity waiter high-water;
- hot pools by accumulated lock wait;
- prefetch admitted/skipped-capacity/skipped-pool-busy.

This is designed so one live v53 run remains diagnostic even if systems still fail.

## Frozen v48 prospective Flow60 hypothesis

Feature: `flow60_event_count`

Bins:
- LOW <=25
- MID 26..47
- HIGH >47

Primary horizon: **900s only**
Primary contrast: **LOW vs HIGH**
MID/300s/3600s cannot rescue primary failure.

Primary support requires LOW>=5 and HIGH>=5 AVAILABLE in each A/B subcohort.

Primary PASS requires all:
1. median LOW > HIGH in A
2. median LOW > HIGH in B
3. median LOW > HIGH in ALL
4. LOW median >0 in A and B
5. LOW PF >1 in A and B
6. aggregate LOW PF >1
7. aggregate LOW mean_without_best >0

This hypothesis remains prospectively untested economically.

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
- do not replace global ordering unless a narrower conflict domain is proven safe
- optional prefetch may be skipped; authoritative normalization may not be skipped

## Immediate next action

**Do not run v48. Do not rerun v52.**

First require CI green for v53 code/tests.

After CI PASS, run exactly one fresh systems-only v53:

`python route_research_systems_stability_v53.py --run-key route-research-systems-stability-20260907-53`

Decision:
- 11/11 + no forward collector + v51/v52/v53 diagnostics present -> stop latency tuning and wire the validated profile into frozen v48 acquisition;
- fail -> do not reroll blindly; classify the same-run remaining delay using demand pool-lock wait, demand capacity wait and total resolver latency before any further architecture change.
