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
`fresh episode -> on-chain hazard -> route-only BUY -> research_decision_as_of -> route-only SELL +5/+15/+60 -> causal economic evaluation`

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
- v47 causal feature discovery: **OFFLINE PASS / ROBUSTNESS REVIEW COMPLETE**
- v48 frozen prospective Flow60 holdout: **HYPOTHESIS FROZEN / FIRST FRESH ATTEMPT ABORTED BEFORE ECONOMIC EVALUATION — SYSTEMS 9/11**
- v49 systems stabilization: **CODE/CI PASS / LIVE SYSTEMS-ONLY VALIDATION PENDING**
- Funded executable BUY assembly: **BLOCKED_BY_FUNDING**
- Solana Tracker hazard: **BLOCKED_BY_PROVIDER_CREDITS**
- Official `decision_as_of`: **PENDING / UNFROZEN**
- Official executable forward outcomes: **PENDING**
- Profitable economic edge: **NOT ESTABLISHED**
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
- Discovery data nunca pode ser reapresentado como virgin holdout da regra descoberta nele.
- Se v48 falhar ou ficar inconclusivo, não retunar bins nem trocar de hipótese usando o mesmo holdout.
- Run abortada por systems antes do collector não pode ser reinterpretada como verdict econômico.
- A run key da primeira tentativa v48 fica preservada/queimada; não reutilizar.

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

Nenhum threshold do detector foi alterado pelos resultados econômicos v40-v49.

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

v44 PASS no tamanho prático congelado:
- coverage 99.8%
- true backlog 0.222%
- Pump p95 1.733s
- PumpSwap p95 3.808s
- result **11/11**

v45 cap50 single acquisition foi rejeitado:
- systems **10/11**
- PumpSwap p95 **9.512s**
- collector corretamente não iniciou

Primeira tentativa fresh v48 (`route-research-prospective-holdout-20260906-48-A`) foi abortada por systems:
- coverage **97.3%** — PASS
- true backlog **2.667%** — PASS
- Pump radar p95 **6.498s** — FAIL
- PumpSwap causal pipeline p95 **8.898s** — FAIL
- result **9/11**
- worker errors 0
- drops 0
- hydration budget skips 0
- reservation superset violations 0
- forward economic collector **não iniciou**
- Flow60 hypothesis **não foi avaliada**.

Dominant clocks da tentativa abortada:
- Pump arrival ~= 1918/120 = **15.98 notif/s**;
- Pump prepare service p95 **918.8ms** com 12 workers => capacidade p95 ~= **13.06 notif/s**, abaixo da chegada;
- PumpSwap terminou com **108 prepared items waiting reservation**;
- PumpSwap normalization-to-reservation p95 **6.320s**;
- PumpSwap ingress-to-reservation p95 **8.881s**;
- SQLite writer/result e detector DB-read permaneceram bem menores que o relógio dominante;
- conclusão: Pump estava tail-underprovisioned e PumpSwap sofreu global ingress reservation head-of-line por sequence holes de pool identity resolution.

v49 systems scheduling amendment, preregistrado antes do próximo live:
- Pump prepare workers: **12 -> 20**, dimensionado pela capacidade medida, sem alterar detector;
- PumpSwap immutable pool identity resolution começa em ingress via prefetch;
- prefetch usa o **mesmo resolver**, cache/history, per-pool single-flight, hydration budget, hedging e explicit unresolved semantics;
- prefetch não persiste trade, não cria reservation, não detecta trigger, não muta episódio, não reordena FIFO e não faz retry/backfill;
- authoritative normalization/persistence continua no path original;
- `route_research_systems_stability_v49.py` bloqueia deliberadamente o forward SELL collector e valida somente o gate systems 11/11.

Conclusão: não relaxar gate, não rerollar v48 até conseguir systems evidence independente. Primeiro rodar uma única v49 systems-only fresh.

## Funding / official executable path

Frozen official Jupiter BUY:
- provider `jupiter_swap_v2_order`
- purpose `entry_executable_buy_v1`
- USDC input
- US$25
- 100bps
- public taker only
- no signing/execute

Readiness persistido mostrou rota disponível, mas nenhum transaction assembly por falta de saldo no taker configurado. Official funded assemblability permanece **BLOCKED_BY_FUNDING**.

## Hazard

Validated free provider:
`solana_rpc_mint_hazard_v1 / token_hazard_minimal_v1`

Core:
- token program
- decimals
- supply
- mint authority
- freeze authority
- Token-2022 metadata quando exposta

`getTokenLargestAccounts` é evidência auxiliar opcional de **token-account concentration**, não holder/owner concentration.

## Route-only causal research

Funding-free research path only. Nunca congela official `decision_as_of` e nunca assina/submete.

Frozen semantics:
- BUY: USDC -> token, taker=None, route-only/non-executable
- notional: US$25
- slippage parameter: 100bps
- horizons: 300 / 900 / 3600 seconds
- SELL: exact entry output amount token -> USDC, taker=None
- missing Jupiter route permanece missing explícito

Provider pacing congelado do v44:
- hazard starts: 650ms
- BUY starts: 1000ms
- SELL starts: 250ms
- no retry/backfill

## v40 microcohort

Primeira microcoorte causal route-only, n10 por horizonte. Todos os horizontes `INCONCLUSIVE_SAMPLE_LT_30`. Resultados negativos/heavy-tailed retidos apenas como evidência inicial; detector não foi ajustado.

## v44 larger single valid cohort

Live `route-research-forward-cohort-20260906-44`:
- systems 11/11
- hazard 40/40 AVAILABLE
- entry 39/40 AVAILABLE
- 39 decisions / 117 schedules
- collector terminal 117/117
- target lateness p95 1s
- lineage 0

Economics:
- 300s n35: mean -5.016%, median -4.082%, PF0.766
- 900s n29: mean -14.497%, median -28.814%, PF0.653
- 3600s n29: mean -36.457%, median -42.599%, PF0.245

Overall inconclusivo porque 900/3600 tinham n29.

## v46 dual prospective subcohorts — canonical discovery sample

Base run:
`route-research-forward-cohort-20260906-46`

Subcohorts:
- `...-46-A`
- `...-46-B`

Protocol:
- duas subcoortes v44-size completas e sequenciais;
- cada uma cap40 / minimum30;
- cada uma exige systems11/11, >=30 decisions, terminal collector, lateness p95<=2s, lineage0;
- uma subcoorte falha não pode ser salva pela outra;
- agregação preserva identidade e missingness.

Live final result:
- subcohorts passed: **2/2**
- aggregate lineage violations: **0**
- descriptive-ready horizons: **3/3**
- classification: **READY_FOR_DESCRIPTIVE_RESEARCH_REVIEW**

Aggregate A+B:
- 300s: AVAILABLE74, positive45.95%, mean -7.324%, median -0.233%, PF0.536, mean_without_best -9.309%
- 900s: AVAILABLE69, positive56.52%, mean -1.458%, median +1.363%, PF0.932, mean_without_best -5.771%
- 3600s: AVAILABLE66, positive39.39%, mean -27.359%, median -29.786%, PF0.371, mean_without_best -30.252%

900s era o único horizonte próximo de break-even, mas ainda sem edge positivo replicado no detector cru.

## v47 offline causal feature discovery — COMPLETE

Files:
- `src/route_research_feature_review_v47.py`
- `route_research_feature_review_v47.py`
- `tests/test_route_research_feature_review_v47.py`
- `src/route_research_feature_robustness_v47.py`
- `route_research_feature_robustness_v47.py`
- `tests/test_route_research_feature_robustness_v47.py`

Protocols:
- `docs/route-research-offline-causal-feature-review-v47-protocol-2026-09-06.md`
- `docs/route-research-v47-candidate-robustness-protocol-2026-09-06.md`

Causal dataset audit live:
- rows_total 79
- A 39 / B 40
- lineage violations 0
- missing decisions 0
- missing episodes 0
- missing hazard attempts 0
- missing entry quotes 0
- official decision mutations 0
- classification **PASS_V47_CAUSAL_DATASET_AUDIT**

Zero-coverage features in v46 evidence:
- `flow30_notional_imbalance_pct`
- `flow30_return_pct`
- `entry_liquidity_usd`

Não backfillar retrospectivamente. Melhorar observabilidade apenas para datasets futuros se necessário.

### v47 robustness conclusion

Dos 18 `SAME_DIRECTION_DESCRIPTIVE_ONLY` automáticos, a maior parte foi rejeitada como hipótese primária por redundância, baixo suporte, forma econômica instável ou dependência/outlier.

Famílias redundantes:
- `flow60_event_count` e `flow300_event_count` contam praticamente o mesmo fenômeno na amostra;
- `hazard_token_2022` e `hazard_extensions_count` produziram splits equivalentes.

Candidato escolhido para prospective validation:
`flow60_event_count` no horizonte 900s.

Discovery bins congelados pelo v47 value-only grouping:
- LOW <=25
- MID 26..47
- HIGH >47

Discovery 900s — LOW vs HIGH:

A:
- LOW n18, median +1.969%, PF1.179, mean +2.312%, mean_without_best -1.930%
- HIGH n5, median -30.760%, PF0.416, mean -19.476%

B:
- LOW n15, median +1.529%, PF2.905, mean +28.414%, mean_without_best +9.602%
- HIGH n9, median -1.088%, PF0.346, mean -20.021%

ALL:
- LOW n33, median +1.529%, PF2.026, mean +14.177%, mean_without_best **+5.502%**
- HIGH n14, median -15.924%, PF0.372, mean -19.826%, mean_without_best -26.234%

Interpretação correta:
- há uma hipótese causal/descritiva defensável de **flow saturation / move maturity**;
- maior intensidade de eventos antes da decisão pode identificar movimentos já congestionados/maduros;
- isso ainda NÃO é uma regra de trading e NÃO é edge validado;
- v46/v47 são discovery e não podem validar a própria hipótese.

Outros candidatos não são promovidos para v48 primário:
- repeated-wallet 3600s: A HIGH continuou economicamente negativo e winner concentration elevada;
- Token-2022: forte diferença 3600s, mas economic shape 900s não sustenta uma regra única e é redundante com extensions;
- buy share: median direction não coincide de forma robusta com mean/PF em 900s;
- entry price impact: semântica/sinal requer cuidado e os grupos permanecem economicamente fracos em vários horizontes;
- decision delay: efeito pequeno/inconsistente fora de 300s.

## v48 prospective Flow60 holdout — FROZEN BEFORE DATA

Protocol:
`docs/route-research-v48-prospective-flow60-holdout-protocol-2026-09-06.md`

Files:
- `src/route_research_prospective_holdout_v48.py`
- `route_research_prospective_holdout_v48.py`
- `tests/test_route_research_prospective_holdout_v48.py`

Primary feature:
`flow60_event_count`

Frozen bins:
- LOW <=25
- MID 26..47
- HIGH >47

Primary horizon:
- **900s only**

Primary contrast:
- **LOW vs HIGH**
- MID é reportado, não faz parte do gate primário.
- 300s e 3600s são diagnósticos e não podem resgatar um FAIL de 900s.

Fresh acquisition:
- run key deve ser nova;
- cada subcoorte continua cap40/minimum30 e precisa passar gates independentes;
- qualquer systems FAIL antes do collector deixa a hipótese economicamente NOT_EVALUATED;
- o profile systems usado no próximo v48 só pode mudar após v49 systems-only PASS.

Primary support gate em 900s:
- A: LOW >=5 AVAILABLE e HIGH >=5 AVAILABLE
- B: LOW >=5 AVAILABLE e HIGH >=5 AVAILABLE

Primary PASS exige TODOS:
1. median LOW > HIGH em A;
2. median LOW > HIGH em B;
3. median LOW > HIGH em ALL;
4. LOW median >0 em A e B;
5. LOW PF >1 em A e B;
6. aggregate LOW PF >1;
7. aggregate LOW mean_without_best >0.

Pass classification:
`PASS_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS`

Low support:
`INCONCLUSIVE_V48_PRIMARY_SUPPORT`

Adequate support but failed economics/replication:
`FAIL_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS`

Mesmo um PASS v48 é apenas prospective route-only hypothesis PASS. Ainda não libera official executable path, shadow ou live money.

### First fresh v48 attempt — SYSTEMS ABORT, NO ECONOMIC VERDICT

Base attempted run key:
`route-research-prospective-holdout-20260906-48`

Only A acquisition started. Same-run systems gate returned **9/11** because Pump and PumpSwap p95 exceeded 5s. v46 correctly stopped fail-closed before B and before forward economic collection.

Classification:
- acquisition: `FAIL_V48_FROZEN_V46_ACQUISITION_PATH`
- Flow60 hypothesis: **NOT_EVALUATED**
- economic edge: **NOT ESTABLISHED**

Do not reuse this run key and do not inspect/repurpose it as a prospective economic holdout.

## v49 systems stability — CODE/CI PASS, LIVE PENDING

Protocol:
`docs/route-research-v49-systems-stability-protocol-2026-09-07.md`

Files:
- `src/pumpswap_ingress_prefetch_v49.py`
- `unified_market_route_research_smoke_v49.py`
- `route_research_systems_stability_v49.py`
- `tests/test_pumpswap_ingress_prefetch_v49.py`

Purpose:
- attack the two measured systems clocks only;
- validate amended scheduling without collecting forward SELL labels;
- preserve Flow60 hypothesis as virgin with respect to a completed forward holdout.

v49 PASS requires the unchanged v43 same-run systems gate **11/11**.

Classifications:
- `PASS_V49_SYSTEMS_STABILITY_PROFILE`
- `FAIL_V49_SYSTEMS_STABILITY_PROFILE`
- `FAIL_V49_SYSTEMS_ONLY_GUARD`

A v49 PASS is systems evidence only. It does not validate route-only profitability, Flow60, executable fills, shadow or live money.

## Immediate next work

No PC:

1. `git pull --ff-only`
2. executar uma única fresh v49 systems-only run:

`python route_research_systems_stability_v49.py --run-key route-research-systems-stability-20260907-49`

Enviar o output completo.

**Não rodar v48 novamente ainda.** Não alterar bins 25/47, horizonte 900s, detector, provider pacing ou economic gate.

Se v49 PASS 11/11:
1. registrar o live systems PASS;
2. wirear o profile v49 validado no acquisition path do v48 sem mudar a hipótese;
3. usar uma **nova** v48 base run key;
4. só então coletar o verdadeiro prospective holdout.

Se v49 FAIL:
- manter Flow60 congelada e NOT_EVALUATED;
- usar os novos diagnostics para localizar o relógio dominante restante;
- não rerollar v48.

## Shadow / live

- systems canonical historical v44-size path: **PASS**
- first v48 fresh attempt: **SYSTEMS ABORT 9/11 / NO ECONOMIC VERDICT**
- v49 systems amendment: **CODE/CI PASS / LIVE SYSTEMS-ONLY PENDING**
- v46 causal sample: **DISCOVERY READY**
- v47 discovery/robustness: **COMPLETE**
- v48 frozen prospective hypothesis: **FROZEN / PROSPECTIVELY UNTESTED ECONOMICALLY**
- funded executable BUY: **BLOCKED_BY_FUNDING**
- official decision/outcomes: **PENDING**
- profitable economic edge: **NOT ESTABLISHED**
- shadow/live money: **NOT RELEASED**

## End-of-chat handoff — continue from here

Do not reopen feature discovery on v46/v47 and do not rerun v48 before v49 live systems validation.

Scientific sequence is now:
`v46 discovery sample -> v47 causal feature discovery + robustness -> frozen Flow60 hypothesis -> first v48 acquisition abort (systems only) -> v49 systems-only stabilization -> fresh v48 holdout if v49 PASS`.

Frozen v48 hypothesis remains exactly:
- feature `flow60_event_count`
- LOW <=25 / MID 26..47 / HIGH >47
- primary horizon 900s
- LOW-vs-HIGH
- strict replication + positive economic-shape + heavy-tail gate.

v49 implementation was committed before live validation and GitHub Actions compile/unit tests passed at head before this context update.

Next session/action:
1. pull latest branch;
2. run fresh `route_research_systems_stability_v49.py` with run key `route-research-systems-stability-20260907-49`;
3. send complete output;
4. classify systems PASS/FAIL only;
5. do not inspect this diagnostic as economic evidence;
6. only on v49 PASS prepare a new fresh v48 acquisition key.

Scientific state:
- historical systems engineering: **proven at prior v44-size path, but latest first v48 attempt exposed a load-sensitive regression**;
- v49 amended systems profile: **code/CI proven, live not yet proven**;
- causal route-only discovery sample: **complete via v46**;
- v47 feature discovery + heavy-tail review: **complete**;
- one prospective Flow60 hypothesis: **frozen and not economically evaluated prospectively yet**;
- profitable economic edge: **not established**;
- funded executable path: **blocked by funding**;
- official executable outcomes/shadow/live: **not released**.