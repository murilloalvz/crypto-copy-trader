# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico atual** do projeto. Histórico detalhado, protocolos e resultados ficam em `docs/`.

## Estado canônico

- Repositório: `murilloalvz/crypto-copy-trader`
- Branch relevante: `feat/exit-engine-v1`
- Modo: **PAPER / RESEARCH / READ ONLY**
- Tese: **market-first Opportunity Intelligence / Opportunity Engine**
- Laboratório principal validado: **Solana**
- Segundo laboratório em preparação: **Robinhood Chain / Pons v2**
- Fluxo conceitual: `market -> radar -> causal episode -> enrichment -> research decision -> forward outcomes -> prospective validation -> execution research -> shadow`
- Detector Solana permanece congelado.
- Wallet é evidência pós-episódio, nunca whitelist de aquisição.

## Status atual

### Sistemas / aquisição

- v42 Unified Market Latency: **FORMAL PASS 11/11**
- v44 route-only provider pacing: **PASS 11/11**
- v54 demand-only resolver admission: **LIVE SYSTEMS PASS 11/11 / profile aceito**
- detector thresholds: **FROZEN**
- provider pacing: **650/1000/250ms frozen for current route research**
- route-only research: **US$25 / 100 bps / 300-900-3600s**

### Ciência econômica Solana

- v46 dual prospective discovery: **COMPLETE**
- v47 causal feature discovery: **COMPLETE**
- v48 Flow60 prospective holdout: **FAIL ECONOMIC HYPOTHESIS / CLOSED**
- v55 Causal Early-Opportunity Discovery: **COMPLETE / CLEAN / ONE ELIGIBLE 900s CANDIDATE**
- v55 rank #1: **`flow60_buy_share_pct`, favorable LOW, opposite HIGH**
- v68 prospective Flow60 buy-share holdout: **IMPLEMENTED + PRE-REGISTERED / FRESH LIVE RUN NOT STARTED YET**
- profitable route-only opportunity-selection edge: **NOT YET ESTABLISHED**

### Preparatory research tracks

- v56 Exceptional Trade Pre-Entry: **CAUSAL SCAFFOLD READY**
- v57 Market-First Social Evidence: **CAUSAL SCAFFOLD READY / NO LIVE PROVIDER**
- v58 Market-First Exit Geometry: **PURE MEASUREMENT READY / NO POLICY TUNING**
- v59 Multichain Market Contract: **CHAIN-AWARE EDGE-ADAPTER SCAFFOLD READY**
- v60 Opportunity Wallet Convergence: **PRE-FROZEN-COHORT EVIDENCE READY**
- v61 Direct Funding Link: **CAUSAL DEPLOYER/PARTICIPANT LINK PRIMITIVE READY**
- v62 Pons adapter/lifecycle contract: **READ-ONLY SCAFFOLD READY**
- v63 Exceptional Trade Outcome-Blind Controls: **CASE-CONTROL MATCHER READY**
- v64 Pons Exact Curve Progress: **STATE-SNAPSHOT PROGRESS READY**
- v65 Smart-Wallet Cohort Manifest: **DETERMINISTIC HASHED COHORT FREEZE READY**
- v66 Protocol Deployment Capability Attestation: **DEPLOYMENT/CAPABILITY AUTHORITY READY**
- v67 Pons Raw Launch Quality Evidence: **IMPLEMENTED / TESTS GREEN / NO SCORE**

### Execution state

- funded executable BUY: **BLOCKED_BY_FUNDING**
- landing/fill validation: **NOT RELEASED**
- market-first exit policy: **NOT VALIDATED**
- shadow execution: **NOT RELEASED**
- live money: **NOT AUTHORIZED**

## Frozen systems gate

All must pass in systems-sensitive acquisition runs:
1. no worker errors
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

Do not relax the 5s thresholds to rescue an experiment.

## v54 accepted systems profile

Canonical systems-only run:
`route-research-systems-stability-20260907-54`

- radar coverage 98.1%
- true backlog 1.913%
- Pump p95 ~1.906s
- PumpSwap p95 ~1.626s
- systems 11/11
- zero worker errors / drops / hydration skips / reservation-superset violations
- speculative resolver tasks scheduled = 0

v54 changes only speculative resolver ownership; authoritative normalization remains unchanged.

## v48 Flow60 prospective result — CLOSED

Result:
`docs/route-research-v48-prospective-flow60-result-2026-09-07.md`

Base:
`route-research-prospective-holdout-20260907-48v54`

Validity:
- A=40
- B=40
- rows=80
- causal audit PASS
- lineage violations=0

Frozen primary hypothesis:
- feature `flow60_event_count`
- LOW<=25 / MID=26..47 / HIGH>47
- primary 900s LOW vs HIGH

Classification:
`FAIL_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS`

Interpretation: absolute Flow60 event count did not replicate prospectively as a robust maturity/stage proxy. Do not retune, switch to MID, switch horizon, or reuse the sample for replacement validation.

## v55 Causal Early-Opportunity Discovery — COMPLETE

Protocol:
`docs/route-research-v55-causal-early-opportunity-discovery-protocol-2026-09-07.md`

Result:
`docs/route-research-v55-causal-early-opportunity-discovery-result-2026-09-08.md`

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

900s detector-population baseline for this sample:
- A: n=29 median=+3.929% mean=+1.355% PF=1.054
- B: n=33 median=+1.460% mean=+29.177% PF=2.204
- ALL: n=62 median=+2.525% mean=+16.164% PF=1.655

Do not call this detector edge: B contained a +1157.888% winner and its mean_without_best was negative in the underlying descriptive report. Right-tail dependence remains material.

### v55 selected candidate

The candidate-selection bridge was pre-registered before results:
`docs/route-research-v55-candidate-selection-to-holdout-protocol-2026-09-07.md`

Exactly one eligible 900s candidate survived:

- feature: `flow60_buy_share_pct`
- family: direction
- feature coverage: A=100%, B=100%
- published value-only bins:
  - LOW <=57.1429
  - MID <=65.7143
  - HIGH >65.7143
- HIGH-minus-LOW median delta A=-10.660 pp
- HIGH-minus-LOW median delta B=-8.360 pp
- HIGH-minus-LOW median delta ALL=-8.639 pp
- support A `(LOW=10,HIGH=6)`
- support B `(LOW=11,HIGH=10)`

Pre-registered mapping therefore selects:
- favorable = **LOW**
- opposite = **HIGH**

Status remains discovery-only. The 79 v55 rows are burned for validation.

## v68 Prospective Flow60 Buy-Share Holdout — NEXT ECONOMIC GATE

Protocol:
`docs/route-research-v68-prospective-flow60-buy-share-holdout-protocol-2026-09-08.md`

Code:
- `src/route_research_prospective_flow60_buy_share_v68.py`
- `route_research_prospective_flow60_buy_share_holdout_v68.py`
- `tests/test_route_research_prospective_flow60_buy_share_v68.py`
- `tests/test_route_research_prospective_flow60_buy_share_v68_wiring.py`

Frozen:
- feature `flow60_buy_share_pct`
- LOW<=57.1429
- MID=(57.1429,65.7143]
- HIGH>65.7143
- favorable=LOW
- opposite=HIGH
- primary horizon=900s
- minimum available support LOW>=5 and HIGH>=5 independently in A and B
- same v46 fresh A/B acquisition
- same v54 systems profile
- same detector / pacing / route notional / slippage / horizons

Primary PASS requires all:
1. LOW median > HIGH median A
2. LOW median > HIGH median B
3. LOW median > HIGH median ALL
4. LOW median >0 A and B
5. LOW PF >1 A and B
6. aggregate LOW PF >1
7. aggregate LOW mean_without_best >0

MID and 300/3600s are diagnostic only and cannot rescue 900s.

If v68 FAILS or is INCONCLUSIVE, do not switch to another v55 feature or retune this sample.

## v56-v67 supporting research map

### Exceptional Trade Intelligence

v56 reconstructs only evidence strictly known before a reference entry:
- chain_time < entry_chain_time
- observed_at < entry_observed_at
- same-second target activity excluded

v63 supplies outcome-blind same-wallet controls so future analysis can ask:
> what existed before a huge winner that did not exist before a behaviorally comparable ordinary entry by the same trader?

Historical backfill remains retrospective discovery unless knowledge-time lineage can be proved.

### Wallet convergence

v60 asks only after market detection whether a cohort frozen **before** the episode participated.

v65 makes the cohort manifest deterministic/hashable and chain-aware. A prospective cohort must be committed before the first eligible observation.

Distinct addresses do not prove independent traders.

### Funding / integrity

v61 distinguishes direct pre-launch deployer→participant native funding from other transfer directions/assets while preserving chain_time and observed_at.

A direct link is evidence of a financial relationship, not proof of insider ownership, wash trading, manipulation, or fraud.

Participation concentration/repetition alone must never be called manipulation.

### Robinhood / Pons

v59 establishes chain-aware identity and adapter-at-the-edge architecture.

v62-v67 prepare Pons as the second research laboratory without altering Solana acquisition.

Important semantics:
- Pons v2 lifecycle is bonding curve -> swept -> graduated pool, not Solana Pump semantics;
- graduation may be two-phase;
- quote asset may be native or approved ERC-20;
- thresholds are per-launch/per-quote economics, not one universal 4.2 ETH assumption;
- v64 curve maturity uses exact causal state snapshot `realQuoteReserve / graduationThreshold`, not trade-count reconstruction;
- internal fee/buyback behavior means summing external trades alone is not authoritative for curve progress;
- v66 requires deployment address + capability provenance before a protocol-specific feature is trusted;
- v67 stores raw launch quality evidence only, with no weighted FIRE/WATCH/SKIP score;
- recipient-specific opening-tax evidence may be used only when the deployed capability is authoritative under v66.

Current research seed from public Pons tooling is useful for feature discovery only: dev-buy share, creator economics, exemption/bundle declaration, deployer history, repeated launch fingerprints, early buyer breadth, current opening tax and exact curve progress. Third-party heuristic weights are not imported.

### Social

v57 preserves exact token-mint linkage and knowledge-time social evidence. No approved live social provider exists yet.

### Exit

v58 defines market-first route-path geometry: coverage, MFE, MAE, time to peak/trough, giveback and MFE capture.

Missing route observations remain missing; no interpolation/backfill/zero conversion.

The old Wave exit engine does not validate market-first exits.

## Working edge thesis — research map, not strategy

The strongest current conceptual target is:

`movement begins`
`+ participation/buyer structure is favorable`
`+ multiple pre-frozen useful wallet archetypes converge`
`+ deployer/funding/launch integrity is acceptable`
`+ lifecycle stage still leaves room`
`+ route remains executable`
`+ exit preserves rare right-tail winners`

Each component must prove incremental value separately before combinations are tested. Do not build a weighted Frankenstein score from discovery features.

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
15. v68 cutpoints/direction/horizon/gate are frozen before fresh data
16. v68 failure cannot be rescued by MID, other horizon, another v55 feature, or new bins on the same sample
17. Solana detector thresholds remain frozen through v68
18. non-Solana research cannot contaminate Solana v68 acquisition
19. historical chain data cannot be assigned fake historical observed_at
20. social created_at != causal availability
21. old Wave exit results do not validate market-first exits
22. no live money without robust forward + execution + shadow evidence

## Immediate next action

First require the new v68 head to be CI-green.

Then run exactly one fresh v68 base, for example:

`route-research-prospective-flow60-buy-share-20260908-68`

Do not reuse v55 run keys or any prior v48 base.

If v68 PASSes, the next gate is **execution realism + market-first exit/shadow research**, not immediate live money.

If v68 FAILs or is INCONCLUSIVE, close the flow60 buy-share hypothesis and move economic discovery to an independent research family (Exceptional Trade / wallet convergence / Pons lifecycle), without mining v68 for a rescue feature.
