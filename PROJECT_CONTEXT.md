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
- v50 and v50b: recent v49-profile **11/11** systems passes
- v50b dominant clock: `global_sequence_barrier`
- v50c: **SYSTEMS FAIL 10/11**, diagnostic attribution valid, dominant clock changed to `per_asset_dependency`
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

## v49 scheduling amendment

Systems-only changes:
- Pump prepare workers 12 -> 20 from measured capacity;
- PumpSwap immutable pool identity prefetch begins at ingress;
- same resolver/cache/history/single-flight/hydration budget/hedging;
- canonical normalization, persistence, reservation, FIFO, detector and research semantics unchanged.

## v50 causal clock attribution

Acceptance rule:
- exact ingress/normalization/reservation/attributed-row coverage required for global-barrier attribution;
- submit/skip coverage >=95% required for later causal-clock comparison;
- no post-deadline drain because that would alter the frozen 120s systems semantics.

### v50b

Systems **11/11**:
- coverage 99.5%
- true backlog 0.482%
- Pump p95 1.838s
- PumpSwap p95 4.002s

Tracer:
- ingress/normalization/reservation/attributed 3357/3357
- submit/skip 3345/3357 = 99.643%
- global prefix normalization barrier p95 3550.7ms
- reservation->submit p95 996.0ms
- submit->dependency-ready p95 672.4ms
- dominant clock `global_sequence_barrier`

### v50c — latest live result

Run:
`route-research-systems-diagnostic-20260907-50c`

Load:
- PumpSwap received 7141
- Pump received 2161
- radar coverage 98.9%
- true backlog 1.097%
- drops 0
- worker errors 0
- hydration budget skips 0
- reservation superset violations 0

Systems gate:
- Pump p95 2077.4ms — PASS
- PumpSwap causal pipeline p95 **15507.9ms — FAIL**
- result **10/11**
- forward economic collector did not start

Important: this is a **systems failure**, not an economic Flow60 verdict.

Exact v50c attribution:
- ingress 7141
- normalization 7141
- reservations 7141
- attributed rows 7141
- submit/skip 7039 = 98.572%
- barrier_attribution_complete=True
- causal_clock_attribution_acceptable=True

Clocks p95:
- self ingress->normalization 277.4ms
- global prefix normalization barrier 1699.0ms
- post-prefix reservation coordinator 245.0ms
- normalization->reservation 1791.4ms
- reservation->submit 1208.5ms
- submit->dependency-ready **12988.4ms**
- finalize ready queue 9466.5ms
- finalize start end-to-end 15492.8ms
- pipeline 15507.9ms

Dominant clock:
`per_asset_dependency`

Causal asset concentration:
- 338 assets had reservations
- 83 assets experienced causal wait
- only 12 assets accounted for 50% of total causal wait
- 42 assets accounted for 90%
- max waiting jobs on one asset 27

Examples of hot causal-wait assets had p95 waits around 11.5s–16.6s.

Interpretation:
- v49 fixed enough of the earlier normalization/reservation problem that under v50c the dominant bottleneck moved downstream;
- at high PumpSwap load, strict per-asset causal FIFO/dependency chains create long tails and ready-queue delay;
- global sequence barrier is no longer the dominant p95 clock in this run;
- two prior 11/11 passes are insufficient to declare the profile stable for prospective economic acquisition because v50c reproduced a load-sensitive 10/11 failure.

Do **not** solve this by relaxing FIFO, dropping hot-asset observations, changing detector thresholds, extending the deadline, or rerolling until an 11/11 appears.

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
- no worker tuning by blind trial/error
- route availability != assemblable transaction != landed transaction != fill
- route-only return != realized P&L
- no post-hoc v48 retuning
- systems-aborted run before collector produces no economic verdict
- no live money without robust forward evidence

## Immediate next work

**Do not run v48. Do not rerun v50 blindly.**

Next engineering task is a systems-only v51 diagnostic/fix focused on the measured downstream bottleneck:

`reservation/submit -> per-asset causal dependency -> finalize ready queue`

Required investigation before changing scheduling:
1. inspect the exact v42/v34 stateful-only finalizer and per-asset dependency implementation;
2. separate unavoidable same-asset FIFO wait from avoidable global/single-finalizer ready-queue wait;
3. determine why `finalize_ready_queue_wait_ms` reached p95 9.47s while finalizer service itself was p95 1.2ms;
4. preserve strict same-asset causality and cross-source trigger serialization;
5. preregister the smallest scheduling-only change if an avoidable queueing clock is proven;
6. add regression tests for same-asset FIFO and no cross-asset causal contamination;
7. CI;
8. validate systems-only before touching v48 acquisition.

Do not optimize Flow60/economics from v50c.
