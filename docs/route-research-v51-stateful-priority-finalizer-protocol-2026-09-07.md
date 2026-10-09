# v51 Stateful-Priority PumpSwap Finalizer Protocol

Date: 2026-09-07
Mode: **PAPER / RESEARCH / READ ONLY**

## Problem measured before v51

v50c ran the v49 scheduling profile under a materially larger PumpSwap burst:

- PumpSwap received: 7141 / 120s
- systems gate: 10/11
- Pump p95: 2.077s PASS
- PumpSwap pipeline p95: 15.508s FAIL
- exact ingress/normalization/reservation attribution: 7141/7141
- submit/skip attribution: 7039/7141 = 98.572%
- global sequence barrier p95: 1.699s
- reservation->submit p95: 1.209s
- submit->dependency-ready p95: 12.988s
- finalize ready-queue wait p95: 9.467s
- finalizer service p95: 1.2ms
- v42/v34 demoted pending jobs: 625
- 12 assets accounted for 50% of causal wait; 42 for 90%.

The dominant clock moved downstream from v50b's global normalization barrier to the stateful dependency/finalizer path.

## Code-level cause being amended

The v34/v42 scheduler proves some pending detector-positive followers are continuation-only after a canonical episode exists. For such a demotion it:

1. removes the pending job from the stateful dependency indexes;
2. converts its issued per-asset ticket into a causal skip;
3. advances only contiguous skipped tickets;
4. retains a finalizer acknowledgement so the continuation still becomes audit-visible;
5. enqueues that already-demoted continuation into the same ready queue used by genuinely stateful work.

The v19 runtime has one PumpSwap finalizer consumer. Therefore a burst of already-demoted continuation audits can sit ahead of an unrelated stateful episode opener. Delaying that opener delays the immutable episode-cache proof for its own followers, which can recursively increase per-asset dependency wait even though the work ahead of it can no longer mutate episode state.

The continuation finalizer is safe to defer relative to stateful work because the v27 continuation path, once the episode cache proves the canonical window, only performs cache reads, constructs the canonical hit, and enqueues an append-only continuation trigger to the dedicated thread-owned writer. It cannot open or reshape an episode. The same proof used by v34/v42 remains the only condition that grants this lower priority.

## v51 change

v51 changes **ready-work selection only**.

- Keep exactly one PumpSwap finalizer worker.
- Keep the same single shared stateful commit executor.
- Keep all per-asset reservation tickets and completed cursors.
- Keep v34/v42 proof-based demotion semantics.
- Keep the global reservation order.
- Keep detector, replay, persistence, episode, as-of, provider and economic semantics.

The ready queue becomes stable two-priority ordering:

1. priority 0: work that still owns a stateful reservation acknowledgement;
2. priority 1: work already present in `demoted_finalizer_acks`, whose stateful ticket has been converted to a causal skip and which remains only for continuation audit/hit finalization.

FIFO is preserved within each priority by an insertion sequence counter.

A ready/running job is never reclassified by v51. Ambiguous work remains stateful. A same-asset stateful successor cannot become ready until the existing completed-cursor condition is satisfied. Multi-asset reservations still require every asset cursor.

## What v51 deliberately does NOT do

v51 does not:

- add finalizer workers;
- parallelize stateful episode commits;
- bypass the shared cross-source commit executor;
- drop or sample continuation audits;
- change detector thresholds;
- change v48 Flow60 bins/horizon/gate;
- change provider pacing;
- extend the frozen 120s deadline;
- retry or backfill missing data;
- collect forward SELL outcomes during systems validation.

## Required regression proof before live

Tests must prove:

1. stateful ready work can overtake a backlog of already-demoted continuation audits;
2. FIFO remains stable among stateful ready jobs;
3. FIFO remains stable among demoted audit jobs;
4. ambiguous same-asset stateful followers cannot overtake their predecessor;
5. multi-asset causality remains blocked until every predecessor cursor advances;
6. ready backlog accounting includes both priorities;
7. v50 causal-clock instrumentation still observes the scheduler lifecycle;
8. the v51 wrapper restores patched globals after execution.

A deterministic synthetic burst test should include hundreds of demoted continuations so the priority mechanism is exercised without relying on live market load.

## Live systems-only gate

A fresh v51 run remains subject to the unchanged v43 11/11 systems gate, including PumpSwap pipeline p95 <=5s.

Additional v51 requirements:

- no forward collector starts;
- v50 exact barrier attribution remains complete;
- v50 later lifecycle attribution remains >=95%;
- v51 scheduler diagnostic is present;
- no scheduler/instrumentation fatal error.

Classifications:

- `PASS_V51_STATEFUL_PRIORITY_SYSTEMS_PROFILE`
- `FAIL_V51_STATEFUL_PRIORITY_SYSTEMS_PROFILE`
- `FAIL_V51_SYSTEMS_ONLY_GUARD`
- `FAIL_V51_DIAGNOSTIC`

A v51 PASS is systems evidence only. It does not validate Flow60 profitability, executable fills, shadow or live money.

## Frozen economic hypothesis

The v48 hypothesis remains untouched and economically NOT_EVALUATED prospectively:

- feature `flow60_event_count`
- LOW <=25 / MID 26..47 / HIGH >47
- primary horizon 900s
- primary contrast LOW vs HIGH
- original support/replication/heavy-tail gate.

Do not run v48 until v51 systems validation passes.