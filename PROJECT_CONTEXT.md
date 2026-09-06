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
- v44 provider-paced cohort: **LIVE SYSTEMS PASS 11/11 / 39 DECISIONS / FORWARD COMPLETE / OVERALL INCONCLUSIVE**
- v44 hazard pacing: **40/40 AVAILABLE / 0 hazard 429**
- v44 entry pacing: **39/40 AVAILABLE / 1 Jupiter entry 429**
- v44 forward missingness: **all 24 SELL PROVIDER_ERROR = Jupiter HTTP 400 `Failed to get quotes`, not 429**
- v45 larger predeclared cohort: **CODE/CI PASS / LIVE PENDING**
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

Nenhum threshold foi alterado pelos resultados v40-v45.

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

v44 também manteve systems PASS 11/11:
- received 4507
- coverage 99.8%
- true backlog 0.222%
- Pump p95 1.733s
- PumpSwap p95 3.808s

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
- decisions frozen 18
- schedules 54
- classification `INCONCLUSIVE_V43_COHORT_LT_MINIMUM`
- collector correctly did **not** start

Conclusion: v43 undersizing was provider throttling, not detector/plumbing/economic evidence.

## v44 provider-paced cohort — live complete

Files:
- `src/provider_start_pacer_v44.py`
- `route_research_forward_cohort_v44.py`
- `tests/test_provider_start_pacer_v44.py`

Frozen pacing:
- Solana hazard starts: 650ms apart
- Jupiter route-only BUY starts: 1000ms apart
- Jupiter route-only SELL starts: 250ms apart

Critical semantics:
- pacing before the original at-most-once provider capture;
- no retry after provider failure;
- no backfill/later replacement;
- no detector/episode/FIFO/as-of/economic-definition changes.

Live run `route-research-forward-cohort-20260906-44`:
- systems PASS 11/11
- selected 40
- hazard AVAILABLE 40 / PROVIDER_ERROR 0
- entry AVAILABLE 39 / PROVIDER_ERROR 1
- residual entry failure = Jupiter 429
- research decisions 39
- schedules 117
- collector submitted 117 / terminal 117
- collector errors 0
- executable semantic violations 0
- target lateness p95 1s / max 1s
- lineage violations 0

Forward availability:
- 300s: 35 AVAILABLE / 4 PROVIDER_ERROR = 89.7%
- 900s: 29 AVAILABLE / 10 PROVIDER_ERROR = 74.4%
- 3600s: 29 AVAILABLE / 10 PROVIDER_ERROR = 74.4%

Persisted forward diagnostic:
- all 24 forward errors = Jupiter `/order` HTTP 400 `Failed to get quotes`
- **zero SELL 429**
- repeated persistent failures across all horizons for four episodes
- these are legitimate route/provider missingness, not collector plumbing failure

Descriptive route-only economics:
- 300s n35: positive48.57%, mean -5.016%, median -4.082%, PF0.766, best +246.881%, worst -99.914%, mean without best -12.425%
- 900s n29: positive31.03%, mean -14.497%, median -28.814%, PF0.653, best +685.875%, worst -99.996%, mean without best -39.511%
- 3600s n29: positive24.14%, mean -36.457%, median -42.599%, PF0.245, best +98.456%, worst -99.997%, mean without best -41.276%

Classifications:
- 300s: `DESCRIPTIVE_SAMPLE_READY_FOR_ANALYSIS`
- 900s: `INCONCLUSIVE_SAMPLE_LT_30`
- 3600s: `INCONCLUSIVE_SAMPLE_LT_30`
- overall: `INCONCLUSIVE_V43_FORWARD_COHORT`

Interpretation: first larger causal sample remains economically negative/heavy-tailed. This is not yet a formal negative-edge conclusion because two horizons missed the n>=30 descriptive gate by one label. Do not tune strategy from v44.

## v45 larger predeclared cohort

Protocol: `docs/route-only-forward-economic-cohort-v45-protocol-2026-09-06.md`

Files:
- `route_research_forward_cohort_v45.py`
- `tests/test_route_research_forward_cohort_v45.py`

Status: **CODE/CI PASS / LIVE PENDING**.

v45 changes only sample size relative to v44:
- selected cap: **50**
- minimum clean research decisions before collector starts: **40**

Everything else remains frozen:
- acquisition 120s
- hazard pacing 650ms
- BUY pacing 1000ms
- SELL pacing 250ms
- route-only BUY $25 / 100bps
- exact horizons 300/900/3600s
- same-run systems gate 11/11
- no retry/backfill
- same detector/provider/economic definitions

Reason for 50/40: v44 forward availability at 900/3600 was 29/39 (~74.4%). The larger predeclared cohort is intended only to absorb legitimate `Failed to get quotes` missingness and reach the already-defined >=30 AVAILABLE labels/horizon without changing route semantics after seeing outcomes.

## Immediate next work

Run one fresh v45 cohort with a new run key and no concurrent market/collector process.

Interpretation order:
1. same-run systems must remain 11/11;
2. require >=40 fresh research decisions before collector starts;
3. inspect hazard/entry 429s without retrying them;
4. require terminal forward collection and target lateness p95 <=2s;
5. preserve all `Failed to get quotes` as explicit missingness;
6. check whether all three horizons reach >=30 AVAILABLE labels;
7. only then perform descriptive comparison with v40/v44, with detector/features/thresholds still frozen.

## Shadow / live

- systems current: **PASS**
- route-only research plumbing: **PASS**
- on-chain hazard semantics: **PASS**
- v44 economics: **OVERALL INCONCLUSIVE / NEGATIVE-HEAVY-TAILED OBSERVATION**
- v45: **CODE/CI PASS / LIVE PENDING**
- funded executable BUY: **BLOCKED_BY_FUNDING**
- official decision/outcomes: **PENDING**
- economic edge: **NOT ESTABLISHED**
- shadow/live money: **NOT RELEASED**
