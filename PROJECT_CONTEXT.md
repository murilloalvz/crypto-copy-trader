# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico atual** do projeto. Histórico detalhado, protocolos e resultados ficam em `docs/`.

## Estado canônico

- Repositório: `murilloalvz/crypto-copy-trader`
- Branch científica base: `feat/exit-engine-v1`
- Head científico canônico pré-hardening: `94017d7d96231a5bcd05a6d2a69d8d2ee90e231c`
- Branch systems ativa: `fix/pumpswap-persistence-throughput-v4`
- Modo: **PAPER / RESEARCH / READ ONLY**
- Tese: **market-first Opportunity Intelligence / Opportunity Engine**
- Laboratório principal: **Solana**
- Segundo laboratório em preparação: **Robinhood Chain / Pons v2**
- Fluxo: `market -> radar -> causal episode -> enrichment -> research decision -> forward outcomes -> prospective validation -> execution research -> shadow`
- Detector Solana permanece congelado.
- Wallet é evidência pós-episódio, nunca whitelist de aquisição.

## Status executivo atual

### Sistemas / aquisição

- v54 demand-only resolver admission: **accepted historical systems profile / PASS 11/11**
- Tailfix v1: **cross-source token commit isolation implemented/tested**
- Tailfix v2: **bounded shared RPC transport + decision release implemented/tested**
- Tailfix v3: **LATENCY OBJECTIVE ACHIEVED LIVE, but systems gate 9/11 because persistence drain capacity failed**
- Tailfix v4: **persistence throughput hardening implemented + tests/CI green before final context update / LIVE SYSTEMS VALIDATION NEXT**
- detector thresholds: **FROZEN**
- provider pacing: **650/1000/250ms frozen for current route research**
- route-only research: **US$25 / 100 bps / 300-900-3600s**
- official Pump/PumpSwap p95 gate: **5s unchanged**
- preventive latency warning: **4s per monitored causal stage**
- preventive writer-pressure warning: **PumpSwap writer queue high-water >=80% of persistence-worker reservoir**

### Ciência econômica Solana

- v48 Flow60 prospective holdout: **FAIL ECONOMIC HYPOTHESIS / CLOSED**
- v55 Causal Early-Opportunity Discovery: **COMPLETE / CLEAN**
- v55 selected rank #1: **`flow60_buy_share_pct`, favorable LOW, opposite HIGH**
- v68 prospective Flow60 buy-share holdout: **IMPLEMENTED + PRE-REGISTERED / ECONOMIC VERDICT NOT OBTAINED**
- profitable route-only opportunity-selection edge: **NOT YET ESTABLISHED**

### v68 interpretation

All attempted fresh v68 acquisitions that reached the relevant gate aborted **before forward economic collection** because the frozen systems acquisition path did not pass.

Therefore:

`V68 ECONOMIC HYPOTHESIS = NOT EVALUATED`

Do not classify Flow60 buy-share as PASS/FAIL from an acquisition abort. Do not reuse a failed/partial acquisition key as a clean prospective cohort.

## Frozen systems gate — 11/11

All must pass in systems-sensitive acquisition runs:

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

## v54 accepted historical systems profile

Canonical systems-only run:
`route-research-systems-stability-20260907-54`

- radar coverage 98.1%
- true backlog 1.913%
- Pump p95 ~1.906s
- PumpSwap p95 ~1.626s
- systems 11/11
- zero worker errors / drops / hydration skips / reservation-superset violations

This remains historical accepted evidence, not proof that every future/high-load acquisition is stable.

## Tailfix v3 — live result and lesson

Protocol:
`docs/pumpswap-latency-hardening-tailfix-v3-protocol-2026-09-08.md`

V3 changes:

1. Resolver SQLite current/historical lookup, durable mapping write and canonical reload run off the asyncio event loop.
2. Same-pool single-flight remains held until identity is durably written and canonically reloaded; no identity is published early.
3. SQLite retains one physical writer with explicit `RESOLUTION > CAUSAL > AUDIT` admission.
4. Tailfix v2 bounded RPC transport remains authoritative.
5. Same-token cross-source serialization remains authoritative.
6. Stage-by-stage latency decomposition and promotion-only 4.0s headroom warning were added.

Fresh live v3 systems run on 2026-09-08:

- PumpSwap received: 2,969
- persistence completed: 2,559
- radar processed: 2,551
- radar coverage: **90.4% FAIL**
- true backlog: **9.597% FAIL**
- Pump p95: **1.516s PASS**
- PumpSwap pipeline p95: **1.894s PASS**
- systems gate: **9/11**
- writer queue at deadline: **224**
- PumpSwap ingress backlog: 154
- PumpSwap in-flight persistence: 256
- writer batch avg size: 6.71 / 32
- writer batch service p95: ~92.9ms
- writer queue wait p95: ~929ms
- global prefix normalization barrier p95: ~1.624s
- reservation->submit p95: ~0.788s
- submit->dependency-ready p95: ~1.586s
- stateful ready queue p95: ~1.371s
- demoted ready queue p95: ~1.518s
- all monitored v3 latency stages <4s
- `event_loop_store_calls=0`
- mapping sync started/admitted/completed = 243/243/243; inflight=0
- transport-limit violations=0
- same-token overlap violations=0
- reservation-superset violations=0
- drops=0 / worker errors=0

Interpretation:

**V3 fixed the latency class it targeted.** The remaining failure was sustained persistence drain capacity: the individual PumpSwap event path was healthy, but the system could not empty all accepted work before the frozen 120s deadline. Do not continue tuning resolver/RPC latency without new evidence.

## Tailfix v4 — active systems gate

Protocol:
`docs/pumpswap-persistence-throughput-hardening-v4-protocol-2026-09-08.md`

Main code:
- `src/sqlite_write_admission.py`
- `src/pumpswap_pool_mapping_fastpath_v4.py`
- `src/pumpswap_writer_pressure_v4.py`
- `unified_market_route_research_smoke_tailfix_v4.py`
- `route_research_systems_stability_tailfix_v4.py`

### What v4 changes

1. **Bounded SQLite resolution fairness**: pool-identity writes remain higher priority, but when a causal writer is already waiting, at most one consecutive resolution write may go first before the causal writer gets a turn.
2. **One physical SQLite writer remains invariant**. V4 does not create parallel SQLite writers.
3. **Optimistic pool-mapping fast path**: fresh `(run_key,pool)` identity uses `INSERT OR IGNORE` first; replay/conflict SELECT runs only after a UNIQUE collision.
4. Earliest `observed_at`, equal-time lexical tie-break, conflict auditing and durable-before-publication remain unchanged.
5. **Writer-pressure telemetry** measures submissions, completions, pending work, queue high-water, queue-before-close and microbatch utilization.
6. V3 latency headroom remains active.
7. No detector, economics, pacing, FIFO, replay/as-of, worker-count or RPC-ceiling retuning.

### V4 preventive classifications

`FAIL_TAILFIX_V4_UNCHANGED_11_GATE`
- official frozen 11/11 failed;
- no v68 allowed.

`HOLD_TAILFIX_V4_PREVENTIVE_HEADROOM`
- 11/11 passed, but latency headroom or writer-pressure headroom is too thin/missing;
- no v68 allowed.

`PASS_TAILFIX_V4_11_GATE_WITH_LATENCY_AND_THROUGHPUT_HEADROOM`
- official 11/11 passed;
- every monitored causal latency stage p95 <4s;
- writer-pressure report present;
- writer queue high-water <80% of the PumpSwap persistence-worker reservoir;
- this is the only v4 classification that may unlock a new fresh v68 acquisition.

The writer-pressure rule is promotion-only engineering. It does not replace the official coverage/backlog/latency gates.

### V4 deterministic evidence

V4 tests cover:

- bounded resolution fairness and one active SQLite writer;
- historical/default admission behavior preserved outside v4;
- fresh mapping INSERT fast path;
- earliest same-identity replay semantics;
- conflicting identity audit/canonical replacement;
- equal-time lexical tie-break;
- writer submissions/completions/pending/batch telemetry;
- v4 systems seam installation/restoration;
- PASS/HOLD/FAIL promotion guard behavior.

Latest implementation head before this context update:
`a3c4da025f6a4e5623c088349f1b2e1a84a17abd`

GitHub Actions compile + full unit-test suite: **SUCCESS**.

The v4 diff from parent v3 head `e762171...` is systems-isolated: new systems/tests/docs plus deliberate `src/sqlite_write_admission.py` fairness support. The frozen detector and original v68 scientific files are unchanged.

## v48 Flow60 prospective result — CLOSED

Classification:
`FAIL_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS`

Frozen hypothesis:
- `flow60_event_count`
- LOW<=25 / MID=26..47 / HIGH>47
- primary 900s LOW vs HIGH

Absolute Flow60 event count did not replicate prospectively. Do not retune bins/horizon or reuse the burned sample.

## v55 Causal Early-Opportunity Discovery — COMPLETE

Fresh base:
`route-research-early-opportunity-discovery-20260907-55`

- rows=79; A=39 / B=40
- causal/lineage audit clean
- exactly one eligible primary 900s candidate advanced: `flow60_buy_share_pct`
- LOW <=57.1429
- MID <=65.7143
- HIGH >65.7143
- favorable=LOW / opposite=HIGH

The v55 discovery sample is burned for validation.

## v68 Prospective Flow60 Buy-Share Holdout — ECONOMIC GATE STILL OPEN

Protocol:
`docs/route-research-v68-prospective-flow60-buy-share-holdout-protocol-2026-09-08.md`

Frozen:
- feature `flow60_buy_share_pct`
- LOW<=57.1429
- MID=(57.1429,65.7143]
- HIGH>65.7143
- favorable=LOW
- opposite=HIGH
- primary horizon=900s
- LOW>=5 and HIGH>=5 independently in A and B
- same detector / pacing / notional / slippage / horizons

Primary PASS requires all:
1. LOW median > HIGH median A
2. LOW median > HIGH median B
3. LOW median > HIGH median ALL
4. LOW median >0 A and B
5. LOW PF >1 A and B
6. aggregate LOW PF >1
7. aggregate LOW mean_without_best >0

MID and 300/3600s are diagnostic only. If a valid future v68 FAILS or is INCONCLUSIVE, do not mine the same sample for rescue.

## Preparatory research tracks

- v56 Exceptional Trade Pre-Entry: causal scaffold ready
- v57 Market-First Social Evidence: causal scaffold ready / no live provider
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

These stay isolated from active Solana v68 validation.

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
24. do not reuse partial/failed acquisition identities blindly
25. do not increase worker counts without proving causal independence and respecting ceilings
26. systems/headroom engineering cannot relax the frozen 5s gate
27. one physical SQLite writer remains authoritative unless a future architecture change proves equivalent causal/durability semantics
28. a pool identity must be durable before publication

## Immediate next action

1. Require the final `fix/pumpswap-persistence-throughput-v4` head to be CI-green.
2. Run exactly one fresh 120s **systems-only** validation using `route_research_systems_stability_tailfix_v4.py`.
3. Do **not** run v68 economics yet.
4. Accept systems only on exact classification `PASS_TAILFIX_V4_11_GATE_WITH_LATENCY_AND_THROUGHPUT_HEADROOM`.
5. If V4 FAILS, use writer-pressure/fairness + inherited V3 latency telemetry to identify the remaining capacity stage; do not retune economics.
6. If V4 PASSES, freeze this systems profile and only then prepare a fresh, never-reused v68 acquisition identity.
