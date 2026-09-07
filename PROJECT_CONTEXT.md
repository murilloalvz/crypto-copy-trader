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
- v53 opportunistic prefetch profile: **LIVE SYSTEMS PASS 11/11**, but later v48 B failed 10/11 under heavier load
- second v48 attempt on v53 profile: **BASE BURNED; ECONOMICS NOT_EVALUATED**
- v54 demand-only resolver admission: **LIVE SYSTEMS PASS 11/11**
- v48 prospective Flow60 holdout: **FROZEN ECONOMIC PROTOCOL / v54 ACQUISITION WIRED / NEW VIRGIN HOLDOUT READY**
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

## v53 -> v54 systems evidence

The v48-v53 B failure showed:
- PumpSwap p95 7428.5ms — FAIL
- demand pool-lock wait p95 2401.8ms / max 6311.4ms
- demand resolution-capacity wait p95 0ms
- resolver capacity waits 0

Admitted v53 ingress prefetch still used the authoritative `resolver.resolve` path and could own the same per-pool lock later needed by causal demand.

v54 removes only speculative resolver ownership. Ingress candidate-pool observation remains diagnostic, but speculative prefetch schedules zero resolver tasks and never calls `resolver.resolve`, acquires pool locks/capacity, consumes hydration budget, persists mappings, reserves assets or creates detector evidence. Authoritative normalization remains unchanged.

Fresh systems-only v54 run:
`route-research-systems-stability-20260907-54`

Result:
- PumpSwap received 3887
- Pump received 2020
- radar coverage **98.1%**
- true backlog **1.913%**
- Pump p95 **1906.1ms** — PASS
- PumpSwap p95 **1625.9ms** — PASS
- systems **11/11**
- zero worker errors / drops / hydration-budget skips / reservation-superset violations
- v54 speculative resolver tasks scheduled **0**
- skipped speculative candidate pools **3890**
- no forward collector

The v50 exact causal trace was incomplete at the frozen deadline, so no exact dominant causal-clock claim is made from this run. Systems PASS is independent of trace completeness.

v54 is now the accepted acquisition profile for the next untouched v48 economic holdout.

## Frozen v48 prospective Flow60 hypothesis

Feature: `flow60_event_count`

Bins:
- LOW <=25
- MID 26..47
- HIGH >47

Primary horizon: **900s only**
Primary contrast: **LOW vs HIGH**
MID/300s/3600s cannot rescue primary failure.

Subcohort design remains frozen:
- A then B sequentially
- cap 40 / minimum 30 research decisions each
- provider pacing 650/1000/250ms
- route-only BUY US$25 / 100bps
- exact-output SELL horizons 300/900/3600
- each A/B independently must pass systems/collector/lineage gates

Primary support requires LOW>=5 and HIGH>=5 AVAILABLE at 900s in each A/B subcohort.

Primary PASS requires all:
1. median LOW > HIGH in A
2. median LOW > HIGH in B
3. median LOW > HIGH in ALL
4. LOW median >0 in A and B
5. LOW PF >1 in A and B
6. aggregate LOW PF >1
7. aggregate LOW mean_without_best >0

The Flow60 hypothesis remains prospectively **NOT_EVALUATED**. Failed systems acquisitions do not count as economic evidence.

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
- a partially successful A cannot rescue a B systems failure; the whole base is burned
- v48 FAIL/INCONCLUSIVE cannot be rescued by changing bins, horizon or hypothesis on the same holdout
- v54 changes systems scheduling only; detector/economic semantics remain frozen

## Immediate next action

Pull the current branch and run one completely fresh v48 prospective holdout on the validated v54 systems profile.

Do **not** reuse either prior v48 base.

Recommended fresh base key:
`route-research-prospective-holdout-20260907-48v54`

Command:
`python route_research_prospective_holdout_v48.py --run-key route-research-prospective-holdout-20260907-48v54`

Do not inspect partial A economics if B later fails systems. Only a complete fresh A+B path may produce the v48 economic verdict.
