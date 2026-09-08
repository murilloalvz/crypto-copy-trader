# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico atual** do projeto. Histórico detalhado, protocolos e resultados ficam em `docs/`.

## Estado canônico

- Repositório: `murilloalvz/crypto-copy-trader`
- Branch científica base: `feat/exit-engine-v1`
- Head científico canônico pré-hardening: `94017d7d96231a5bcd05a6d2a69d8d2ee90e231c`
- Branch systems ativa: `fix/pumpswap-causal-throughput-v5`
- Modo: **PAPER / RESEARCH / READ ONLY**
- Tese: **market-first Opportunity Intelligence / Opportunity Engine**
- Laboratório principal: **Solana**
- Detector Solana: **FROZEN**
- Wallet: evidência pós-episódio, nunca whitelist de aquisição
- Fluxo oficial: `market -> radar -> causal episode -> enrichment -> research decision -> forward outcomes -> prospective validation -> execution research -> shadow`

## Status executivo

### Sistemas / aquisição

- v54 demand-only resolver admission: **historical accepted systems profile / PASS 11/11**
- Tailfix v1: cross-source token commit isolation implemented/tested
- Tailfix v2: bounded shared RPC transport + early decision release implemented/tested
- Tailfix v3: resolver latency class fixed live, but run failed 9/11 on persistence drain capacity
- Tailfix v4: persistence drain fixed live, but run failed 10/11 on PumpSwap causal latency due normalization/single-flight amplification
- Tailfix v5: **active systems correction; deterministic implementation/tests in progress/CI before live required**
- official Pump/PumpSwap p95 gate: **5s unchanged**
- preventive causal-stage warning: **4s p95**
- V5 sustained writer warning: queue-depth p95 >=80% of bounded PumpSwap persistence-worker reservoir, writer-result-wait p95 >=4s, or incomplete drain
- provider pacing: **650/1000/250ms frozen** for current route research
- route-only research: **US$25 / 100 bps / 300-900-3600s**

### Ciência econômica Solana

- v48 `flow60_event_count` prospective holdout: **FAIL / CLOSED**
- v55 causal discovery: **COMPLETE / CLEAN**
- v55 rank #1: `flow60_buy_share_pct`, favorable LOW / opposite HIGH
- v68 prospective Flow60 buy-share holdout: **IMPLEMENTED + PRE-REGISTERED / ECONOMIC VERDICT NOT OBTAINED**
- profitable prospective route-only selection edge: **NOT YET ESTABLISHED**

All systems-aborted v68 attempts stopped before valid forward economic collection.

Therefore:

`V68 ECONOMIC HYPOTHESIS = NOT_EVALUATED`

Do not classify Flow60 buy-share as PASS/FAIL from a systems abort. Never reuse a failed/partial acquisition key as a clean prospective cohort.

## Frozen systems gate — 11/11

Every systems-sensitive acquisition must pass all:

1. no worker/traceback errors
2. drops = 0
3. reference asset episodes = 0
4. radar coverage >=95%
5. true backlog <=5%
6. Pump p95 <=5s
7. PumpSwap causal pipeline p95 <=5s
8. hydration budget skips = 0
9. wallet/flow bundles nonempty
10. replay/audit valid
11. reservation superset violations = 0

Never relax the 5s thresholds to rescue an experiment.

## Historical accepted v54 profile

Run: `route-research-systems-stability-20260907-54`

- coverage 98.1%
- true backlog 1.913%
- Pump p95 ~1.906s
- PumpSwap p95 ~1.626s
- 11/11 PASS
- zero worker errors / drops / hydration skips / reservation-superset violations

This is historical evidence only; it does not guarantee future high-load acquisitions.

## Tailfix v3 — latency fixed, throughput failed

Protocol: `docs/pumpswap-latency-hardening-tailfix-v3-protocol-2026-09-08.md`

V3 moved pool-store lookup/write/reload off the asyncio event loop, retained same-pool single-flight until durable canonical identity, retained one physical SQLite writer, added `RESOLUTION > CAUSAL > AUDIT` admission, preserved bounded RPC transport and added causal-stage headroom telemetry.

Fresh v3 live systems result:

- PumpSwap received: 2,969
- persistence completed: 2,559
- radar processed: 2,551
- coverage: **90.4% FAIL**
- true backlog: **9.597% FAIL**
- Pump p95: **1.516s PASS**
- PumpSwap p95: **1.894s PASS**
- systems: **9/11**
- writer queue at deadline: 224
- all monitored V3 latency stages <4s
- `event_loop_store_calls=0`
- mapping sync started/admitted/completed 243/243/243
- transport violations=0
- same-token overlap violations=0

Interpretation: the latency class targeted by V3 was fixed; the remaining failure was sustained persistence drain capacity.

## Tailfix v4 — throughput fixed, normalization latency failed

Protocol: `docs/pumpswap-persistence-throughput-hardening-v4-protocol-2026-09-08.md`

V4 added:

- bounded SQLite resolution fairness: when causal work waits, at most one consecutive resolution grant goes first;
- optimistic pool mapping insert-first fast path;
- writer pressure instrumentation;
- V3 latency headroom retained;
- no detector/economic/RPC-worker/FIFO changes.

Fresh v4 live systems result on 2026-09-08:

- PumpSwap received / persisted / processed: **5,191 / 5,191 / 5,191**
- Pump received / persisted / processed: **2,107 / 2,107 / 2,107**
- coverage: **100.0% PASS**
- true backlog: **0.000% PASS**
- drops: 0
- worker errors: 0
- Pump p95: **2.463s PASS**
- PumpSwap p95: **19.066s FAIL**
- systems: **10/11**
- normalization->reservation p95: ~17.421s
- global prefix normalization barrier p95: ~17.412s
- resolver pool-lock hold p95: ~4.439s
- resolver durable mapping write p95: ~4.221s
- SQLite resolution admission p95: ~3.566s
- demand same-pool lock wait p95: ~14.934s
- RPC decision p95: ~0.534s; capacity/transport violations=0
- mapping writes: 560
- pool mapping collision reads: **238 / 560 = 42.5%**
- identity conflicts: 0
- writer submitted/completed: 5,191 / 5,191
- writer pending at close: 0
- writer queue high-water: 222
- writer result wait p95: ~2.030s

Interpretation:

**V4 fixed the V3 throughput failure.** It did not fail because SQLite could not drain. It failed because the critical identity/normalization path accumulated repeated same-pool work and SQLite-resolution admission waits; strict ingress-order reservation then amplified a few slow predecessors into a ~17s global barrier.

The 42.5% pool-mapping collision rate with zero identity conflicts is consistent with repeated writes of already-present same identities. Code review identified two concrete sources: historical promotion before the per-pool single-flight lock and older queued notifications re-resolving identities learned later in the same run.

Do not tune the v4 fairness constant by trial and error. The active V5 removes redundant demand while preserving the v4 fairness rule.

## Tailfix v5 — active causal-throughput hardening

Protocol: `docs/pumpswap-causal-throughput-hardening-v5-protocol-2026-09-08.md`

Main additions:

- `src/pumpswap_normalization_resolver_v5.py`
- `src/pumpswap_causal_normalization_v5.py`
- `src/pumpswap_writer_headroom_v5.py`
- `unified_market_route_research_smoke_tailfix_v5.py`
- `route_research_systems_stability_tailfix_v5.py`
- V5-specific deterministic tests

### V5 fixes failure classes instead of tuning one threshold

1. **Historical promotion is inside per-pool single-flight.** Concurrent notifications cannot all promote the same prior-run mapping independently.
2. **Current-run durable identity may be reused as delayed knowledge.** If notification time is 120 and mapping becomes known at 130, the normalized event is persisted at `observed_at=130`, never 120. This prevents redundant re-resolution without lookahead/backdating.
3. **Prior-run historical reuse stays strict.** A historical mapping observed after the notification cutoff is not reused as if it were already known.
4. **CreatePool identity persistence becomes async/off-loop.** The remaining synchronous pool-store write in normalization is removed from the asyncio event loop.
5. **V4 fairness stays unchanged.** V5 tests removal of redundant resolution demand instead of simultaneously changing the fairness knob.
6. **Writer pressure becomes sustained evidence.** Queue high-water remains diagnostic, but promotion uses queue-depth p95, writer-result-wait p95 and complete drain.
7. **One PumpSwap finalizer remains intentionally unchanged.** V4 ready-queue tails happened downstream of the ~17s normalization burst and are not yet proven to be an independent root cause. Do not increase finalizer workers preemptively.

### Delayed-availability causal rule

For a current-run mapping learned later than an already queued notification:

`effective_event_observed_at = max(notification.observed_at, mapping.observed_at)`

This means identity learned later can unblock old queued work only at the later availability timestamp. It cannot create evidence before the identity became known.

### V5 preventive classifications

`FAIL_TAILFIX_V5_UNCHANGED_11_GATE`
- frozen 11/11 failed;
- V68 remains blocked.

`HOLD_TAILFIX_V5_PREVENTIVE_HEADROOM`
- 11/11 passed but required preventive evidence is missing, at least one monitored causal stage p95 >=4s, sustained writer pressure is too high, writer result-wait p95 >=4s, or writer did not drain;
- V68 remains blocked.

`PASS_TAILFIX_V5_11_GATE_WITH_CAUSAL_AND_THROUGHPUT_HEADROOM`
- 11/11 PASS;
- all V3 monitored causal stages p95 <4s;
- V5 resolver/coalescing evidence present;
- writer queue-depth p95 <80% of persistence-worker reservoir;
- writer result-wait p95 <4s;
- writer fully drained;
- only this exact classification can be considered for a fresh V68 acquisition.

### Deterministic V5 requirements before live

Tests must prove:

- many concurrent historical same-pool requests -> one promotion;
- many older queued same-pool requests -> one network resolution;
- delayed current-run mapping reuse clamps observed availability forward;
- prior-run future historical mapping is not looked ahead;
- CreatePool identity is async + durable;
- V5 seams restore after success and exception;
- transient max queue spike alone does not HOLD;
- sustained queue p95 does HOLD;
- writer result-wait p95 >=4s does HOLD;
- incomplete drain does HOLD;
- official systems FAIL cannot be rescued;
- missing preventive evidence causes HOLD;
- full repository compile/tests green.

## v48 Flow60 prospective result — CLOSED

Classification: `FAIL_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS`

Frozen hypothesis:
- `flow60_event_count`
- LOW<=25 / MID=26..47 / HIGH>47
- primary 900s LOW vs HIGH

Do not retune bins/horizon or reuse the burned sample.

## v55 causal discovery — COMPLETE

Fresh discovery rows=79; A=39 / B=40; lineage/causal audit clean.

Exactly one candidate advanced:

- feature `flow60_buy_share_pct`
- LOW <=57.1429
- MID <=65.7143
- HIGH >65.7143
- favorable LOW / opposite HIGH

The v55 sample is burned for validation.

## v68 prospective Flow60 Buy-Share — ECONOMIC GATE OPEN, NOT RUNNING

Frozen:

- `flow60_buy_share_pct`
- LOW<=57.1429
- MID=(57.1429,65.7143]
- HIGH>65.7143
- favorable LOW / opposite HIGH
- primary horizon 900s
- support LOW>=5 and HIGH>=5 independently in A and B
- same detector / pacing / notional / slippage / horizons

PASS requires all:
1. LOW median > HIGH median A
2. LOW median > HIGH median B
3. LOW median > HIGH median ALL
4. LOW median >0 A and B
5. LOW PF >1 A and B
6. aggregate LOW PF >1
7. aggregate LOW mean_without_best >0

MID and 300/3600s are diagnostic only. No same-sample rescue if a valid v68 FAILS/INCONCLUSIVE.

## Other research tracks — isolated

- v56 Exceptional Trade Pre-Entry: causal scaffold ready
- v57 Market-First Social Evidence: causal scaffold ready / no approved live provider
- v58 Market-First Exit Geometry: measurement ready / no policy tuning
- v59 Multichain Market Contract: chain-aware adapter scaffold ready
- v60 Opportunity Wallet Convergence: pre-frozen-cohort evidence ready
- v61 Direct Funding Link: causal relationship primitive ready
- v62 Pons adapter/lifecycle: read-only scaffold ready
- v63 Exceptional Trade Outcome-Blind Controls: case-control matcher ready
- v64 Pons Exact Curve Progress: state-snapshot progress ready
- v65 Smart-Wallet Cohort Manifest: deterministic hashed cohort freeze ready
- v66 Protocol Deployment Capability Attestation: authority scaffold ready
- v67 Pons Raw Launch Quality Evidence: implemented / no score

These remain isolated from active Solana systems/V68 validation.

## Execution state

- funded executable BUY: **BLOCKED_BY_FUNDING**
- landing/fill validation: **NOT RELEASED**
- market-first exit policy: **NOT VALIDATED**
- shadow execution: **NOT RELEASED**
- live money: **NOT AUTHORIZED**

## Scientific invariants

1. discovery != validation
2. systems PASS != economic edge
3. route-only return != realized P&L
4. route availability != transaction assembly != landing != fill
5. first persisted trigger remains canonical
6. no lookahead / retroactive enrollment / causal backfill
7. missingness stays explicit
8. wallet is post-episode evidence only
9. distinct wallet addresses != independent traders
10. concentration/repetition != manipulation proof
11. failed prospective hypotheses are closed, not retuned
12. v48 sample is burned
13. v55 sample is discovery-only and burned for v68 validation
14. only v55 rank #1 may advance from that discovery sequence
15. v68 cutpoints/direction/horizon/gate remain frozen
16. v68 cannot be rescued with MID/another horizon/feature/new bins on the same sample
17. Solana detector thresholds remain frozen through v68
18. non-Solana research cannot contaminate v68 acquisition
19. historical chain data cannot receive fake historical `observed_at`
20. social `created_at` != causal availability
21. old Wave exit results do not validate market-first exits
22. no live money without robust forward + execution + shadow evidence
23. systems abort before forward collector = no economic verdict
24. never reuse partial/failed acquisition identities blindly
25. do not increase worker counts without proving causal independence and respecting ceilings
26. systems/headroom engineering cannot relax the frozen 5s gate
27. one physical SQLite writer remains authoritative unless a future architecture proves equivalent semantics
28. pool identity must be durable before publication
29. current-run delayed identity reuse must clamp event `observed_at` forward to mapping availability
30. prior-run historical identity remains subject to the original event causal cutoff
31. do not tune SQLite fairness by trial-and-error while duplicate identity demand remains possible

## Immediate next action

1. Require the final V5 head to be CI-green after all tests/docs/context changes.
2. Audit V5 diff to confirm detector/original V68/pacing/economic files remain untouched.
3. Run exactly one fresh 120s **systems-only** validation with `route_research_systems_stability_tailfix_v5.py`.
4. Do **not** run V68 economics yet.
5. Accept systems only on exact classification `PASS_TAILFIX_V5_11_GATE_WITH_CAUSAL_AND_THROUGHPUT_HEADROOM`.
6. If normalization/barrier is healthy but ready-queue p95 independently remains >=4s, then evaluate a separate bounded multi-finalizer design with per-asset FIFO and same-token proofs. Do not raise workers before that evidence.
7. If V5 passes, freeze the systems profile before preparing a new never-reused V68 acquisition identity.
