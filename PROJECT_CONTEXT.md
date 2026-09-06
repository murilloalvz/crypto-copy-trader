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
- Route-research plumbing: **PASS**
- Solana RPC minimal hazard v37 semantics: **PASS**
- Jupiter route-only plumbing: **PASS**
- v43 integrated cohort: **LIVE SYSTEMS PASS 11/11 / SAMPLE INCONCLUSIVE 18<30**
- v43 sample loss cause: **PROVIDER THROTTLING CONFIRMED** — 15/40 Solana RPC 429 + 7/25 Jupiter entry 429
- v44 provider-paced cohort runner: **CODE/CI PASS / LIVE PENDING**
- Funded executable BUY assembly: **BLOCKED_BY_FUNDING**
- Solana Tracker hazard v36: **BLOCKED_BY_PROVIDER_CREDITS**
- Wallet history v38: **strict lineage correct / official sample inconclusive**
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

Nenhum threshold foi alterado pelos resultados v40-v44.

## Systems latency gate

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

Canonical same-run PASS v42:
- received 6823
- processed 6823
- coverage 100.0%
- true backlog 0%
- Pump p95 1.842s
- PumpSwap pipeline p95 3.302s
- errors/drops/reference/budget/superset = 0

v43 também manteve systems PASS 11/11 sob carga maior:
- received 9174
- processed 9171
- true backlog 0.033%
- Pump p95 2.731s
- PumpSwap p95 4.142s

Latency engine permanece congelado.

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

Funded assemblability remains **BLOCKED_BY_FUNDING**.

## Hazard

v37 provider `solana_rpc_mint_hazard_v1 / token_hazard_minimal_v1` remains the minimal validated provider.
Core: token program, decimals, supply, mint authority, freeze authority, Token-2022 metadata when exposed.

`getTokenLargestAccounts` is optional auxiliary evidence and is **token-account concentration**, not holder/owner concentration.

## Wallet market-first history v38

Strict pre-T0 official lineage only. Legacy Discovery/Copyability, leaderboard PnL, exploratory v2/v3 and later backfill are forbidden as official labels.

Persisted diagnostic:
- 12 episodes
- 194 participant-wallet observations
- 0 prior official decisions
- 0 eligible labels
- 0 associations
- `INCONCLUSIVE_NO_OFFICIAL_MARKET_FIRST_HISTORY_SAMPLE`

Correct missingness, not strategy failure.

## v40 first causal route-only microcohort

Collector PASS:
- 33 scheduled
- 30 AVAILABLE
- 10 AVAILABLE per 300/900/3600 horizon
- target lateness p95 1s
- no collector/executable-semantic errors

Economics, route-only only:
- 300s n10: positive40%, mean -22.788%, median -32.044%, PF0.412, best +138.698%, mean without best -40.731%
- 900s n10: positive10%, mean -47.031%, median -50.019%, PF0.049
- 3600s n10: positive10%, mean -53.070%, median -50.184%, PF0.052

All horizons: **INCONCLUSIVE_SAMPLE_LT_30**. No threshold tuning from this microcohort.

## v41 / v42 structural resolution

v41 fixed terminal accounting and hidden one-lane PumpSwap hydration transport. v42 added eager submit-time demotion using the exact existing continuation proof for pending work only.

v42 live: **systems PASS 11/11 + route plumbing PASS**.

No further latency optimization without new evidence.

## v43 integrated forward economic cohort

Protocol: `docs/route-only-forward-economic-cohort-v43-protocol-2026-09-06.md`

Frozen defaults:
- acquisition 120s
- predeclared cap 40
- minimum clean research decisions 30
- route-only BUY $25 / 100bps
- exact horizons 300/900/3600s
- target lateness descriptive gate p95 <=2s

Live run `route-research-forward-cohort-20260906-43`:
- systems PASS 11/11
- selected 40
- hazard AVAILABLE 25 / PROVIDER_ERROR 15
- all 15 hazard errors = Solana public RPC HTTP 429 Too Many Requests
- entry eligible 25
- entry AVAILABLE 18 / PROVIDER_ERROR 7
- all 7 entry errors = Jupiter `/order` HTTP 429 API Gateway Too Many Requests
- selected terminal disposition coverage 100%
- entry terminal coverage among eligible 100%
- missing eligible entry 0
- unexpected entry after hazard failure 0
- decisions frozen 18
- schedules 54
- classification `INCONCLUSIVE_V43_COHORT_LT_MINIMUM`
- collector correctly did **not** start

Conclusion: v43 undersizing was provider throttling, not detector/plumbing/economic evidence.

## v44 provider-paced cohort

Files:
- `src/provider_start_pacer_v44.py`
- `route_research_forward_cohort_v44.py`
- `tests/test_provider_start_pacer_v44.py`

Status: **CODE/CI PASS / LIVE PENDING**.

Purpose: reduce confirmed provider 429 losses while preserving original at-most-once semantics.

Frozen v44 candidate pacing:
- Solana hazard capture starts: 650ms apart
- Jupiter route-only BUY starts: 1000ms apart
- Jupiter route-only SELL starts: 250ms apart

Critical semantics:
- pacing happens **before** the original provider capture;
- no retry after a provider failure;
- no backfill/later replacement;
- no detector/episode/FIFO/as-of/economic-definition changes;
- explicit 429 remains explicit if it still occurs;
- v43 systems 11/11 and >=30-decision admission gates remain unchanged.

The BUY pacer is deliberately conservative because entry has no exact future target. SELL pacing is tighter because forward target lateness must remain observable and p95 <=2s for descriptive readiness.

## Immediate next work

Run one fresh v44 cohort with a new run key.

Interpretation order:
1. same-run systems must remain 11/11;
2. compare hazard 429 rate with v43 15/40;
3. compare Jupiter entry 429 rate with v43 7/25;
4. require >=30 fresh decisions before collector starts;
5. if admitted, inspect SELL 429s and target lateness;
6. only then review 300/900/3600 descriptive economics.

Do not raise cap or tune detector/strategy from v43. First test whether the confirmed provider-throttling bottleneck is removed by pacing.

## Shadow / live

- systems current: **PASS**
- route-only research plumbing: **PASS**
- on-chain hazard semantics: **PASS**
- v43 sample: **INCONCLUSIVE — PROVIDER 429 THROTTLING**
- v44: **CODE/CI PASS / LIVE PENDING**
- funded executable BUY: **BLOCKED_BY_FUNDING**
- official decision/outcomes: **PENDING**
- economic edge: **NOT ESTABLISHED**
- shadow/live money: **NOT RELEASED**
