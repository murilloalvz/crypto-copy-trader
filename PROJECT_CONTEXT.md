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

## Status atual

- Pump acquisition: **PASS**
- PumpSwap acquisition + causal resolution: **PASS**
- Detector / episode / replay hardening: **PASS**
- Unified Market Latency v42: **FORMAL PASS 11/11**
- v44-size provider-paced path: **SYSTEMS PASS 11/11**
- Solana RPC minimal hazard v37 semantics: **PASS**
- Route-only Jupiter research plumbing: **PASS**
- v45 cap50 single acquisition: **REJECTED — SYSTEMS 10/11**
- v46 dual prospective 40/30: **2/2 SUBCOHORTS PASS / DISCOVERY SAMPLE COMPLETE**
- v47 causal feature discovery + robustness: **COMPLETE**
- v48 prospective Flow60 holdout: **FROZEN / FIRST FRESH ATTEMPT ABORTED BY SYSTEMS BEFORE ECONOMIC COLLECTION**
- v49 systems amendment: **IMPLEMENTED / CI PASS**
- recent v49-profile systems evidence: **TWO SAME-RUN 11/11 PASSES VIA v50/v50b**
- v50b causal clock attribution: **GLOBAL SEQUENCE BARRIER IDENTIFIED**
- corrected v50 attribution acceptance code/tests: **CI PASS**
- Flow60 prospective economics: **NOT_EVALUATED**
- profitable economic edge: **NOT ESTABLISHED**
- funded executable BUY assembly: **BLOCKED_BY_FUNDING**
- Solana Tracker hazard: **BLOCKED_BY_PROVIDER_CREDITS**
- official `decision_as_of`: **PENDING / UNFROZEN**
- official executable forward outcomes: **PENDING**
- shadow/live money: **NOT RELEASED**
- não iniciar coleta oficial de 12h ainda.

## Invariantes congelados

1. Histórico exploratório de P&L não é prova causal de edge.
2. Detector/estratégia não mudam por resultado econômico pequeno ou conveniente.
3. Wallet é evidência pós-episódio, nunca acquisition whitelist.
4. Missing/failure permanece explícito; nunca substituir por candle/quote posterior.
5. Primeiro trigger-to-episode persistido permanece canônico.
6. No retroactive enrollment / no backfill.
7. Systems latency PASS não significa profitability PASS.
8. Não aumentar workers por tentativa; primeiro localizar o relógio dominante.
9. Features de wallet/hazard/flow permanecem descritivas até evidência out-of-sample.
10. Discovery data nunca pode validar a própria hipótese descoberta nele.
11. `route available != assemblable transaction != landed transaction != fill`.
12. Route-only outcome não é realized wallet P&L.
13. Nenhum live money sem forward evidence robusta + gate explícito.
14. v48 não pode ser resgatado por retuning pós-hoc.
15. Run abortada por systems antes do collector não produz verdict econômico.
16. A primeira run key v48 fica preservada/queimada e não pode ser reutilizada.
17. v49/v50 são systems-only e não podem ser usados como evidência econômica.

## Detector congelado

File:
`src/market_opportunity_radar.py`

Version:
`market_opportunity_radar_v1_1_tx_aware`

Thresholds:
- fast window 30s
- baseline 300s
- >=6 fast events
- >=4 known unique wallets
- established: >=3 baseline events + >=3x acceleration
- fresh causal token age <=120s
- com tx identity coverage 100%: >=4 unique fast tx
- direction descritiva

Nenhum threshold do detector foi alterado pelos resultados econômicos v40-v50.

## Systems latency gate congelado

ALL devem passar:
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

Canonical v42:
- coverage 100.0%
- true backlog 0%
- Pump p95 1.842s
- PumpSwap p95 3.302s
- **11/11**

v44 practical-size path:
- coverage 99.8%
- true backlog 0.222%
- Pump p95 1.733s
- PumpSwap p95 3.808s
- **11/11**

First fresh v48 attempt:
- coverage 97.3%
- true backlog 2.667%
- Pump p95 6.498s — FAIL
- PumpSwap p95 8.898s — FAIL
- **9/11**
- no forward economic collector
- Flow60 remained NOT_EVALUATED.

Measured causes from that abort:
- Pump arrival ~=15.98 notif/s;
- Pump prepare p95 service 918.8ms with 12 workers implied tail capacity below arrival;
- PumpSwap normalization->reservation p95 6.320s;
- ingress->reservation p95 8.881s;
- 108 prepared PumpSwap items waiting reservation;
- SQLite writer and detector DB reads were not the dominant clocks.

## v49 systems amendment

Protocol:
`docs/route-research-v49-systems-stability-protocol-2026-09-07.md`

Changes only scheduling/identity timing:
- Pump prepare workers **12 -> 20**, sized from measured load;
- PumpSwap immutable pool identity resolution begins at ingress via prefetch;
- prefetch uses the same resolver/cache/history/per-pool single-flight/hydration budget/hedging;
- prefetch does not persist, reserve, detect, mutate episode state, retry, backfill or reorder FIFO;
- authoritative normalization/persistence remains the original path.

Do not relax the 5s gate.

## v50 causal clock diagnostic

Protocol:
`docs/route-research-v50-pumpswap-causal-clock-diagnostic-2026-09-07.md`

Purpose:
- observe the exact v49 scheduling path;
- attribute PumpSwap latency into self-normalization, global sequence barrier, reservation coordinator, reservation->submit and per-asset dependency;
- never collect forward SELL outcomes.

### First v50 live run

Run:
`route-research-systems-diagnostic-20260907-50`

Systems result:
- coverage 100.0%
- true backlog 0%
- Pump p95 3.324s
- PumpSwap p95 3.179s
- **11/11**

The systems evidence is valid, but the first tracer implementation was invalid because notification identity was not retained and the v20 normalization primitive bypassed the hook.

Those instrumentation bugs were fixed and regression-tested.

### v50b live run

Run:
`route-research-systems-diagnostic-20260907-50b`

Systems result:
- coverage **99.5%**
- true backlog **0.482%**
- Pump p95 **1.838s**
- PumpSwap p95 **4.002s**
- drops 0
- worker errors 0
- hydration budget skips 0
- reservation superset violations 0
- forward collector did not start
- **11/11**

Corrected tracer:
- ingress 3357/3357
- normalization 3357/3357
- reservations 3357/3357
- attributed rows 3357/3357
- submit/skip 3345/3357 = **99.643%**

Clock p95:
- self ingress->normalization: **369.3ms**
- global prefix normalization barrier: **3550.7ms**
- post-prefix reservation coordinator: **146.7ms**
- normalization->reservation: **3683.9ms**
- reservation->submit: **996.0ms**
- submit->dependency-ready: **672.4ms**

Dominant clock:
`global_sequence_barrier`

Representative blockers:
- seq 768: self-normalization 4.425s, 131 successors blocked, max successor wait 4.216s
- seq 307: self-normalization 4.211s, 138 successors blocked, max successor wait 4.143s
- seq 63: self-normalization 6.284s, 138 successors blocked, max successor wait 5.849s
- seq 33: self-normalization 8.934s, 29 successors blocked, max successor wait 8.560s

Interpretation:
- the global ingress-sequence normalization watermark is the dominant residual PumpSwap clock in v50b;
- this is direct systems evidence of head-of-line blocking;
- it does not authorize removing the watermark without a separate causality proof.

### v50 attribution acceptance rule

Do **not** add a post-deadline drain. v19 intentionally stops timed workers at the frozen 120s deadline; draining afterward would change the systems-gate semantics.

Barrier attribution requires exact coverage:
- ingress >0
- normalization == ingress
- reservations == ingress
- attributed rows == ingress

Later lifecycle comparison requires:
- submit/skip coverage >= **95%** of reservations.

Diagnostic output now separates:
- `barrier_attribution_complete`
- `lifecycle_attribution_complete`
- `lifecycle_submit_coverage_pct`
- `causal_clock_attribution_acceptable`

A clock attribution is accepted only when exact barrier coverage holds, later submit/skip coverage is >=95%, and the trace is non-empty.

## Route-only causal research semantics

Funding-free research only. Never freezes official `decision_as_of` and never signs/submits.

Frozen:
- BUY: USDC -> token
- taker=None
- non-executable route-only
- US$25 notional
- 100bps slippage parameter
- horizons 300 / 900 / 3600s
- SELL exact raw BUY output amount token -> USDC
- missing Jupiter route remains explicit

Provider pacing frozen from v44:
- hazard starts 650ms
- BUY starts 1000ms
- SELL starts 250ms
- no retry/backfill

## v46 / v47 discovery state

v46 A+B aggregate detector-population economics:
- 300s: n74, positive45.95%, mean -7.324%, median -0.233%, PF0.536
- 900s: n69, positive56.52%, mean -1.458%, median +1.363%, PF0.932
- 3600s: n66, positive39.39%, mean -27.359%, median -29.786%, PF0.371

Economic edge on the raw detector remains **NOT ESTABLISHED**.

v47 causal dataset audit:
- rows 79
- A39 / B40
- lineage violations 0
- missing decisions/episodes/hazard/entry quotes 0
- official decision mutations 0
- **PASS_V47_CAUSAL_DATASET_AUDIT**

Zero-coverage features in discovery sample:
- `flow30_notional_imbalance_pct`
- `flow30_return_pct`
- `entry_liquidity_usd`

Do not backfill discovery rows retrospectively.

## v48 prospective Flow60 hypothesis — FROZEN

Protocol:
`docs/route-research-v48-prospective-flow60-holdout-protocol-2026-09-06.md`

Primary feature:
`flow60_event_count`

Frozen bins:
- LOW <=25
- MID 26..47
- HIGH >47

Primary horizon:
**900s only**

Primary contrast:
**LOW vs HIGH**

MID is diagnostic only. 300s and 3600s are diagnostic only and cannot rescue the primary 900s result.

Discovery 900s evidence that motivated the hypothesis:

A LOW:
- n18
- median +1.969%
- PF1.179
- mean +2.312%
- mean_without_best -1.930%

A HIGH:
- n5
- median -30.760%
- PF0.416
- mean -19.476%

B LOW:
- n15
- median +1.529%
- PF2.905
- mean +28.414%
- mean_without_best +9.602%

B HIGH:
- n9
- median -1.088%
- PF0.346
- mean -20.021%

ALL LOW:
- n33
- median +1.529%
- PF2.026
- mean +14.177%
- mean_without_best +5.502%

ALL HIGH:
- n14
- median -15.924%
- PF0.372
- mean -19.826%

Hypothesis interpretation:
**flow saturation / move maturity** — unusually high event intensity already observed before `research_decision_as_of` may indicate a crowded/mature movement, while lower flow may indicate an earlier stage.

This is a hypothesis, not a trading rule.

Primary support gate at 900s:
- A LOW >=5 AVAILABLE and HIGH >=5 AVAILABLE
- B LOW >=5 AVAILABLE and HIGH >=5 AVAILABLE

Primary PASS requires ALL:
1. median LOW > HIGH in A
2. median LOW > HIGH in B
3. median LOW > HIGH in ALL
4. LOW median >0 in A and B
5. LOW PF >1 in A and B
6. aggregate LOW PF >1
7. aggregate LOW mean_without_best >0

Classifications:
- `PASS_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS`
- `INCONCLUSIVE_V48_PRIMARY_SUPPORT`
- `FAIL_V48_PROSPECTIVE_FLOW60_ROUTE_ONLY_HYPOTHESIS`
- acquisition/system-specific fail classifications remain fail-closed.

Even a v48 PASS does not release funded executable trading, shadow or live money.

## Funding / official executable path

Frozen official Jupiter BUY:
- provider `jupiter_swap_v2_order`
- purpose `entry_executable_buy_v1`
- USDC input
- US$25
- 100bps
- public taker only
- no signing/execute

Current status:
**BLOCKED_BY_FUNDING** because the configured taker has no required balance for official executable BUY assembly.

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

`getTokenLargestAccounts` is optional token-account concentration evidence, not holder concentration.

## Immediate next action

Do not run v48 yet.

Run one final fresh v50 replication under the corrected acceptance rule:

`python route_research_systems_diagnostic_v50.py --run-key route-research-systems-diagnostic-20260907-50c`

Accept systems profile for v48 wiring only if:
- same-run systems gate remains **11/11**;
- forward collector does not start;
- `barrier_attribution_complete=True`;
- `causal_clock_attribution_acceptable=True`.

If v50c passes those conditions:
1. freeze v49 as the validated systems scheduling profile;
2. wire that profile into a new v48 acquisition wrapper/path without changing the v48 evaluator;
3. add regression tests proving detector, Flow60 bins/horizon/gate and provider pacing remain unchanged;
4. CI;
5. use a completely new v48 base run key;
6. only then collect the true prospective holdout.

If v50c fails systems or attribution quality:
- do not rerun v48;
- do not relax the 5s gate;
- do not retune Flow60;
- use only systems diagnostics to decide the next engineering step.

## Shadow / live

- v46 discovery sample: complete
- v47 feature discovery/robustness: complete
- v48 Flow60: frozen, prospectively untested economically
- recent v49-profile systems evidence: two 11/11 runs
- v50b dominant causal clock: global sequence barrier
- profitable economic edge: not established
- official executable path: blocked by funding
- shadow: not released
- live money: not released
