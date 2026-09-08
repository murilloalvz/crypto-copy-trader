# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico atual** do projeto. Histórico detalhado, protocolos e resultados ficam em `docs/`.

## Estado canônico

- Repositório: `murilloalvz/crypto-copy-trader`
- Branch científica base: `feat/exit-engine-v1`
- Head científico canônico pré-hardening: `94017d7d96231a5bcd05a6d2a69d8d2ee90e231c`
- Branch systems ativa: `fix/pumpswap-latency-hardening-v3`
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
- Tailfix v3: **preventive latency hardening implemented / CI green before final docs / LIVE SYSTEMS VALIDATION PENDING**
- detector thresholds: **FROZEN**
- provider pacing: **650/1000/250ms frozen for current route research**
- route-only research: **US$25 / 100 bps / 300-900-3600s**
- official Pump/PumpSwap p95 gate: **5s unchanged**
- Tailfix v3 promotion-only early warning: **4s per monitored causal stage**

### Ciência econômica Solana

- v48 Flow60 prospective holdout: **FAIL ECONOMIC HYPOTHESIS / CLOSED**
- v55 Causal Early-Opportunity Discovery: **COMPLETE / CLEAN**
- v55 selected rank #1: **`flow60_buy_share_pct`, favorable LOW, opposite HIGH**
- v68 prospective Flow60 buy-share holdout: **IMPLEMENTED + PRE-REGISTERED / ECONOMIC VERDICT NOT OBTAINED**
- profitable route-only opportunity-selection edge: **NOT YET ESTABLISHED**

### Critical interpretation of the attempted v68 run

The attempted fresh v68 acquisition aborted **before forward economic collection** because the frozen systems gate failed on PumpSwap tail latency.

Therefore:

`V68 ECONOMIC HYPOTHESIS = NOT EVALUATED`

Do **not** classify Flow60 buy-share as failed from that run.

Observed systems failure pattern included high throughput/coverage with tail amplification rather than simple backlog. Prior diagnostics showed hot causal predecessors, global normalization barrier, reservation-to-submit and per-asset dependency/ready-queue clocks as important sources depending on load. This triggered systems hardening, not economic retuning.

Do not reuse the failed/partial run key as if it were a clean prospective cohort.

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
- speculative resolver tasks scheduled = 0

This remains historical accepted evidence, not proof that every future/high-load acquisition will stay below 5s.

## Tailfix v3 — current systems gate

Protocol:
`docs/pumpswap-latency-hardening-tailfix-v3-protocol-2026-09-08.md`

Main code:
- `src/pumpswap_resolver_latency_hardening_v3.py`
- `src/pumpswap_latency_headroom_v3.py`
- `src/sqlite_write_admission.py`
- `src/cross_source_token_commit_lanes.py`
- `unified_market_route_research_smoke_tailfix_v3.py`
- `route_research_systems_stability_tailfix_v3.py`

### What v3 changes

1. Resolver SQLite current/historical lookup, durable mapping write and canonical reload are offloaded from the asyncio event loop.
2. Same-pool single-flight remains held until identity is durably written and canonically reloaded; no in-memory identity is published early.
3. SQLite still has one physical writer, but admission priority is now `RESOLUTION > CAUSAL > AUDIT`, so pool identity needed to unblock normalization cannot sit behind lower-criticality writes indefinitely.
4. Tailfix v2 bounded RPC transport remains authoritative; no hidden transport ceiling increase.
5. Same-token cross-source serialization remains authoritative.
6. Commit-lane implementation supports proven bounded concurrency, but the active v3 profile remains Pump=1 / PumpSwap=1 because the inherited upstream PumpSwap path still has one finalizer consumer. Do not claim fake capacity by only raising downstream workers.
7. V3 decomposes latency into resolver/store/network/barrier/dependency/queue/commit clocks.
8. V3 adds a promotion-only headroom rule at 4.0s (80% of the immutable 5s p95 gate).

### Tailfix v3 classifications

`FAIL_TAILFIX_V3_UNCHANGED_11_GATE`
- official frozen 11/11 failed;
- no economic run allowed.

`HOLD_TAILFIX_V3_LATENCY_HEADROOM`
- 11/11 passed, but headroom report missing or at least one monitored causal stage p95 >=4.0s;
- no economic run allowed.

`PASS_TAILFIX_V3_11_GATE_WITH_HEADROOM`
- 11/11 passed;
- headroom report present;
- every monitored causal stage p95 <4.0s;
- systems profile may be considered for a **fresh** v68 acquisition.

The 4s rule is preventive systems engineering. It does not replace or weaken the scientific 5s systems gate and is not an economic criterion.

### Required v3 live invariants

A promotable systems run requires all of:

- official 11/11 PASS;
- classification `PASS_TAILFIX_V3_11_GATE_WITH_HEADROOM`;
- PumpSwap p95 <=5s;
- no monitored causal stage >=4s;
- `event_loop_store_calls=0`;
- `durable_mapping_writes == historical_store_hits + network_resolutions`;
- transport limit violations = 0;
- no hidden RPC oversubscription;
- same-token overlap violations = 0;
- reservation superset violations = 0.

### CI evidence

Implementation head `de89bfc230a290b2d48d7cdf61166126ebc1ddf1` completed GitHub Actions successfully:

`Ran 997 tests ... OK`

The compare against canonical `94017d7...` is systems-isolated: all files are added systems/tests/docs except the deliberate modification of `src/sqlite_write_admission.py`. The frozen detector, original v68 feature builder and original v68 runner are not modified.

This CI evidence proves deterministic regression/invariant tests. It does **not** prove live Solana/RPC/SQLite latency; one fresh 120s systems-only run is still required.

## v48 Flow60 prospective result — CLOSED

Classification:
`FAIL_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS`

Frozen hypothesis:
- `flow60_event_count`
- LOW<=25 / MID=26..47 / HIGH>47
- primary 900s LOW vs HIGH

Absolute Flow60 event count did not replicate prospectively as a robust maturity/stage proxy. Do not retune bins, switch to MID/horizon or reuse the burned sample.

## v55 Causal Early-Opportunity Discovery — COMPLETE

Fresh base:
`route-research-early-opportunity-discovery-20260907-55`

Causal audit:
- rows total=79
- A=39
- B=40
- lineage violations=0
- missing decisions/episodes/hazard/entry quotes=0
- official decision mutations=0
- augmentation failures=0
- feature clock violations=0
- classification=`PASS_V55_CAUSAL_DISCOVERY_DATASET`

Exactly one eligible primary 900s candidate survived the pre-registered bridge:

- feature `flow60_buy_share_pct`
- family direction
- coverage A/B=100%
- LOW <=57.1429
- MID <=65.7143
- HIGH >65.7143
- favorable=LOW
- opposite=HIGH

The v55 79-row discovery sample is burned for validation.

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
- minimum available support LOW>=5 and HIGH>=5 independently in A and B
- same detector / pacing / notional / slippage / horizons

Primary PASS requires all:
1. LOW median > HIGH median A
2. LOW median > HIGH median B
3. LOW median > HIGH median ALL
4. LOW median >0 A and B
5. LOW PF >1 A and B
6. aggregate LOW PF >1
7. aggregate LOW mean_without_best >0

MID and 300/3600s are diagnostic only and cannot rescue 900s.

If a **valid** future v68 acquisition FAILS or is INCONCLUSIVE, do not retune bins, switch horizon, mine favorable subcohorts or promote another v55 feature from the same discovery sequence.

## Preparatory research tracks

- v56 Exceptional Trade Pre-Entry: **causal scaffold ready**
- v57 Market-First Social Evidence: **causal scaffold ready / no live provider**
- v58 Market-First Exit Geometry: **measurement ready / no policy tuning**
- v59 Multichain Market Contract: **chain-aware adapter scaffold ready**
- v60 Opportunity Wallet Convergence: **pre-frozen-cohort evidence ready**
- v61 Direct Funding Link: **causal relationship primitive ready**
- v62 Pons adapter/lifecycle: **read-only scaffold ready**
- v63 Exceptional Trade Outcome-Blind Controls: **case-control matcher ready**
- v64 Pons Exact Curve Progress: **state-snapshot progress ready**
- v65 Smart-Wallet Cohort Manifest: **deterministic hashed cohort freeze ready**
- v66 Protocol Deployment Capability Attestation: **authority scaffold ready**
- v67 Pons Raw Launch Quality Evidence: **implemented / no score**

These tracks stay isolated from the active Solana v68 validation until scientifically appropriate.

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
14. v55 rank #1 is the only candidate that may advance from that discovery sequence
15. v68 cutpoints/direction/horizon/gate remain frozen
16. v68 failure cannot be rescued by MID, another horizon/feature or new bins on the same sample
17. Solana detector thresholds remain frozen through v68
18. non-Solana research cannot contaminate Solana v68 acquisition
19. historical chain data cannot receive fake historical `observed_at`
20. social `created_at` != causal availability
21. old Wave exit results do not validate market-first exits
22. no live money without robust forward + execution + shadow evidence
23. systems abort before forward collector = no economic verdict
24. do not reuse partial/failed acquisition identities blindly
25. do not increase worker counts without proving causal independence and respecting existing ceilings
26. Tailfix/headroom engineering cannot relax the frozen 5s gate

## Immediate next action

1. Require the newest `fix/pumpswap-latency-hardening-v3` head to be CI-green.
2. Run exactly one fresh 120s **systems-only** Tailfix v3 validation using `route_research_systems_stability_tailfix_v3.py`.
3. Do **not** run v68 economics yet.
4. If classification is `PASS_TAILFIX_V3_11_GATE_WITH_HEADROOM`, accept the systems profile and then plan a fresh v68 acquisition identity, kept separate from the previous aborted acquisition.
5. If classification is HOLD or FAIL, there is still no v68 economic verdict. Use the v3 stage telemetry to fix the dominant systems clock before another economic cohort.

If the next dominant stage is ready/finalizer queueing, consider bounded multi-finalizer concurrency for disjoint assets/tokens only after changing the upstream consumer and proving per-asset FIFO/same-token safety. If normalization/global-prefix barrier remains dominant, stay on resolver/store/barrier ownership instead. Never raise workers by trial and error.
