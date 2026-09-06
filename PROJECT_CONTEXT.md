# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado fica em `docs/`; aqui ficam estado canônico, invariantes, gates e próxima ordem de trabalho.

## Estado atual

- Repositório: `murilloalvz/crypto-copy-trader`
- Branch: `feat/exit-engine-v1`
- Modo: **PAPER / RESEARCH / READ ONLY**
- Tese: **market-first Solana Opportunity Intelligence / Opportunity Engine**

Fluxo oficial:
`market -> radar -> causal episode T0 -> flow/wallet/context -> executable entry/hazard -> official decision_as_of -> executable forward outcomes -> economic validation -> shadow`

Trilha paralela sem funding:
`fresh episode -> on-chain hazard -> route-only BUY -> research_decision_as_of -> route-only SELL +5/+15/+60 -> descriptive causal evaluation`

### Status canônico

- Pump acquisition: **PASS**
- PumpSwap acquisition + causal pool resolution: **PASS**
- Detector / episode persistence / replay hardening: **PASS**
- Unified Market Latency v34/v37: **FORMAL PASS 11/11**
- Jupiter route availability: **PASS 12/12**
- Funded executable BUY assembly: **BLOCKED_BY_FUNDING**
- Solana Tracker hazard v36: **BLOCKED_BY_PROVIDER_CREDITS**
- Solana RPC minimal hazard v37: **FORMAL PROVIDER PASS**
- Wallet history v38: **strict lineage correct / official sample inconclusive**
- v39 route-only official-schedule plumbing: **CODE/CI PASS**
- v40 first route-only cohort: **COLLECTOR PASS / economic sample INCONCLUSIVE / same-run latency FAIL**
- v41 structural hardening: **CODE/CI PASS / LIVE PENDING**
- Official `decision_as_of`: **PENDING**
- Official executable forward outcomes: **PENDING**
- Economic edge: **NOT ESTABLISHED**
- Shadow/live: **NOT RELEASED**
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

Nenhum threshold foi alterado pelos resultados v40.

## Unified Market Latency gate

ALL:
1. no traceback/worker errors
2. drops 0
3. reference assets 0
4. coverage >=95%
5. true total deadline backlog <=5%
6. Pump p95 <=5s
7. PumpSwap causal pipeline p95 <=5s
8. hydration budget skips 0
9. bundles não sistematicamente vazios
10. replay/collision counters auditáveis
11. reservation superset violations 0

Canonical PASS v37:
- coverage 99.8%
- true backlog 0.173%
- Pump p95 1.397s
- PumpSwap p95 1.695s
- errors/drops/ref/budget/superset violations 0

## Funding / official executable entry

Frozen Jupiter official entry:
- provider `jupiter_swap_v2_order`
- purpose `entry_executable_buy_v1`
- USDC input
- US$25
- slippage 100bps
- public taker only
- no private key/signing/execute

Persisted result:
- route_id 12/12
- assembled tx 0/12
- reason 12/12 `Insufficient funds`

Therefore:
- route availability **PASS**
- funded assemblability **BLOCKED_BY_FUNDING**

## Hazard

v37 provider `solana_rpc_mint_hazard_v1 / token_hazard_minimal_v1` remains the minimal validated provider.
Core: token program, decimals, supply, mint authority, freeze authority, Token-2022 metadata when exposed.

`getTokenLargestAccounts` is optional auxiliary evidence and must never be called holder/owner concentration without owner resolution.

## Wallet history v38

Strict pre-T0 only:
- prior official decision < current T0
- prior forward outcome observed < current T0
- prior exit quote observed < current T0
- same-second equality excluded
- legacy Discovery/Copyability / leaderboard / exploratory wallet P&L forbidden as official label source

Persisted diagnostic on v37 run:
- 12 episodes
- 194 participant-wallet observations
- 0 prior official decisions
- 0 eligible labels
- 0 associations
- classification `INCONCLUSIVE_NO_OFFICIAL_MARKET_FIRST_HISTORY_SAMPLE`

This is correct missingness, not strategy failure.

## v40 — first causal route-only forward cohort

Run:
`unified-market-route-research-smoke-20260905-40`

### Same-run systems

- received 5330
- radar processed 5236
- coverage 98.2% — PASS
- true backlog 94/5330 = 1.764% — PASS
- Pump p95 1.685s — PASS
- PumpSwap pipeline p95 **36.416s — FAIL**
- reference assets 0
- drops 0
- worker errors 0
- hydration budget skips 0
- reservation superset violations 0

Dominant clocks:
- PumpSwap normalization -> reservation p95 ~35.555s
- prepared -> submit p95 ~34.655s
- pipeline p95 ~36.416s
- writer physical batch service p95 only ~85.8ms

Burst evidence:
- 347 network hydrations
- 189 successful hydration batches
- 378 endpoint requests
- 0 all-hedges-failed
- one hot asset reached 332 reservations / 239 max outstanding

Historical v40 same-run systems classification therefore remains **FAIL**. Do not rewrite it.

### v40 hazard / entry accounting

v37 hazard inside v40:
- selected 12
- AVAILABLE 11
- PROVIDER_ERROR 1
- terminal coverage 100%
- provider classification PASS

v40 research:
- selected 12
- route-only Jupiter entry attempts 11 AVAILABLE
- research decisions frozen 11
- forward schedules 33
- route-only executable violations 0
- clock violations 0
- official decision mutation 0
- historical v40 entry terminal coverage reported 91.7%
- historical classification `FAIL_ROUTE_ONLY_RESEARCH_DECISION_PLUMBING`

Source review proved the denominator bug: the 12th selected episode had terminal hazard PROVIDER_ERROR, so Jupiter entry was intentionally **not attempted**. v40 divided 11 entry terminals by all 12 selected episodes and mislabeled explicit upstream missingness as missing entry plumbing.

Historical classification is preserved. v41 fixes future accounting only.

### v40 forward collector — PASS

- scheduled 33
- AVAILABLE 30
- PROVIDER_ERROR 3
- 300s: 10 AVAILABLE / 1 PROVIDER_ERROR
- 900s: 10 AVAILABLE / 1 PROVIDER_ERROR
- 3600s: 10 AVAILABLE / 1 PROVIDER_ERROR
- target lateness p95 1s, max1s
- reused 0
- collector errors 0
- executable semantic violations 0
- classification `PASS_ROUTE_ONLY_FORWARD_COLLECTION_COMPLETE`

The same episode failed provider-side at all three horizons. Exact persisted provider reason must be inspected with:
`route_research_structural_diagnostic_v41.py`
No explanation is invented before that diagnostic.

### v40 economic microcohort

Route-only research labels only; not landed/fill P&L.

300s:
- n=10
- positive 40%
- mean -22.788%
- median -32.044%
- PF 0.412
- best +138.698%
- worst -99.275%
- mean without best -40.731%
- best winner = 86.991% of gross positive return

900s:
- n=10
- positive 10%
- mean -47.031%
- median -50.019%
- PF 0.049

3600s:
- n=10
- positive 10%
- mean -53.070%
- median -50.184%
- PF 0.052

Every horizon: `INCONCLUSIVE_SAMPLE_LT_30`.

Interpretation: first clean microcohort is strongly negative/heavy-tailed, but too small for edge conclusion. Do not tune thresholds from it.

## v41 — structural hardening — CODE/CI PASS, LIVE PENDING

Protocol:
`docs/route-research-v41-structural-hardening-2026-09-06.md`

New files:
- `src/pumpswap_parallel_batched_resolver_v41.py`
- `unified_market_route_research_smoke_v41.py`
- `route_research_structural_diagnostic_v41.py`
- `tests/test_pumpswap_parallel_batched_resolver_v41.py`
- `tests/test_unified_market_route_research_smoke_v41.py`

### v41 fix 1 — correct terminal accounting

Selected episode terminal disposition is now either:
- terminal non-AVAILABLE hazard -> explicit upstream disposition, no fake Jupiter call; or
- hazard AVAILABLE -> eligible Jupiter entry -> terminal entry disposition.

Separate metrics:
- `selected_terminal_disposition_coverage_pct`
- `entry_terminal_coverage_among_eligible_pct`

A missing entry after AVAILABLE hazard still fails closed.

### v41 fix 2 — remove hidden single-batch network serialization

Source review found v32/v33 had a single daemon batch thread executing `_fetch_batch` synchronously. Therefore only one `getMultipleAccounts` batch was in flight even with an 18-resolution outer budget.

v41 keeps one ordered dispatcher but executes bounded parallel batches.
Frozen candidate profile:
- hydration batch workers 8
- hedge endpoints 2
- possible endpoint requests 16
- existing `max_concurrent_resolutions` 18

Hard invariant:
`hydration_batch_workers * hedge_endpoints <= max_concurrent_resolutions`

This uses the existing expensive-work budget rather than raising it blindly.

No detector/FIFO/as_of/episode/hydration-budget semantics changed.

### v41 fresh live gate

Code/CI PASS is not live PASS.
A fresh 120s smoke must independently satisfy:
- original systems latency 11/11
- route research selected terminal disposition 100%
- entry terminal coverage among hazard-AVAILABLE episodes 100%
- no config/reuse/worker/clock/official-decision/schedule/executable-semantic violations
- >=1 route-only AVAILABLE entry for PASS rather than inconclusive

## Immediate next work

1. Run the persisted **read-only** structural diagnostic on the completed v40 run to surface the exact repeated Jupiter SELL provider error.
2. Run a fresh **v41 120s structural smoke** with a new run key.
3. Treat that v41 run as structural validation first; do **not** backfill any missed forward target.
4. If systems latency returns to PASS and route accounting passes, freeze v41 plumbing.
5. Only then start the next full forward cohort toward n>=30 per horizon.
6. Keep detector/features/thresholds frozen until enough clean out-of-sample labels exist.

## Shadow / live

- systems canonical v37: **PASS**
- v40 same-run systems: **FAIL**
- Jupiter route: **PASS**
- funded executable BUY: **BLOCKED_BY_FUNDING**
- on-chain hazard: **PASS**
- wallet history: **LINEAGE CORRECT / OFFICIAL SAMPLE INCONCLUSIVE**
- v40 route-only collector: **PASS**
- v40 economics: **INCONCLUSIVE / observed negative microcohort**
- v41 structural hardening: **CODE/CI PASS / LIVE PENDING**
- official decision/outcomes: **PENDING**
- economic edge: **NOT ESTABLISHED**
- shadow/live money: **NOT RELEASED**
