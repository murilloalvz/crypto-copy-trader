# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado permanece em `docs/`; aqui ficam estado canônico, invariantes, gates e próxima ordem de trabalho.

## Estado atual

- Repositório: `murilloalvz/crypto-copy-trader`.
- Branch: `feat/exit-engine-v1`.
- Modo: **PAPER / RESEARCH / READ ONLY**.
- Tese ativa: **market-first Solana Opportunity Intelligence / Opportunity Engine**.
- Fluxo canônico oficial:
  `market data -> unified radar -> detector -> opportunity episode -> flow/wallet/context -> execution/hazard -> official decision_as_of -> executable forward outcomes -> economic validation -> shadow`.
- Trilha paralela de pesquisa sem funding:
  `fresh episode -> on-chain hazard -> route-only BUY -> research_decision_as_of -> route-only SELL +5/+15/+60 -> descriptive causal forward evaluation`.

Status canônico:

- Pump native acquisition: **PASS**.
- PumpSwap native acquisition + causal pool resolution: **PASS**.
- Unified radar -> causal opportunity episode: **PASS**.
- Replay / continuation hardening: **PASS / auditável**.
- **Unified Market Latency v34/v37: FORMAL PASS 11/11.**
- **Jupiter route availability: PASS 12/12.**
- **Funded executable BUY assembly: BLOCKED_BY_FUNDING.**
- v35 taker readiness: `SOL=0`, `USDC=0`, déficit USDC `25`, `INSUFFICIENT_USDC_AND_SOL`.
- Solana Tracker hazard v36: **FAIL / BLOCKED_BY_PROVIDER_CREDITS** — 12/12 `HTTP 403: Insufficient credits for this request`.
- **Solana RPC on-chain hazard v37: FORMAL PROVIDER PASS 12/12**, no mesmo live em que latency também passou 11/11.
- Wallet market-first history v38: **lineage causal correta / official history sample INCONCLUSIVE**; diagnóstico real encontrou 0 prior official decisions e 0 associations, como esperado.
- v39 official-forward route-only plumbing: **CODE/CI PASS**, mas não promove official outcomes.
- v40 route-only causal economic research: **CODE/CI PASS; LIVE PENDING**.
- Official `decision_as_of`: mecanismo/readiness CODE/CI READY; **nenhum freeze oficial enquanto funded executable BUY estiver bloqueado**.
- Official executable forward outcomes +5m/+15m/+60m: infra READY; coleta executável oficial ainda bloqueada.
- Route-only forward research +5m/+15m/+60m: fresh-run harness + collector + evaluator **CODE/CI PASS; first live cohort pending**.
- Economic edge/profitability: **NOT ESTABLISHED**.
- Shadow/live money: **NOT RELEASED**.
- **Não iniciar coleta oficial de 12h ainda.**

Bloqueios externos não são strategy failure:
- funding pode esperar;
- créditos do Solana Tracker não serão comprados apenas para fabricar PASS;
- v37 remove a dependência do Solana Tracker para hazard mínimo;
- route-only research permite estudar forward economics sem funding, mas não substitui o futuro gate executável/shadow.

## Princípios congelados

- Histórico exploratório de P&L não é prova causal de edge.
- Detector/estratégia/coorte ficam congelados durante validação.
- Separar signal quality, observability, route availability, assemblability, landing/fill, economic replay e systems latency.
- `route available != assemblable transaction != landed transaction != fill`.
- No-sample não significa strategy failure.
- Wallet é evidência pós-episódio, nunca acquisition whitelist.
- Um outcome de oportunidade onde uma wallet apareceu **não é P&L realizado da wallet**.
- Missing/failure permanece explícito; nunca substituir por candle/quote/snapshot posterior.
- Primeiro trigger-to-episode **persistido** permanece canônico.
- Late-earlier não retrocede T0 e não abre episódio retroativo concorrente.
- PASS de systems latency não significa profitability PASS.
- Não aumentar workers por tentativa; primeiro localizar o relógio dominante.
- Nenhum live money sem forward evidence robusta + gate explícito.
- Features de hazard/wallet permanecem descritivas até demonstrarem valor incremental out-of-sample.
- Não criar threshold/score porque uma feature “parece boa” ou porque histórico favorece um corte.
- Reordenar implementação por blocker externo não muda a precedência da validação final.
- **Nunca retro-enrolar episódio antigo numa coorte forward.** Route-only v40 precisa nascer em fresh run.

## Detector congelado

`src/market_opportunity_radar.py`

Version: `market_opportunity_radar_v1_1_tx_aware`.

- fast window 30s;
- baseline 300s;
- >=6 fast events;
- >=4 known unique wallets;
- established: >=3 baseline events e >=3x acceleration;
- fresh causal token age <=120s;
- com transaction identity coverage=100%: >=4 unique fast tx;
- direction é descritiva.

**Nenhum threshold foi ajustado por P&L ou pelos smokes live.**

## Systems latency — formal gate congelado

ALL:
1. no traceback/worker errors;
2. drops 0;
3. `reference_asset_episodes=0`;
4. coverage >=95%;
5. true total deadline backlog <=5% de received;
6. Pump radar p95 <=5s;
7. PumpSwap causal pipeline p95 <=5s;
8. hydration budget skips 0;
9. bundles não sistematicamente vazios;
10. replay/collision counters auditáveis, sem corruption não explicada;
11. `reservation_superset_violations=0`.

### v34 canonical live
- received 4892;
- processed 4814;
- coverage 98.4%;
- true backlog 1.594%;
- Pump p95 2.053s;
- PumpSwap p95 1.712s;
- errors/drops/ref/budget/superset violations = 0.

Resultado: **PASS 11/11**.

### v37 retained live
Run `unified-market-onchain-hazard-smoke-20260904-37`:
- received 5781;
- processed 5771;
- coverage 99.8%;
- true backlog 0.173%;
- Pump p95 1.397s;
- PumpSwap p95 1.695s;
- drops/errors/ref/budget/superset violations = 0.

Resultado: **PASS 11/11**.

Não mexer em scheduler/workers/SQLite/hydration sem nova evidência.

## Jupiter executable BUY — official gate

Provider `jupiter_swap_v2_order`, purpose `entry_executable_buy_v1`.

Frozen research sizing for this gate:
- input USDC;
- notional US$25;
- slippage 100bps;
- taker public address only;
- no private key/signing/execute.

Persisted diagnostic:
- route_id 12/12;
- assembled transaction 0/12;
- reason 12/12 `Insufficient funds`.

Classificação:
- route availability: **PASS 12/12**;
- funded executable assembly: **BLOCKED_BY_FUNDING**.

Official executable BUY PASS still requires fresh same-run latency PASS, terminal coverage100%, no config/worker/reuse/causal errors and >=1 AVAILABLE assembled transaction artifact.

## Hazard

### v36 Solana Tracker
Historical result remains **FAIL / BLOCKED_BY_PROVIDER_CREDITS**. Do not rewrite as PASS.

### v37 on-chain minimal hazard
Provider `solana_rpc_mint_hazard_v1`, purpose `token_hazard_minimal_v1`.

Core:
- SPL Token / Token-2022;
- decimals / supply;
- mint authority;
- freeze authority;
- Token-2022 extensions when exposed;
- context slot.

Live v37:
- selected12;
- AVAILABLE12;
- terminal coverage100%;
- core complete12;
- worker/reuse/causal violations0.

Classificação: **PASS_CAUSAL_ONCHAIN_HAZARD_PROVIDER**.

`getTokenLargestAccounts` auxiliary failed 12/12. This is explicit missingness, not a blocker and not silently relabeled as holder concentration.

## Wallet market-first history v38

Strict pre-T0 lineage:
- prior official decision < current T0;
- prior outcome observed_at < current T0;
- prior SELL quote observed_at < current T0;
- same-second equality excluded due second-resolution ambiguity;
- current episode cannot leak into own history;
- legacy Discovery/Copyability, leaderboard PnL, old wallet-forward and exploratory v2/v3 do not supply official labels.

`executable_quote_return_pct` is an opportunity association label and remains distinct from wallet `realized_return_pct`.

### Persisted v38 diagnostic
Run inspected: `unified-market-onchain-hazard-smoke-20260904-37`.

- episodes=12;
- participant wallet observations=194;
- candidate prior official episodes=0;
- eligible labels=0;
- matching prior episodes=0;
- associations=0;
- no prior official decisions: 12/12;
- no valid market-first history sample: 12/12.

Classification: **INCONCLUSIVE_NO_OFFICIAL_MARKET_FIRST_HISTORY_SAMPLE**.

Interpretation: correct causal behavior. Zero clean history is preferred to contaminated history. This is not edge evidence.

## Official forward outcomes

`src/opportunity_forward_outcome_store.py`:
- requires frozen official `decision_as_of`;
- exact 300/900/3600s targets;
- AVAILABLE requires executable quote artifact;
- terminal immutable;
- no later candle/backfill.

Official collection remains blocked behind funded executable BUY.

## v39 — official-schedule route-only SELL plumbing

`src/jupiter_forward_exit_route.py` and `forward_exit_route_probe_v39.py` prepare causal SELL route observation for a future official schedule without ever completing official outcomes.

- amount = exact prior executable BUY `output_amount_raw`;
- exact target;
- `taker=None`;
- valid route quote must be `executable=False`;
- no signing/execute/private key;
- unexpected assembled tx fails closed.

Status: **CODE/CI PASS**. This is plumbing only.

## v40 — route-only causal forward economic research

Protocol: `docs/route-only-forward-research-v40-protocol-2026-09-04.md`.

Purpose: collect honest causal paper forward economics without funding while preserving official executable/shadow gates.

### Separate research identity

v40 introduces a separate immutable `research_decision_as_of` in `opportunity_route_research_decisions`.

It **never writes** `market_opportunity_episodes.decision_as_of`.

Fresh sequence:

```text
fresh market episode
-> v37 on-chain hazard AVAILABLE
-> Jupiter route-only BUY (USDC -> token, taker=None)
-> research_decision_as_of = max causal evidence clocks
-> exact +300/+900/+3600 schedule
-> route-only SELL (token -> USDC, taker=None)
-> descriptive quote-to-quote evaluation
```

### Entry rules

`src/jupiter_research_entry_route.py`
- provider `jupiter_swap_v2_order`;
- purpose `entry_route_only_research_v1`;
- frozen $25 research notional;
- 100bps slippage parameter;
- token decimals reused from causal v37 hazard Mint evidence;
- valid quote MUST remain `executable=False`;
- assembled transaction unexpectedly present => fail closed;
- no taker/signing/execute/transfer.

### Research decision/outcome store

`src/opportunity_route_research_store.py`
- separate tables from official outcomes;
- immutable research decision;
- exact 300/900/3600 targets;
- research AVAILABLE requires causal non-executable SELL quote at/after target;
- no fallback between horizons;
- no backfill.

### Exit rules

`src/jupiter_research_exit_route.py`
- SELL amount raw = exact route-only BUY `output_amount_raw`;
- token -> USDC;
- `taker=None`;
- quote must remain non-executable;
- target lateness explicit;
- only research outcome can be completed; official outcome remains untouched.

### Fresh integrated smoke

`unified_market_route_research_smoke_v40.py`
- retains v37 market/hazard architecture;
- first 12 fresh research episodes by default;
- waits for causal v37 hazard terminal evidence;
- captures fresh route-only BUY;
- freezes separate research clock;
- schedules +5/+15/+60;
- audits official decision mutation, clock, scheduling, reuse, worker and executable-semantic violations.

Formal plumbing classification can be `PASS_ROUTE_ONLY_RESEARCH_DECISION_PLUMBING`, but only after live run. **Current live status: PENDING.**

### Forward collector

`route_research_forward_collector_v40.py`
- polls only due research outcomes;
- no pre-target observation;
- captures SELL route promptly at target;
- runs through +60m when invoked for a fresh cohort;
- no official outcome writes.

### Evaluation

`src/route_research_evaluation.py` / `route_research_evaluate_v40.py` report per horizon:
- coverage;
- positive share;
- mean/median route return;
- Profit Factor;
- best/worst;
- mean without best winner;
- largest winner share of gross positive return;
- lineage violations.

Label:
`route_quote_return_pct = 100 * (SELL route price / BUY route price - 1)`.

It is NOT realized wallet PnL, landing/fill PnL or proof of executable profitability.

Samples with <30 AVAILABLE observations remain **INCONCLUSIVE_SAMPLE_LT_30**.

Current v40 status: **CODE/CI PASS; LIVE PENDING**.

## Current order of work

Without funding:
1. keep v34/v37 latency and hazard frozen;
2. run one **fresh v40** 120s decision-plumbing smoke;
3. if it schedules research outcomes, start the v40 forward collector immediately for the same run so +5/+15/+60 targets are not backfilled;
4. evaluate the completed route-only cohort;
5. if plumbing is clean, expand sample without changing detector/features/thresholds;
6. only after enough clean labels perform ablation/time-split and wallet/hazard/flow incremental-value analysis;
7. never use v40 route-only data to declare executable/live readiness.

When funding becomes available:
1. v35 preflight READY;
2. fresh funded executable BUY gate PASS;
3. official decision freeze;
4. official executable forward/shadow exit evidence;
5. landing/fill/cost/dedup/reconnect audit;
6. robust forward validation;
7. first official 12h collection only after runnable protocol freeze.

## Shadow / live

- systems acquisition/latency: **PASS**;
- Jupiter route: **PASS**;
- funded executable BUY: **BLOCKED_BY_FUNDING**;
- Solana Tracker hazard: **BLOCKED_BY_PROVIDER_CREDITS**;
- on-chain hazard v37: **PASS**;
- wallet history v38: **LINEAGE CORRECT / OFFICIAL SAMPLE INCONCLUSIVE**;
- v39 route-only official-schedule plumbing: **CODE/CI PASS**;
- v40 causal route-only forward research: **CODE/CI PASS / LIVE PENDING**;
- official decision_as_of: pending;
- official executable forward outcomes: pending;
- economic edge: **NOT ESTABLISHED**;
- shadow/live money: **NOT RELEASED**.
