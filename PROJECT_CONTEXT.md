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

Status:
- Pump acquisition: **PASS**
- PumpSwap acquisition + causal resolution: **PASS**
- Detector / episode / replay hardening: **PASS**
- Unified Market Latency v34/v37: **FORMAL PASS 11/11**
- Unified Market Latency v42, same-run with current route-research plumbing: **FORMAL PASS 11/11**
- Solana RPC minimal hazard v37: **PASS**
- Jupiter route availability: **PASS**
- Funded executable BUY assembly: **BLOCKED_BY_FUNDING**
- Solana Tracker hazard v36: **BLOCKED_BY_PROVIDER_CREDITS**
- Wallet history v38: **strict lineage correct / official sample inconclusive**
- v40 first route-only forward cohort: **collector PASS / economic microcohort INCONCLUSIVE / historical same-run systems FAIL**
- v41 accounting + parallel hydration: **implemented / live plumbing PASS; systems still failed at 6.387s PumpSwap p95**
- v42 eager proven-continuation demotion: **CODE/CI PASS + LIVE SYSTEMS PASS 11/11 + route plumbing PASS**
- v43 integrated forward economic cohort runner: **CODE/CI PASS / LIVE PENDING**
- Official `decision_as_of`: **PENDING**
- Official executable forward outcomes: **PENDING**
- Economic edge: **NOT ESTABLISHED**
- Shadow/live money: **NOT RELEASED**
- Não iniciar coleta oficial de 12h ainda.

## Invariantes congelados

- Histórico exploratório de P&L não é prova causal de edge.
- Detector/estratégia/coorte não mudam por resultado econômico pequeno ou conveniente.
- Wallet é evidência pós-episódio, nunca acquisition whitelist.
- `route available != assemblable transaction != landed transaction != fill`.
- Route-only outcome não é wallet realized P&L.
- Missing/failure permanece explícito; nunca substituir por candle/quote posterior.
- Primeiro trigger-to-episode **persistido** permanece canônico.
- No retroactive enrollment / no backfill.
- PASS de systems latency não significa profitability PASS.
- Não aumentar workers por tentativa; localizar primeiro o relógio dominante.
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

Nenhum threshold foi alterado pelos resultados v40-v43.

## Systems latency — gate congelado

ALL:
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

### Canonical current same-run PASS — v42

Run `unified-market-route-research-smoke-20260906-42`:
- received 6823
- processed 6823
- coverage 100.0%
- true backlog 0%
- Pump p95 1.842s
- PumpSwap pipeline p95 3.302s
- drops/errors/reference assets/budget skips/superset violations = 0
- bundles non-empty
- replay/audit live and no fatal error

Result: **FORMAL PASS 11/11**.

v42 eager demotion evidence:
- submit-time proof passes 282
- eager-demoted jobs 19
- eager-demoted tickets 20
- total demoted pending jobs 173
- finalizer acks pending 0

Do not modify detector, worker profile, SQLite, hydration, scheduler or continuation semantics without new evidence.

## Funding / official executable entry

Frozen Jupiter official entry:
- provider `jupiter_swap_v2_order`
- purpose `entry_executable_buy_v1`
- USDC input
- US$25
- 100bps
- public taker only
- no signing/execute

Persisted earlier diagnostic:
- routes 12/12
- assembled tx 0/12
- reason 12/12 `Insufficient funds`

Therefore route availability passed; funded assemblability remains **BLOCKED_BY_FUNDING**.

## Hazard

v37 provider `solana_rpc_mint_hazard_v1 / token_hazard_minimal_v1` remains the minimal validated provider.
Core: token program, decimals, supply, mint authority, freeze authority, Token-2022 metadata when exposed.

`getTokenLargestAccounts` is optional auxiliary evidence and is **token-account concentration**, not holder/owner concentration.

## Wallet market-first history v38

Strict pre-T0 official lineage only. Legacy Discovery/Copyability, leaderboard PnL, exploratory v2/v3 and later backfill are forbidden as official labels.

Persisted diagnostic on canonical v37 run:
- 12 episodes
- 194 participant-wallet observations
- 0 prior official decisions
- 0 eligible labels
- 0 associations
- classification `INCONCLUSIVE_NO_OFFICIAL_MARKET_FIRST_HISTORY_SAMPLE`

Correct missingness, not strategy failure.

## v40 — first causal route-only microcohort

Run `unified-market-route-research-smoke-20260905-40`.

Collector:
- scheduled 33
- AVAILABLE 30
- PROVIDER_ERROR 3
- 10 AVAILABLE per 300/900/3600 horizon
- target lateness p95 1s
- collector errors 0
- executable violations 0
- PASS collection complete

Repeated forward provider failure was one token failing Jupiter `/order` with HTTP 400 `Failed to get quotes` at all three horizons: persistent route/provider evidence, not collector plumbing failure.

Economic microcohort:
- 300s n10: positive40%, mean -22.788%, median -32.044%, PF0.412, best +138.698%, mean without best -40.731%
- 900s n10: positive10%, mean -47.031%, median -50.019%, PF0.049
- 3600s n10: positive10%, mean -53.070%, median -50.184%, PF0.052

All horizons: **INCONCLUSIVE_SAMPLE_LT_30**. Strongly negative/heavy-tailed first observation, but insufficient for edge conclusion. No tuning from it.

## v41 / v42 structural resolution

v41 fixed:
1. terminal upstream hazard failure is an explicit disposition, not a missing Jupiter entry;
2. hidden one-lane PumpSwap hydration transport became bounded parallel batches within the existing resolution budget.

v41 live:
- route-research decision plumbing PASS
- entry terminal coverage among eligible 100%
- PumpSwap p95 improved from v40 ~36.4s to ~6.387s but still failed systems gate.

v42 then reused the exact v34/v27 continuation proof at submit time over already-pending followers. Only proven continuation-only pending work is demoted; ready/running/ambiguous/late-earlier/state-mutating work remains strict FIFO.

v42 live result: **systems PASS 11/11** and route-research decision plumbing PASS in the same run.

Latency engine is now frozen.

## v43 — integrated forward economic cohort

Protocol:
`docs/route-only-forward-economic-cohort-v43-protocol-2026-09-06.md`

Files:
- `route_research_forward_cohort_v43.py`
- `src/route_research_forward_collection_v43.py`
- `tests/test_route_research_forward_cohort_v43.py`

Status: **CODE/CI PASS / LIVE PENDING**.

Purpose: eliminate the manual `smoke -> start collector` handoff and collect the first >=30 causal route-only outcomes per horizon under the frozen v42 market path.

Frozen defaults:
- acquisition 120s
- predeclared cohort cap 40
- minimum clean research decisions 30
- hazard cap = research cap
- route-only BUY notional $25
- slippage parameter 100bps
- exact horizons 300/900/3600s
- forward lateness descriptive gate p95 <=2s

v43 execution logic:
1. run fresh v42 acquisition/research path;
2. capture the v42 diagnostics while still printing them live;
3. automatically audit same-run systems gate 11/11;
4. if systems fail, stop — no forward collection;
5. audit persisted research schedules;
6. if <30 decisions or incomplete 3-horizon schedules, preserve undersized run and stop;
7. otherwise start forward collector immediately;
8. derive collector stop time from the **latest persisted target + grace**, not a blind fixed 3700s;
9. collect route-only SELL only at/after exact targets;
10. run descriptive evaluation automatically at the end.

`READY_FOR_DESCRIPTIVE_RESEARCH_REVIEW` requires:
- same-run systems 11/11
- >=30 fresh decisions
- exact schedules
- terminal forward collection
- target lateness p95 <=2s
- lineage violations 0
- >=30 AVAILABLE outcomes at each of 300/900/3600s

This classification is sample/lineage readiness only. It is **not** profitability, executability, landing/fill or live-money PASS.

## Immediate next work

Run one fresh v43 integrated cohort with a new run key. Keep the PC awake and do not start another market/collector process concurrently.

After v43 completes:
1. inspect same-run systems 11/11;
2. inspect admitted decision count and provider missingness;
3. inspect forward terminal coverage and target lateness;
4. inspect per-horizon descriptive economics;
5. compare with v40 microcohort without changing detector/features/thresholds;
6. if descriptive sample is clean, design the next predeclared time-split/ablation analysis for wallet/hazard/flow incremental value.

## Shadow / live

- systems current: **PASS**
- route-only research plumbing: **PASS**
- on-chain hazard: **PASS**
- funded executable BUY: **BLOCKED_BY_FUNDING**
- wallet official history: **LINEAGE CORRECT / SAMPLE INCONCLUSIVE**
- v40 economics: **INCONCLUSIVE / negative microcohort observed**
- v43 economic cohort: **CODE/CI PASS / LIVE PENDING**
- official decision/outcomes: **PENDING**
- economic edge: **NOT ESTABLISHED**
- shadow/live money: **NOT RELEASED**
