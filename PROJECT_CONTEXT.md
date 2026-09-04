# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado fica em `docs/`; aqui permanecem somente estado canônico, invariantes, configuração validada, gates e próxima ordem de trabalho.

## Estado atual

- Repositório: `murilloalvz/crypto-copy-trader`.
- Branch de pesquisa: `feat/exit-engine-v1`.
- Modo: **PAPER / RESEARCH / READ ONLY**.
- Tese ativa: **market-first Solana Opportunity Intelligence / Opportunity Engine**.
- Fluxo canônico:
  `market data -> unified radar -> detector -> opportunity episode -> wallets/flow/context -> execution/risk -> decision_as_of -> forward executable outcomes`.
- Pump native acquisition: PASS.
- PumpSwap native acquisition + causal pool resolution: PASS.
- Pump/PumpSwap -> unified radar -> opportunity episode: PASS.
- Unified causal flow/wallet bundle semantics: PASS.
- Replay hardening observation -> pool mapping -> trigger/episode: CODE/CI/LIVE PASS; conflitos permanecem auditáveis.
- **Unified Market Latency Gate: FORMAL PASS via v30.**
- Jupiter executable quote para novo episode: **CODE/CI pronto; primeiro live v31 ainda não executado**.
- Hazard/risk provider: ainda não integrado ao protocolo final.
- Final `decision_as_of`: ainda não congelado.
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
- Separar: qualidade do sinal, qualidade observacional, executabilidade, replay econômico e latência do sistema.
- Sem survivorship, lookahead, retroactive enrollment ou artificial backfill.
- No-sample não significa strategy failure.
- Wallet é contexto/evidência pós-episódio, nunca whitelist de aquisição.
- Nenhum live money sem forward evidence robusta e gate explícito.
- Não aumentar workers por tentativa; localizar primeiro o relógio dominante e dimensionar por evidência.
- PASS de latência significa somente **systems latency/observability PASS**, não economic edge/profitability PASS.
- Missing/failure de provider deve permanecer explícito; nunca substituir silenciosamente por candle, quote posterior ou dado histórico.

## Detector congelado

`src/market_opportunity_radar.py` — `market_opportunity_radar_v1_1_tx_aware`.

Acquisition mechanics:
- fast window 30s;
- baseline horizon 300s;
- >=6 fast events;
- >=4 known unique wallets;
- established: >=3 baseline events e >=3x activity-rate acceleration;
- fresh token: causal token age <=120s;
- quando transaction identity coverage =100%, >=4 unique fast transactions;
- direction é descritiva.

**Nenhum threshold foi ajustado por P&L ou pelos live smokes.**

## Causalidade e replay

Shared market observations:
- exact replay idempotente;
- SQLite completion order não define causalidade;
- earliest collector `observed_at` vence;
- identidade conflitante fica em `market_replay_conflicts`;
- conflito não vira flow novo nem derruba aquisição.

Trigger/episode:
- replay do mesmo trigger não cria novo episode/enrichment;
- primeiro trigger-to-episode **persistido** permanece canônico;
- late-earlier trigger que sobreporia episode já persistido não retrocede T0 e não abre episódio retroativo concorrente; fica auditado;
- divergência fica em `market_trigger_replay_conflicts`;
- corrupção referencial real continua fatal.

No-op / continuation:
- detector pode permanecer level-triggered;
- resultado sem trigger é read-only e sai do stateful dependency graph;
- continuation positiva de episódio já canônico continua auditável, mas não paga novo commit causal de episode;
- apenas trabalho que pode alterar episode state entra no caminho stateful ordenado.

Pump-specific replay: `pump_replay_conflicts`.
PumpSwap pool conflicts: `pumpswap_pool_mapping_conflicts`.

Lifecycle:
- Pump `CreateEvent` = token birth;
- PumpSwap `CreatePoolEvent` = venue/pool lifecycle, não token birth.

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
- histórico ambíguo não é reutilizado;
- causal cache hit em memória bypassa lock/semaphore de resolução cara;
- same-pool misses mantêm single-flight;
- resolução cara/rede continua bounded;
- mapping canônico é recarregado antes da normalização final.

## Arquitetura vencedora de acquisition/radar — v30

```text
Pump + PumpSwap logsSubscribe
        |
        +--> causal normalization / pool identity
        |       cache/store fast path
        |       expensive RPC resolution bounded=18
        |
        +--> optimistic observation persistence
        |       insert-first common path
        |       replay SELECT somente após collision
        |       PumpSwap affected-token readback por microbatch
        |       SQLite WAL / one thread-owned microbatch writer
        |
        +--> conservative early asset reservation
        |
        +--> parallel causal read/detect prepare
        |       Pump prepare threads=12
        |       PumpSwap submitters=64
        |       PumpSwap prepare executor threads=32
        |
        +--> no-trigger / continuation fast paths
        |
        +--> per-asset stateful ordering somente quando necessário
        |
        +--> trigger / canonical opportunity episode
        |
        +--> episode admission + enrichment
```

Validated v30 capacity profile:
- duration: 120s;
- commitment: confirmed;
- Pump batch: 32 / 25ms;
- Pump prepare workers: 12;
- PumpSwap orchestration coroutines: 256;
- PumpSwap prepare submitters: 64;
- PumpSwap prepare executor threads: 32;
- default blocking-I/O executor: 32;
- max concurrent expensive pool resolutions: 18;
- PumpSwap SQLite writer threads: 1;
- writer batch: 32 / 10ms;
- queue size: 5000;
- max hydrations: 1500;
- SQLite WAL + IMMEDIATE writer admission;
- continuation audit remains durable and drains at shutdown.

Important: 256 PumpSwap orchestration coroutines **não** significam 256 RPCs ou 256 SQLite writers. External/expensive work remains bounded as above.

## Unified Market Latency v30 — FORMAL PASS

Canonical live result, 2026-09-04:
- elapsed: 120.2s;
- received: Pump 3627 + PumpSwap 7739 = **11366**;
- processed: Pump 3600 + PumpSwap 7687 = **11287**;
- combined arrival rate: ~94.6 notifications/s;
- coverage: **99.3%**;
- true backlog: `(11366 - 11287) / 11366 = 0.695%`;
- Pump radar p95: **3.134s**;
- PumpSwap pipeline p95: **2.052s**;
- PumpSwap normalization->reservation p95: **1.035s**;
- PumpSwap prepared->submit p95: **0.246s**;
- worker errors: 0;
- drops: 0;
- `reference_asset_episodes`: 0;
- hydration budget skips: 0;
- `reservation_superset_violations`: 0;
- bundles: non-empty in aggregate (`wallets_total=3059`, `flow30_total=4229`);
- replay/collision telemetry: auditable, no unexplained corruption.

Frozen latency PASS conditions — all satisfied by v30:
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

**Não reabrir esse gate sem evidência de regressão.** Alterações futuras que compartilhem recursos com acquisition devem demonstrar que não quebram essas condições, mas o PASS v30 permanece o baseline canônico.

## Estágio atual — Jupiter executable quote v31

Goal: obter uma evidência de entrada executável/route-aware somente para **novo episode admitido**, sem assinatura ou envio de transação.

Código principal:
- `src/jupiter_swap_v2.py` — Jupiter `/order` read-only / assembly;
- `src/causal_quotes.py` + `src/causal_quote_store.py` — modelo/store causal;
- `src/opportunity_provider_attempt_store.py` — lifecycle genérico de provider attempt;
- `src/jupiter_episode_execution.py` — probe por episódio;
- `unified_market_execution_quote_smoke_v31.py` — primeiro live smoke.

Pre-live validation:
- HEAD/protocolo v31 validado em GitHub Actions;
- **666 tests / 0 failures** no run que inclui a camada v31 e seus invariantes;
- live v31 ainda pendente.

Provider attempt lifecycle:
- `STARTED` é persistido antes de I/O;
- terminal: `AVAILABLE`, `UNAVAILABLE`, `CONFIG_MISSING`, `PROVIDER_ERROR`, `METADATA_ERROR`, `NORMALIZATION_ERROR`;
- terminal é imutável;
- crash com `STARTED` permanece visível;
- replay de attempt não reexecuta provider silenciosamente.

Frozen first-smoke cohort/config:
- primeiros 12 **novos admissions** da run, em ordem;
- 2 quote workers;
- input USDC;
- notional US$25;
- slippage request 100 bps;
- token decimals via causal `getTokenSupply` lookup/cache;
- Jupiter timeout 5s;
- taker = public Solana address configurado em `JUPITER_TAKER_PUBLIC_KEY`;
- nenhuma private key carregada;
- nenhum signing;
- nenhum execute/submit.

Causal rules:
1. provider só é enfileirado após `admit_opportunity_episode(...) == True`;
2. continuation/replay não cria provider call novo;
3. `quote.observed_at >= episode.first_trigger_observed_at` obrigatório;
4. missing/error não recebe substituição posterior;
5. `AVAILABLE` requer artifact com `executable=True` / assembled candidate transaction;
6. candidate transaction assembly não prova landing/fill.

Gate v31 completo está congelado em:
`docs/jupiter-executable-quote-v31-protocol-2026-09-04.md`.

Resumo mandatory para PASS do primeiro live:
- v30 market-latency conditions continuam verdes durante a run;
- selected > 0 (zero sample => `INCONCLUSIVE_NO_SAMPLE`);
- terminal coverage = 100%;
- nenhuma tentativa selecionada termina em `STARTED`;
- `CONFIG_MISSING=0`;
- `quote_worker_errors=0`;
- fresh run: `reused_attempts=0`;
- pelo menos 1 `AVAILABLE` executable quote persistido;
- clocks causais válidos;
- sem synthetic/backfilled provider evidence.

Não existe threshold arbitrário de `% AVAILABLE` no primeiro smoke; distribuição de statuses é evidence descritiva para provider coverage.

## Ordem congelada após v31 PASS

1. minimal hazard/risk provider com explicit missing/failure e provider-attempt lifecycle;
2. historical wallet outcomes resolvidos antes de T0 quando aplicável;
3. freeze final `decision_as_of` após provider attempts obrigatórias;
4. forward executable outcomes +5m/+15m/+60m;
5. short true economic E2E smoke;
6. auditar provider coverage/reconnect/dedup/clocks/cost;
7. definir hydration/rate/backpressure policy;
8. congelar protocolo runnable;
9. somente então primeira coleta de 12h.

## Avaliação econômica futura

Outcomes +5m/+15m/+60m com semântica executável/route-aware quando possível. Nunca substituir silenciosamente quote/fill ausente por candle posterior.

Ablations: movement, flow, execution, wallet e risk.

Métricas mínimas:
- mean/median;
- win rate;
- profit factor;
- drawdown;
- coverage;
- token/cluster concentration;
- top-winner contribution;
- robustez removendo top1/top3 winners.

## Shadow / live

- native acquisition: Pump PASS / PumpSwap PASS;
- causal unified local bundle: PASS;
- replay integrity: hardened e auditável;
- unified systems latency: **FORMAL PASS v30**;
- executable Jupiter entry quote: code/CI ready, first live v31 pending;
- hazard/risk integration: pending;
- economic edge: not established;
- executable fill/landing: not validated;
- shadow/live: **not released**.
