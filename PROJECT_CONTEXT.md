# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado fica em `docs/`; aqui permanecem estado canônico, invariantes, gates e próxima ordem de trabalho.

## Estado atual

- Repositório: `murilloalvz/crypto-copy-trader`.
- Branch: `feat/exit-engine-v1`.
- Modo: **PAPER / RESEARCH / READ ONLY**.
- Tese ativa: **market-first Solana Opportunity Intelligence / Opportunity Engine**.
- Fluxo canônico:
  `market data -> unified radar -> detector -> opportunity episode -> wallets/flow/context -> execution/risk -> decision_as_of -> forward executable outcomes`.
- Pump native acquisition: PASS.
- PumpSwap native acquisition + causal pool resolution: PASS.
- Unified radar -> opportunity episode: PASS.
- Replay hardening observation -> pool mapping -> trigger/episode: CODE/CI/LIVE PASS; conflitos permanecem auditáveis.
- **Unified Market Latency v30: FORMAL PASS histórico/canônico.**
- **v31 executable quote live: FAIL** (`0/12` executable) e expôs regressão de robustez sob burst de unknown-pool hydration.
- **v32 batching: live FAIL**; reduziu RPCs, mas global reservation HOL permaneceu alto.
- **v33 hedged batching: near-PASS**, recuperou quase toda a latência; falhou apenas Pump/PumpSwap p95 por pequena margem.
- **v34 proof-based late continuation demotion: CODE/CI READY; live pendente.**
- Hazard/risk provider: ainda não integrado ao protocolo final.
- `decision_as_of`: ainda não congelado.
- Executable forward outcomes +5m/+15m/+60m: ainda não liberados.
- Economic edge/profitability: **não estabelecido**.
- Shadow/live money: **não liberado**.
- **Não iniciar coleta de 12h ainda.**

Documentos canônicos recentes:
- `docs/unified_market_latency_v30_pass.md`
- `docs/jupiter-executable-quote-v31-protocol-2026-09-04.md`

## North star

```text
market changes state
-> causal radar
-> opportunity episode
-> flow / microstructure
-> liquidity / execution
-> token hazard / manipulation risk
-> wallets actually present
-> optional simple regime
-> freeze decision_as_of
-> forward executable outcomes
```

Objetivo: identificar movimentos precoces cujo resultado forward, líquido de custos e com executabilidade realista, permaneça favorável fora da amostra.

## Princípios científicos congelados

- Histórico exploratório de P&L não é prova causal de edge.
- Detector/estratégia/coorte ficam congelados durante validação de infraestrutura/provedores.
- Separar qualidade do sinal, qualidade observacional, executabilidade, replay econômico e latência do sistema.
- Sem survivorship, lookahead, retroactive enrollment ou artificial backfill.
- No-sample não significa strategy failure.
- Wallet é contexto/evidência pós-episódio, nunca whitelist de aquisição.
- Nenhum live money sem forward evidence robusta e gate explícito.
- Não aumentar workers por tentativa; localizar primeiro o relógio dominante.
- PASS de latência significa somente systems latency/observability PASS, não profitability PASS.
- Missing/failure de provider deve permanecer explícito; nunca substituir por candle/quote posterior ou backfill.
- Primeiro trigger-to-episode **persistido** permanece canônico.
- Late-earlier não retrocede T0 e não cria episódio retroativo concorrente; fica auditado.

## Detector congelado

`src/market_opportunity_radar.py` — `market_opportunity_radar_v1_1_tx_aware`.

- fast window 30s;
- baseline horizon 300s;
- >=6 fast events;
- >=4 known unique wallets;
- established: >=3 baseline events e >=3x acceleration;
- fresh causal token age <=120s;
- se transaction identity coverage=100%, >=4 unique fast tx;
- direction é descritiva.

**Nenhum threshold foi ajustado por P&L ou pelos smokes live.**

## Causalidade / replay / continuation

Shared observations:
- exact replay idempotente;
- SQLite completion order não define causalidade;
- earliest collector `observed_at` vence;
- conflitos permanecem auditáveis.

No-op / continuation:
- detector pode permanecer level-triggered;
- resultado sem trigger é read-only e sai do stateful graph;
- continuation positiva de episódio já canônico continua auditável;
- apenas trabalho que pode alterar episode state permanece no caminho stateful ordenado.

Pump-specific replay: `pump_replay_conflicts`.
PumpSwap pool conflicts: `pumpswap_pool_mapping_conflicts`.

## PumpSwap identity / asset role

Reference assets v1: WSOL e USDC.

- exatamente um lado reference -> outro é opportunity token;
- opportunity token base -> side preservado;
- opportunity token quote -> side invertido;
- two-reference/two-unknown -> role_filtered;
- WSOL/USDC não podem virar opportunity episodes.

Pool identity:
- earliest observed mapping vence;
- conflicts auditados;
- cache/store/historical fast paths antes de rede;
- same-pool misses mantêm single-flight;
- expensive resolution bounded;
- mapping canônico recarregado antes da normalização final;
- se identidade só fica conhecida por RPC: `effective_observed_at=max(notification.observed_at, mapping.observed_at)`.

## Baseline de systems latency — v30 FORMAL PASS

Canonical live 2026-09-04:
- elapsed 120.2s;
- received Pump 3627 + PumpSwap 7739 = **11366**;
- processed **11287**;
- coverage **99.3%**;
- true backlog **0.695%**;
- Pump radar p95 **3.134s**;
- PumpSwap pipeline p95 **2.052s**;
- normalization->reservation p95 **1.035s**;
- prepared->submit p95 **0.246s**;
- worker errors 0;
- drops 0;
- `reference_asset_episodes=0`;
- hydration budget skips 0;
- `reservation_superset_violations=0`;
- bundles non-empty;
- replay/collision telemetry auditable.

Frozen 11-gate conditions:
1. no traceback/worker errors;
2. drops 0;
3. `reference_asset_episodes=0`;
4. coverage >=95%;
5. true total deadline backlog <=5%;
6. Pump radar p95 <=5s;
7. PumpSwap pipeline p95 <=5s;
8. hydration budget skips 0;
9. bundles não sistematicamente vazios;
10. replay counters auditáveis / sem corruption não explicada;
11. `reservation_superset_violations=0`.

O v30 permanece baseline histórico PASS; versões integradas devem satisfazer os mesmos gates no mesmo live run.

## v31 — executable quote FAIL + robustness regression

Primeiro live:
- coverage 99.7% PASS;
- backlog 0.277% PASS;
- Pump p95 **7.223s FAIL**;
- PumpSwap p95 **50.768s FAIL**;
- writer p95 saudável (~76ms);
- event loop p95 saudável (~29ms);
- network hydrations 299;
- normalization->reservation p95 ~50s.

Jupiter first 12:
- AVAILABLE=0;
- UNAVAILABLE=11;
- METADATA_ERROR=1;
- terminal coverage=100%;
- executable quotes=0;
- reused attempts=0;
- worker errors=0.

Formal: **FAIL**.

## v32 — batched unknown-pool hydration

Mudança:
- `getMultipleAccounts` microbatch para unknown pools;
- budget continua por pool;
- semaphore continua bounded=18;
- global reservation order/FIFO/as_of/replay/detector inalterados.

Live válido:
- received 8028;
- coverage **90.5% FAIL**;
- backlog **9.53% FAIL**;
- Pump p95 **3.965s PASS**;
- PumpSwap p95 **37.719s FAIL**;
- normalization->reservation p95 **27.340s**;
- 174 pool hydrations em 84 batches, avg batch 2.06;
- writer/prepare permaneceram saudáveis.

Conclusão: batching ajudou, mas retry/fallback serial ainda criava long sequence holes.

## v33 — hedged batched hydration

Mudança:
- mantém batching;
- até 2 RPC endpoints recebem uma tentativa em paralelo;
- primeiro resultado válido vence;
- remove retry/fallback sequencial do caminho crítico;
- mesmo detector, FIFO, reservation order, replay e episode semantics.

Live 2026-09-04:
- elapsed 125.2s;
- received **8918**;
- processed **8500**;
- coverage **95.3% PASS**;
- true backlog `418/8918 = 4.69%` **PASS**;
- errors 0;
- drops 0;
- ref episodes 0;
- budget skips 0;
- superset violations 0;
- bundles non-empty;
- Pump p95 **5.205s FAIL por 205ms**;
- PumpSwap p95 **5.354s FAIL por 354ms**;
- normalization->reservation p95 **4.356s**;
- prepared->submit p95 **3.691s**;
- writer batch p95 **139.6ms**;
- 76 pool hydrations, 70 hedged batches, 140 endpoint requests, all_hedges_failed=0.

Resultado: **9/11 latency gates PASS; #6 e #7 falham por pequena margem**.

A cauda restante ficou concentrada em hot assets:
- max waiting single asset: 34;
- alguns active waits ~17–21s;
- finalize causal dependency p95 global 0, mas rare hot-asset stateful followers permanecem presos atrás de um opener/predecessor.

Jupiter no mesmo run:
- selected 12;
- AVAILABLE=0;
- UNAVAILABLE=12;
- terminal coverage 100%;
- quotes persisted 12;
- executable quotes 0;
- worker errors 0.

## v34 — proof-based late continuation demotion

Goal: remover somente a cauda stateful morta dos hot assets sem relaxar FIFO para trabalho mutável.

Arquivos:
- `src/pumpswap_demoting_scheduler_v34.py`;
- `unified_market_execution_quote_smoke_v34.py`;
- `tests/test_pumpswap_demoting_scheduler_v34.py`;
- `tests/test_unified_market_execution_quote_smoke_v34.py`.

Semântica:
1. v27 continua sendo a autoridade de classificação por run-local canonical episode cache;
2. um job detector-positive pode entrar conservadoramente como stateful enquanto opener anterior ainda não commitou;
3. depois que o opener finaliza, pending jobs são rechecados com o **mesmo cache v27**;
4. somente jobs provados continuation-only têm o stateful reservation ticket convertido para `skip`;
5. payload demovido **não é descartado**: continua pelo finalizer normal para continuation audit/hits/metrics;
6. `complete()` posterior desse payload é no-op apenas para o ticket já consumido;
7. ambiguity/late-earlier/different-window continua strict FIFO;
8. ready/running work nunca é demovido;
9. detector, episode window, trigger identity, persistence, replay e Jupiter cohort permanecem congelados.

Importante: uma versão inicial do scheduler v34 descartava o payload demovido. Isso foi corrigido antes do live; testes agora exigem preservação explícita de continuation payload/audit path.

Pre-live validation:
- **679 tests / 0 failures**;
- compile PASS;
- wrapper restaura `v19.ReadyAssetScheduler` e `v27._EpisodeContinuationCache` em `finally`;
- hot-chain collapse, multiasset ordering e payload preservation cobertos.

Próximo gate: primeiro live v34 com o mesmo capacity/profile de v33. PASS exige novamente todos os 11 gates de latency, além de nenhum erro de demotion/audit e `demoted_finalizer_acks_pending=0` ao final.

## Current Jupiter executable quote protocol

Provider attempt lifecycle:
- STARTED antes de I/O;
- terminal: AVAILABLE, UNAVAILABLE, CONFIG_MISSING, PROVIDER_ERROR, METADATA_ERROR, NORMALIZATION_ERROR;
- terminal immutable;
- replay não reexecuta provider silenciosamente.

Frozen cohort/config:
- first 12 new admissions;
- 2 quote workers;
- input USDC;
- notional US$25;
- slippage 100bps;
- decimals via causal `getTokenSupply`;
- Jupiter timeout 5s;
- taker = public Solana address only;
- no private key/signing/execute/submit.

Executable quote PASS requer:
- os 11 latency gates verdes na mesma run;
- selected>0 (`0 => INCONCLUSIVE_NO_SAMPLE`);
- terminal coverage=100%;
- CONFIG_MISSING=0;
- quote_worker_errors=0;
- reused_attempts=0 fresh run;
- >=1 AVAILABLE executable quote persistido;
- clocks causais válidos;
- nenhum synthetic/backfill.

Não alterar notional/slippage/taker retroativamente para fabricar PASS antes de interpretar `reason=` do provider.

## Ordem congelada após executable-quote PASS

1. minimal hazard/risk provider com explicit missing/failure;
2. historical wallet outcomes pré-T0 quando aplicável;
3. freeze final `decision_as_of`;
4. executable forward outcomes +5m/+15m/+60m;
5. short true economic E2E smoke;
6. provider coverage/reconnect/dedup/clocks/cost audit;
7. hydration/rate/backpressure policy;
8. freeze runnable protocol;
9. primeira coleta de 12h.

## Shadow / live

- native acquisition: PASS;
- causal unified local bundle: PASS;
- replay integrity: hardened/auditable;
- systems latency baseline: v30 FORMAL PASS;
- integrated robustness: v33 near-PASS, v34 live pending;
- executable Jupiter entry quote: FAIL até demonstrar >=1 AVAILABLE;
- hazard/risk: pending;
- economic edge: not established;
- executable fill/landing: not validated;
- shadow/live: **not released**.
