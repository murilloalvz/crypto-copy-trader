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
- v51 stateful-priority finalizer: **IMPLEMENTED / CI PASS / LIVE FAIL 10/11**
- v51 live failure dominant measured clock: `global_sequence_barrier`; trace attribution incomplete because 24 reservation-order items remained at the frozen deadline
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
- dominant clock `global_sequence_barrier`
- global barrier p95 3550.7ms
- reservation->submit p95 996.0ms
- submit->dependency-ready p95 672.4ms

### v50c

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
- dominant clock `per_asset_dependency`

This proved that under high PumpSwap load a downstream ready/dependency bottleneck could dominate after the earlier upstream barrier had shrunk.

## v51 stateful-priority finalizer

Protocol:
`docs/route-research-v51-stateful-priority-finalizer-protocol-2026-09-07.md`

v51 changes ready-work selection only:
- one PumpSwap finalizer remains;
- one shared stateful commit executor remains;
- reservation/FIFO/completed cursors unchanged;
- global reservation order unchanged;
- detector/replay/as-of/provider/economics unchanged;
- stateful-ready work gets priority over already-demoted audit-only work;
- FIFO remains stable within each priority.

Regression CI proves:
- stateful work overtakes a backlog of 625 already-demoted audits;
- stateful FIFO remains stable;
- demoted audit FIFO remains stable;
- ambiguous same-asset followers cannot overtake predecessors;
- multi-asset work waits for every required cursor;
- ready backlog counts both classes;
- wrapper installs/restores scheduler globals.

### v51 live — 2026-09-07

Run:
`route-research-systems-stability-20260907-51`

Load:
- PumpSwap received 1570
- Pump received 1230
- radar coverage 99.1%
- true backlog 0.929%
- no worker errors / drops / hydration budget skips / reservation superset violations
- no forward collector

Systems gate:
- Pump p95 1577.1ms — PASS
- PumpSwap p95 **7658.1ms — FAIL**
- result **10/11**

v51 lane telemetry:
- stateful enqueued/dequeued 51/51
- demoted enqueued/dequeued 66/66
- stateful overtakes demoted 35
- stateful ready wait p95 2017.0ms
- demoted ready wait p95 3397.6ms
- ready backlogs drained to zero

Interpretation: the v51 priority mechanism is active and removes the v50c-style 9.47s ready-queue p95 in this run, but it does not solve the separate upstream global reservation watermark.

v50 tracer in the same run:
- ingress 1570
- normalization 1568
- reservations/rows 1544
- submit/skip 1544
- barrier_attribution_complete=False because 24 reservation-order items remained at deadline
- self ingress->normalization p95 461.2ms
- global prefix normalization barrier p95 **7654.6ms**
- post-prefix coordinator p95 233.3ms
- reservation->submit p95 844.8ms
- submit->dependency-ready p95 2118.0ms
- descriptive dominant clock `global_sequence_barrier`

Top blockers include normalization outliers around 6-10.5s that stall tens to >100 already-normalized successors. The worst listed blocker held 104 successors with 7.88s own normalization latency.

Scientific conclusion: v51 addresses one measured downstream HOL mechanism, but systems stability still fails because the architecture retains a second, independent HOL mechanism: the global ingress-sequence reservation watermark. A single slow/unresolved earlier normalization can delay unrelated later assets.

Important diagnostic semantics fix after this run:
- v51 wrapper now reports the frozen systems verdict independently from v50 trace completeness;
- incomplete exact v50 attribution no longer relabels an otherwise valid systems PASS/FAIL as merely `FAIL_V51_DIAGNOSTIC`;
- this is reporting correctness only and does not alter scheduling.

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

**Do not run v48. Do not rerun v51 blindly.**

The next systems task must target the measured global reservation watermark, not worker counts or detector/economic semantics.

Required design proof before implementation:
1. identify the earliest immutable PumpSwap conflict-domain key available at ingress (prefer pool identity if the protocol guarantees one pool maps immutably to one traded token/reference pair);
2. prove whether notifications from different conflict domains can reserve independently without allowing a later same-token notification to overtake an earlier unresolved one;
3. preserve CreatePool lifecycle ordering, multi-asset safety, exact replay semantics, and reservation superset checks;
4. replace the global watermark only with a narrower proven-safe conflict-domain watermark;
5. add adversarial tests where an earlier unresolved notification later resolves to the same asset as a successor;
6. CI and one systems-only live validation before v48.
