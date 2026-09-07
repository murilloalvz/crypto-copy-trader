# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado permanece em `docs/`.

## Estado canônico

- Repositório: `murilloalvz/crypto-copy-trader`
- Branch: `feat/exit-engine-v1`
- Modo: **PAPER / RESEARCH / READ ONLY**
- Tese ativa: **market-first Solana Opportunity Intelligence / Opportunity Engine**

Fluxo oficial:
`market -> radar -> causal episode T0 -> flow/wallet/context -> executable entry/hazard -> official decision_as_of -> executable forward outcomes -> economic validation -> shadow`

Trilha paralela sem funding:
`fresh episode -> on-chain hazard -> route-only BUY -> research_decision_as_of -> route-only SELL +5/+15/+60 -> descriptive causal evaluation`

Status atual:
- Pump acquisition: **PASS**
- PumpSwap acquisition + causal resolution: **PASS**
- Detector / episode / replay hardening: **PASS**
- Unified Market Latency v42: **FORMAL PASS 11/11**
- v44-size provider-paced acquisition path: **SYSTEMS PASS 11/11**
- Solana RPC minimal hazard v37 semantics: **PASS**
- Route-only Jupiter research plumbing: **PASS**
- v45 larger single acquisition 50/40: **REJECTED — SYSTEMS FAIL 10/11**
- v46 dual prospective 40/30 subcohorts: **LIVE PASS / 2 OF 2 SUBCOHORTS PASS / AGGREGATE DESCRIPTIVE READY**
- v47 offline causal feature review: **CODE/CI PASS / OFFLINE RUN PENDING**
- Funded executable BUY assembly: **BLOCKED_BY_FUNDING**
- Solana Tracker hazard: **BLOCKED_BY_PROVIDER_CREDITS**
- Official `decision_as_of`: **PENDING / UNFROZEN**
- Official executable forward outcomes: **PENDING**
- Economic edge: **NOT ESTABLISHED**
- Shadow/live money: **NOT RELEASED**
- Não iniciar coleta oficial de 12h ainda.

## Invariantes congelados

- Histórico exploratório de P&L não é prova causal de edge.
- Detector/estratégia não mudam por resultado econômico pequeno ou conveniente.
- Wallet é evidência pós-episódio, nunca acquisition whitelist.
- `route available != assemblable transaction != landed transaction != fill`.
- Route-only outcome não é wallet realized P&L.
- Missing/failure permanece explícito; nunca substituir por candle/quote posterior.
- Primeiro trigger-to-episode **persistido** permanece canônico.
- No retroactive enrollment / no backfill.
- PASS de systems latency não significa profitability PASS.
- Não aumentar workers por tentativa; primeiro localizar o relógio dominante.
- Features de wallet/hazard/flow permanecem descritivas até valor incremental out-of-sample.
- Nenhum live money sem forward evidence robusta + gate explícito.

## Detector congelado

`src/market_opportunity_radar.py`
Version: `market_opportunity_radar_v1_1_tx_aware`

- fast window 30s
- baseline 300s
- >=6 fast events
- >=4 known unique wallets
- established: >=3 baseline events + >=3x acceleration
- fresh causal token age <=120s
- com tx identity coverage 100%: >=4 unique fast tx
- direction descritiva

Nenhum threshold foi alterado pelos resultados v40-v47.

## Systems latency

Gate congelado ALL:
1. no worker/traceback errors
2. drops 0
3. reference asset episodes 0
4. coverage >=95%
5. true backlog `(received - radar_processed) / received` <=5%
6. Pump radar p95 <=5s
7. PumpSwap causal pipeline p95 <=5s
8. hydration budget skips 0
9. wallet/flow bundles não vazios
10. replay/audit sem fatal corruption
11. reservation superset violations 0

Canonical v42 same-run PASS:
- coverage 100.0%
- true backlog 0%
- Pump p95 1.842s
- PumpSwap p95 3.302s
- result **11/11**

v44 also PASS at the frozen practical sampling size:
- coverage 99.8%
- true backlog 0.222%
- Pump p95 1.733s
- PumpSwap p95 3.808s
- result **11/11**

v45 increased one acquisition from cap40 to cap50 and failed:
- systems **10/11**
- PumpSwap p95 **9.512s**
- collector correctly did not start

Conclusion: cap50 single-acquisition sampling is rejected. Do not relax the gate or increase workers to rescue it. Gain sample over time using v44-size acquisitions.

## Funding / official executable path

Frozen official Jupiter BUY:
- provider `jupiter_swap_v2_order`
- purpose `entry_executable_buy_v1`
- USDC input
- US$25
- 100bps
- public taker only
- no signing/execute

Persisted readiness showed route availability but no assembled transaction because configured taker had insufficient funds. Official funded assemblability remains **BLOCKED_BY_FUNDING**.

## Hazard

Validated free provider:
`solana_rpc_mint_hazard_v1 / token_hazard_minimal_v1`

Core:
- token program
- decimals
- supply
- mint authority
- freeze authority
- Token-2022 metadata when exposed

`getTokenLargestAccounts` is optional auxiliary evidence and is **token-account concentration**, not holder/owner concentration.

## Route-only causal research

Funding-free research path only. It never freezes official `decision_as_of` and never signs/submits.

Frozen semantics:
- BUY: USDC -> token, taker=None, route-only/non-executable
- notional: US$25
- slippage parameter: 100bps
- horizons: 300 / 900 / 3600 seconds
- SELL: exact entry output amount token -> USDC, taker=None
- missing Jupiter route remains explicit missingness

Provider pacing frozen from v44:
- hazard starts: 650ms
- BUY starts: 1000ms
- SELL starts: 250ms
- no retry/backfill

## v40 microcohort

First causal route-only microcohort, n10 per horizon. All horizons `INCONCLUSIVE_SAMPLE_LT_30`. Results were strongly negative/heavy-tailed and are retained only as early evidence; no detector tuning was allowed.

## v44 larger single valid cohort

Live `route-research-forward-cohort-20260906-44`:
- systems 11/11
- hazard 40/40 AVAILABLE
- entry 39/40 AVAILABLE
- 39 decisions / 117 schedules
- collector terminal 117/117
- target lateness p95 1s
- lineage 0
- all 24 forward errors were Jupiter HTTP400 `Failed to get quotes`, zero SELL429

Economics:
- 300s n35: mean -5.016%, median -4.082%, PF0.766
- 900s n29: mean -14.497%, median -28.814%, PF0.653
- 3600s n29: mean -36.457%, median -42.599%, PF0.245

Overall remained inconclusive because 900/3600 had n29.

## v46 dual prospective subcohorts — canonical descriptive sample

Files:
- `route_research_forward_cohort_v46.py`
- `src/route_research_multi_evaluation_v46.py`
- `tests/test_route_research_forward_cohort_v46.py`

Base run:
`route-research-forward-cohort-20260906-46`

Subcohorts:
- `...-46-A`
- `...-46-B`

Protocol:
- two complete v44-size subcohorts sequentially;
- each cap40 / minimum30;
- each independently requires systems11/11, >=30 decisions, terminal collector, lateness p95<=2s, lineage0;
- one failed subcohort cannot be rescued by the other;
- aggregation preserves run identity and missingness.

Live final result:
- subcohorts passed: **2/2**
- aggregate lineage violations: **0**
- descriptive-ready horizons: **3/3**
- classification: **READY_FOR_DESCRIPTIVE_RESEARCH_REVIEW**

Aggregate A+B:
- 300s: scheduled79, AVAILABLE74, coverage93.7%, positive45.95%, mean -7.324%, median -0.233%, PF0.536, mean_without_best -9.309%
- 900s: scheduled79, AVAILABLE69, coverage87.3%, positive56.52%, mean -1.458%, median +1.363%, PF0.932, mean_without_best -5.771%
- 3600s: scheduled79, AVAILABLE66, coverage83.5%, positive39.39%, mean -27.359%, median -29.786%, PF0.371, mean_without_best -30.252%

Subcohort B at 900s was mildly positive (n36, mean +1.927%, median +1.490%, PF1.087), while aggregate 900s remained slightly negative with PF<1. Therefore 900s is the only near-break-even horizon, but the evidence is **not a replicated positive edge**. 300s and 3600s remain clearly weak in the current unfiltered detector population.

Economic edge remains **NOT ESTABLISHED**.

## v47 offline causal feature review

Protocol:
`docs/route-research-offline-causal-feature-review-v47-protocol-2026-09-06.md`

Files:
- `src/route_research_feature_review_v47.py`
- `route_research_feature_review_v47.py`
- `tests/test_route_research_feature_review_v47.py`

Status: **CODE/CI PASS / OFFLINE RUN PENDING**.

Purpose: use the already-complete v46 A/B sample for descriptive feature discovery without making a new provider call or changing the strategy.

Strict feature cutoff:
`feature_observed_at <= research_decision_as_of`

The dataset is rebuilt causally at each persisted decision clock using existing dual-clock builders. Any later hazard/quote/flow evidence is rejected rather than backfilled.

Predeclared feature families:

Episode:
- trigger kind
- trigger direction
- decision delay

Flow:
- 30s event count
- 30s buy share
- 30s wallet identity coverage
- 30s notional imbalance
- 30s return
- 60s event count
- 300s event count

Current wallet participation:
- participant count
- repeated event share

On-chain hazard:
- mint authority present
- freeze authority present
- Token-2022
- extensions count

Entry route surface:
- price impact
- liquidity when provider metadata exists

Numeric bins are derived from **feature values only**, never returns. They are descriptive bins, not trading thresholds.

A feature comparison is marked `SAME_DIRECTION_DESCRIPTIVE_ONLY` only when comparable groups have >=5 AVAILABLE labels per group in both A and B and median-return separation points in the same direction in A, B and aggregate. Disagreement is explicit instability.

A/B are already observed and therefore are **not a virgin holdout** for a new rule. v47 may propose a hypothesis candidate, but cannot validate it. Any selected hypothesis must be frozen before a fresh v48 out-of-sample cohort.

## Immediate next work

Run v47 OFFLINE over the completed v46 database:

`python route_research_feature_review_v47.py --base-run-key route-research-forward-cohort-20260906-46`

Interpretation order:
1. causal dataset audit must pass with lineage0 and no official decision mutation;
2. inspect feature coverage before interpreting effects;
3. compare direction of median-return separation in A and B;
4. reject unstable/low-support features;
5. treat same-direction features only as hypothesis candidates;
6. if one candidate is scientifically defensible, freeze it in a separate protocol before a fresh v48 holdout.

Do not run another economic acquisition before reviewing v47 output.

## Shadow / live

- systems canonical v44-size path: **PASS**
- v45 cap50 single path: **REJECTED — SYSTEMS FAIL**
- v46 causal sample: **DESCRIPTIVE READY**
- v47: **CODE/CI PASS / OFFLINE RUN PENDING**
- funded executable BUY: **BLOCKED_BY_FUNDING**
- official decision/outcomes: **PENDING**
- economic edge: **NOT ESTABLISHED**
- shadow/live money: **NOT RELEASED**

## End-of-chat handoff — continue from here

This section exists specifically so a new chat can continue without reconstructing this conversation.

Current remote branch head before this handoff update:
- `08acc8bf6ba992818ade7e3c46ab0169bc48a7f8`
- commit message: `docs: advance context through v46 live and v47 review`
- GitHub Actions Unit tests run **683: SUCCESS**.

v47 implementation already present on the branch:
- causal/offline analysis core;
- CLI;
- protocol document;
- unit tests covering causal cutoff and return-independent numeric binning;
- no provider call, no signing, no execution, no official decision mutation.

Next session must **not** redesign v47 and must **not** start v48 first.

On the PC:
1. `git pull --ff-only`
2. run exactly:
   `python route_research_feature_review_v47.py --base-run-key route-research-forward-cohort-20260906-46`
3. send the complete v47 output back for review.

Review requirements for the next chat:
- confirm causal dataset/lineage audit first;
- report feature coverage/missingness;
- compare A and B separately before aggregate;
- identify only same-direction descriptive hypotheses with adequate support;
- explicitly reject unstable or low-support features;
- do **not** convert A/B discoveries into validated trading rules;
- do **not** alter frozen detector thresholds from v47;
- if one hypothesis survives, freeze its exact definition before a fresh v48 prospective holdout.

Scientific state at chat handoff:
- systems engineering: **proven at frozen v44-size path**;
- causal route-only sample: **descriptive-ready via v46**;
- v47 feature discovery: **implementation complete, offline data review still pending**;
- profitable economic edge: **not established**;
- funded executable path: **blocked by funding**;
- official executable outcomes/shadow/live: **not released**.
