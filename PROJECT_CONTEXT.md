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
- v50 + v50b: v49-profile **11/11** systems passes
- v50b dominant clock: `global_sequence_barrier`
- v50c: **SYSTEMS FAIL 10/11**, valid attribution, dominant clock `per_asset_dependency`
- v51 stateful-priority finalizer amendment: **PREREGISTERED / IMPLEMENTED / CI PASS / LIVE PENDING**
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

## v50 causal clock evidence

Attribution acceptance:
- exact ingress/normalization/reservation/attributed-row coverage for global barrier;
- submit/skip coverage >=95% for later lifecycle comparison;
- no post-deadline drain.

### v50b

Systems **11/11**:
- coverage 99.5%
- true backlog 0.482%
- Pump p95 1.838s
- PumpSwap p95 4.002s

Dominant clock:
`global_sequence_barrier`

Key p95:
- global barrier 3550.7ms
- reservation->submit 996.0ms
- submit->dependency-ready 672.4ms

### v50c

Run:
`route-research-systems-diagnostic-20260907-50c`

Load:
- PumpSwap 7141 / 120s
- Pump 2161 / 120s

Systems:
- coverage 98.9%
- true backlog 1.097%
- Pump p95 2077.4ms — PASS
- PumpSwap p95 **15507.9ms — FAIL**
- result **10/11**
- no forward collector

Attribution:
- ingress/normalization/reservation/rows 7141/7141
- submit/skip 7039/7141 = 98.572%
- causal attribution acceptable

p95 clocks:
- self normalization 277.4ms
- global sequence barrier 1699.0ms
- reservation->submit 1208.5ms
- submit->dependency-ready **12988.4ms**
- finalize ready queue **9466.5ms**
- finalizer service only 1.2ms

Dominant clock:
`per_asset_dependency`

v42/v34 evidence:
- demoted pending jobs 625
- only 12 assets accounted for 50% of causal wait
- 42 accounted for 90%
- max waiting jobs on one asset 27

Conclusion: v49 reduced the upstream normalization barrier enough that a downstream scheduling problem became dominant under high PumpSwap load.

## v51 stateful-priority finalizer

Protocol:
`docs/route-research-v51-stateful-priority-finalizer-protocol-2026-09-07.md`

Files:
- `src/pumpswap_stateful_priority_scheduler_v51.py`
- `unified_market_route_research_smoke_v51.py`
- `route_research_systems_stability_v51.py`
- `tests/test_pumpswap_stateful_priority_scheduler_v51.py`
- `tests/test_unified_market_route_research_smoke_v51.py`

### Code-level finding

v34/v42 already proves some pending followers are continuation-only. On demotion it:
- removes them from stateful dependency indexes;
- converts their per-asset ticket to causal skip;
- advances only contiguous skipped tickets;
- retains finalizer ack only for audit/hit visibility;
- then enqueues those already-demoted audits into the same ready queue as genuinely stateful work.

v19 has one PumpSwap finalizer consumer. Therefore a burst of demoted continuation audits can sit ahead of an unrelated stateful opener. Delaying that opener delays episode-cache proof for its own followers, recursively increasing same-asset dependency waits.

The continuation path is safe to defer relative to stateful work because, after the inherited v34 proof succeeds, v27 only reads the immutable episode cache and enqueues append-only continuation audit. It cannot open/reshape an episode.

### v51 amendment

v51 changes **ready-work selection only**:
- one PumpSwap finalizer remains;
- one shared stateful commit executor remains;
- reservation/FIFO/completed cursors unchanged;
- global reservation order unchanged;
- detector/replay/as-of/provider/economics unchanged;
- stateful-ready work gets priority 0;
- already-demoted audit-only work gets priority 1;
- FIFO is stable within each priority via insertion sequence.

No additional finalizer workers were added. No parallel stateful commits were introduced.

### Regression proof

CI passed with tests proving:
- stateful work overtakes a backlog of **625** already-demoted audits;
- stateful FIFO remains stable;
- demoted audit FIFO remains stable;
- ambiguous same-asset followers cannot overtake predecessors;
- multi-asset work waits for every required cursor;
- ready backlog counts both classes;
- wrapper installs/restores scheduler globals.

This is a semantic scheduling proof, not a profitability result.

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

## Immediate next action

**Do not run v48. Do not rerun v50.**

Pull latest and run one fresh v51 systems-only validation:

`python route_research_systems_stability_v51.py --run-key route-research-systems-stability-20260907-51`

v51 PASS requires:
- unchanged systems gate **11/11**;
- no forward collector;
- valid v50 causal attribution;
- v51 scheduler diagnostic present;
- no scheduler/instrumentation fatal error.

If PASS:
1. freeze v51 as the validated acquisition systems profile;
2. wire it into a new v48 acquisition wrapper without changing the v48 evaluator;
3. regression-test Flow60 bins/horizon/gate and provider pacing;
4. CI;
5. use a completely fresh v48 base run key;
6. collect the true prospective holdout.

If FAIL:
- do not reroll v48;
- inspect v51 lane telemetry and v50 clocks from that same run before any further change.
