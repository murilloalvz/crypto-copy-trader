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
- **Unified Market Latency v34: FORMAL PASS 11/11.**
- **Jupiter route availability no live v34: PASS 12/12** (`route_id` presente em todas as 12 tentativas).
- **Funded-taker executable assembly: BLOCKED_BY_FUNDING**; 12/12 retornaram `code=1 / Insufficient funds`, com transaction ausente.
- **v35 taker readiness:** taker configurado com `SOL=0`, `USDC=0`, déficit USDC `25`; classificação `INSUFFICIENT_USDC_AND_SOL`.
- Token hazard provider v1 via Solana Tracker: CODE/CI READY; live causal ainda pendente.
- `decision_as_of`: mecanismo de freeze já existe; readiness causal adicionada, mas **nenhum decision_as_of oficial deve ser congelado enquanto funded executability estiver bloqueada**.
- Forward outcomes +5m/+15m/+60m: schema/schedule CODE/CI READY; coleta econômica oficial ainda bloqueada.
- Economic edge/profitability: **não estabelecido**.
- Shadow/live money: **não liberado**.
- **Não iniciar coleta de 12h ainda.**

Bloqueio externo atual:
- o usuário não precisa financiar a wallet agora;
- a implementação de hazard/readiness/outcomes pode avançar em paralelo;
- isso **não altera a ordem dos gates finais** nem transforma funded executability em PASS.

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
- Um bloqueio de infraestrutura/funding não pode ser reclassificado como strategy failure.
- Reordenar **implementação** para aproveitar tempo enquanto um gate externo está bloqueado não muda a precedência da validação final.

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

## Baseline de systems latency — v30 FORMAL PASS histórico

Canonical live 2026-09-04:
- elapsed 120.2s;
- received Pump 3627 + PumpSwap 7739 = **11366**;
- processed **11287**;
- coverage **99.3%**;
- true backlog **0.695%**;
- Pump radar p95 **3.134s**;
- PumpSwap pipeline p95 **2.052s**;
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

## v31-v33 — caminho até robustez integrada

v31 executable quote live:
- executable quote `0/12`;
- burst de unknown-pool hydration expôs regressão de latência;
- Pump p95 7.223s FAIL;
- PumpSwap p95 50.768s FAIL.

v32 batching:
- `getMultipleAccounts` para unknown pools;
- coverage 90.5% FAIL;
- backlog 9.53% FAIL;
- PumpSwap p95 37.719s FAIL;
- mostrou que retry/fallback serial ainda produzia sequence holes.

v33 hedged batching:
- até 2 RPC endpoints em paralelo, uma tentativa por endpoint;
- coverage 95.3% PASS;
- backlog 4.69% PASS;
- Pump p95 5.205s FAIL por 205ms;
- PumpSwap p95 5.354s FAIL por 354ms;
- removeu o retry tail; cauda restante ficou em hot-asset stateful followers.

## v34 — proof-based late continuation demotion — FORMAL PASS

Arquivos principais:
- `src/pumpswap_demoting_scheduler_v34.py`;
- `unified_market_execution_quote_smoke_v34.py`;
- `tests/test_pumpswap_demoting_scheduler_v34.py`;
- `tests/test_unified_market_execution_quote_smoke_v34.py`.

Semântica:
1. v27 continua autoridade da classificação por run-local canonical episode cache;
2. follower detector-positive pode entrar conservadoramente como stateful antes do opener canônico;
3. depois do opener, pending jobs são rechecados com o mesmo cache;
4. só continuation-only provado pode ter stateful ticket convertido em skip;
5. payload demovido continua pelo finalizer normal para audit/hits/metrics;
6. ambiguity/late-earlier/different-window continua strict FIFO;
7. ready/running work nunca é demovido;
8. detector, episode window, trigger identity, persistence e replay permanecem congelados.

Live 2026-09-04:
- elapsed 120.1s;
- received **4892**;
- processed **4814**;
- coverage **98.4%**;
- true backlog `78/4892 = 1.594%`;
- errors/drops 0;
- ref episodes 0;
- budget skips 0;
- superset violations 0;
- bundles non-empty / replay auditable;
- Pump radar p95 **2.053s**;
- PumpSwap pipeline p95 **1.712s**;
- demoted pending jobs **83**;
- demoted finalizer acks pending **0**.

Resultado formal: **UNIFIED MARKET LATENCY v34 = PASS 11/11**.

Não mexer em scheduler/workers/SQLite/hydration sem nova evidência.

## Jupiter executable quote protocol — route PASS, funded assembly bloqueado

Provider:
- `jupiter_swap_v2_order`;
- purpose `entry_executable_buy_v1`;
- STARTED persistido antes de I/O;
- terminal immutable;
- replay não reexecuta provider silenciosamente.

Frozen config:
- first 12 new admissions;
- 2 quote workers;
- input USDC;
- notional US$25;
- slippage 100bps;
- decimals via causal `getTokenSupply`;
- Jupiter timeout 5s;
- taker = public Solana address only;
- sem private key/signing/execute/submit.

Live v34 persisted diagnostic:
- attempts 12;
- `route_id` presente **12/12**;
- routers OKX/DFlow;
- AVAILABLE 0;
- UNAVAILABLE 12;
- assembled transactions 0;
- reason 12/12: `code=1`, `Insufficient funds`.

Classificação correta:
- **route availability = PASS 12/12**;
- **funded executable assembly = BLOCKED_BY_FUNDING**;
- não inferir falha de rota, parser, detector ou estratégia a partir desse resultado.

Executable quote PASS final continua exigindo:
- 11 latency gates verdes na mesma run;
- selected>0 (`0 => INCONCLUSIVE_NO_SAMPLE`);
- terminal coverage 100%;
- CONFIG_MISSING 0;
- quote worker errors 0;
- reused attempts 0 fresh run;
- >=1 AVAILABLE com assembled transaction persistida;
- clocks causais válidos;
- nenhum synthetic/backfill.

## v35 — taker readiness

Arquivo:
- `jupiter_taker_readiness_v35.py`.

Preflight é READ ONLY:
- `getBalance` para SOL;
- `getTokenAccountsByOwner` para USDC;
- sem Jupiter order;
- sem signing/execute/transfer.

Estado observado:
- taker `DEoSVsCUAdszfYaxWwJrz3MfftByPNvNMe4aUu5BDgij`;
- SOL `0`;
- USDC `0`;
- required USDC `25`;
- deficit `25`;
- min SOL operacional do preflight `0.01`;
- classificação `INSUFFICIENT_USDC_AND_SOL`.

Enquanto isso permanecer assim, não gastar novas coortes oficiais tentando provar funded assembly.

## Token hazard provider v1 — CODE/CI READY

Arquivos:
- `src/opportunity_token_hazard.py`;
- `tests/test_opportunity_token_hazard.py`;
- integração em `src/opportunity_episode_enrichment.py`;
- testes de causalidade em `tests/test_opportunity_hazard_enrichment.py`.

Provider escolhido: Solana Tracker `GET /tokens/{mint}`, reutilizando a credencial/transport já existente no projeto.

Semântica:
- at-most-once por `(run, episode, provider, purpose)`;
- STARTED antes de provider I/O;
- terminal via `opportunity_provider_attempts`;
- CONFIG_MISSING / PROVIDER_ERROR / UNAVAILABLE / NORMALIZATION_ERROR explícitos;
- nenhuma ausência vira score sintético seguro;
- snapshot persiste `observed_at` local de aquisição;
- bundle só inclui hazard se `hazard.observed_at <= bundle.as_of`;
- evidência posterior nunca é backfilled em bundle anterior;
- nenhum threshold novo de entrada é criado aqui.

Campos normalizados descritivos:
- risk score;
- rugged;
- Jupiter verified;
- top10/dev/snipers/bundlers/insiders percentages;
- mint/freeze authority presence;
- provider risk factors + data-quality flags.

**Live causal provider validation ainda pendente.**

## Decision readiness — CODE/CI READY, freeze ainda bloqueado

Arquivo:
- `src/opportunity_decision_readiness.py`;
- `tests/test_opportunity_decision_readiness.py`.

Regras:
- não chama `freeze_market_opportunity_decision_as_of` automaticamente;
- funded executable AVAILABLE exige `assembled_transaction_present=True`;
- `UNAVAILABLE + Insufficient funds` => `BLOCKED_BY_FUNDING`;
- hazard precisa chegar a estado terminal, mas missing/error explícito não elimina silenciosamente o episódio;
- quando executability e hazard estiverem causalmente prontos, candidate `decision_as_of` = maior clock causal requerido;
- nenhum decision oficial é congelado enquanto funded executable gate estiver bloqueado.

## Forward outcomes +5m/+15m/+60m — infra CODE/CI READY

Arquivo:
- `src/opportunity_forward_outcome_store.py`;
- `tests/test_opportunity_forward_outcome_store.py`.

Regras:
- não agenda nada antes de `decision_as_of` congelado;
- horizons default exatos: 300 / 900 / 3600 segundos;
- target = `decision_as_of + horizon`;
- PENDING persistido de forma idempotente;
- observação não pode preceder target;
- AVAILABLE exige quote artifact executável;
- UNAVAILABLE/PROVIDER_ERROR permanecem explícitos;
- terminal immutable;
- nenhuma substituição por later candle / artificial backfill.

A infraestrutura está pronta, mas **não iniciar a coorte econômica oficial** até funded executability PASS.

## Ordem de trabalho enquanto funding está bloqueado

Implementação permitida em paralelo:
1. validar live o provider causal de token hazard sem alterar detector;
2. consolidar historical wallet outcomes estritamente pré-T0 quando aplicável;
3. validar readiness/bundle clocks e missingness;
4. preparar collector de forward executable outcomes sem iniciar coorte oficial;
5. preparar métricas/auditoria de provider e outcome.

Validação final continua congelada:
1. funded executable quote PASS;
2. minimal hazard/risk evidence com missing/failure explícito;
3. historical wallet outcomes pré-T0 quando aplicável;
4. freeze final `decision_as_of`;
5. executable forward outcomes +5m/+15m/+60m;
6. short true economic E2E smoke;
7. provider coverage/reconnect/dedup/clocks/cost audit;
8. hydration/rate/backpressure policy;
9. freeze runnable protocol;
10. primeira coleta de 12h.

## Shadow / live

- native acquisition: PASS;
- causal unified local bundle: PASS;
- replay integrity: hardened/auditable;
- systems latency integrated: **v34 FORMAL PASS 11/11**;
- Jupiter route availability: **PASS 12/12**;
- funded executable Jupiter entry: **BLOCKED_BY_FUNDING**;
- token hazard: CODE/CI READY, live pending;
- decision_as_of: readiness ready, official freeze pending;
- forward outcomes: schema ready, official collection pending;
- economic edge: not established;
- executable fill/landing: not validated;
- shadow/live: **not released**.
