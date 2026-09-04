# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado pode ficar em `docs/`; aqui permanecem decisões canônicas, evidência live relevante, invariantes e gates que controlam o próximo passo.

## Estado atual

- Repositório: `murilloalvz/crypto-copy-trader`.
- Branch de pesquisa: `feat/exit-engine-v1`.
- Modo: **PAPER / RESEARCH / READ ONLY**.
- Tese ativa: **market-first Solana Opportunity Intelligence / Opportunity Engine**.
- Fluxo: `market data -> unified radar -> detector -> opportunity episode -> wallets/flow/context -> execution/risk -> decision_as_of -> forward executable outcomes`.
- Pump native acquisition: PASS.
- Pump -> radar -> opportunity episode: PASS.
- PumpSwap native acquisition + causal pool resolution: PASS.
- Unified causal flow/wallet bundle semantics: PASS.
- Replay hardening observation -> pool mapping -> trigger/episode: CODE/CI/LIVE PASS; conflitos permanecem auditáveis.
- Pump latency: PASS via ordered SQLite microbatch.
- PumpSwap latency: **ainda não fechou o gate formal**.
- Último live smoke canônico: **v19c**; coverage/backlog/Pump/safety passaram, PumpSwap pipeline p95 ficou em **6.281s** (>5s).
- Última correção de código após v19c: cache hits causais do concurrent PumpSwap resolver agora bypassam o semaphore destinado a resolução cara/rede. CI: **608/608 PASS**.
- Próxima execução: mesmo `unified_market_latency_smoke_v19.py`, mesmos parâmetros, nova run key; objetivo é medir somente o efeito do resolver cache fast path.
- Jupiter executable quotes, hazard/risk provider, final `decision_as_of`, executable forward outcomes e historical wallet outcomes continuam bloqueados até o latency gate PASS.
- **Não iniciar coleta de 12h ainda.**

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
- Detector/estratégia/coorte ficam congelados durante validação de infraestrutura.
- Separar: qualidade do sinal, qualidade observacional, executabilidade, replay econômico e latência do sistema.
- Sem survivorship/lookahead/retroactive enrollment/artificial backfill.
- No-sample não significa strategy failure.
- Wallet é contexto/evidência pós-episódio, nunca whitelist de aquisição.
- Nenhum live money sem forward evidence robusta e gate explícito.
- Não aumentar workers por tentativa; primeiro localizar o relógio dominante.
- PASS de latência significa apenas **systems latency/observability PASS**, não economic edge/profitability PASS.

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
- divergência de recomputação fica em `market_trigger_replay_conflicts`;
- primeiro trigger-to-episode persistido permanece canônico;
- corrupção referencial real continua fatal.

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
- reusable resolver pode reaproveitar identidade imutável aprendida antes de T0;
- concurrent resolver mantém single-flight por pool e recarrega mapping canônico persistido antes de normalizar;
- após v19c, cache hit causal em memória bypassa lock/semaphore de resolução cara; o semaphore continua limitando misses que podem chegar a store/historical/network.

## Arquitetura PumpSwap atual

```text
logsSubscribe notification
        |
        v
64 async persistence/normalization workers
        |
        +--> causal pool resolve/normalize
        |       |
        |       +--> in-memory causal cache fast path
        |       +--> single-flight + bounded expensive resolution on miss
        |
        +--> conservative early reservation hint
        |       watermark = post-normalization / pre-writer-result
        |
        +--> thread-owned SQLite microbatch writer
        |       batch 32 / 10ms, WAL
        |       authoritative canonical persist result
        |
        +--> 48 async prepare submitters
                12 dedicated prepare executor threads
                canonical tx view + causal history + frozen detector
                        |
                        v
                per-asset FIFO scheduler
                direct ticket-successor release
                        |
                        v
                1 stateful finalizer
                trigger/episode assignment
                        |
                        v
                episode-scoped enrichment
```

Important invariants:
1. preparation cria zero side effects de trigger/episode;
2. detector prepare só inicia após canonical SQLite persistence;
3. early reservation asset set é um conservative superset;
4. `reservation_superset_violations > 0` é fatal/fail closed;
5. no-new-evidence/duplicate atravessa o mesmo FIFO como no-op release;
6. final trigger/episode assignment preserva FIFO para notifications que compartilham opportunity asset;
7. multi-asset notification espera todos os predecessores relevantes;
8. trigger key permanece `market-radar:pumpswap-v3:<signature>:<mint>`;
9. detector config, `token_as_of`, episode window, replay e provider policy permanecem congelados.

## Evolução da unified latency

### v7-v10 — descobrir os gargalos

- v7: coverage 81.9%, PumpSwap p95 65.05s. Worker slot starvation por predecessor do mesmo asset.
- v8: nonblocking per-asset scheduler removeu starvation; coverage 75.6%, PumpSwap p95 54.973s. Gross capacity deficit.
- v9: coverage 97.3%, backlog ~2.74%, Pump p95 1.798s, PumpSwap p95 18.311s. Service local barato; espera dominava.
- v10: pipeline p95 90.996s; causal dependency 54.449s; ready queue 10.644s; DB 106.9ms; detector 0.3ms. Hot-asset serialization era dominante.

Conclusão: serializar avaliação inteira por asset era errado; somente a fase stateful de trigger/episode precisa FIFO estrito.

### v11 — parallel prepare / FIFO finalize

- 8 prepare workers: causal p95 caiu para 346ms, mas prepare queue p95 50.387s.
- 12 prepare workers: prepare queue 30.187s, service 1.127s; scaling ruim.

Conclusão: split causal correto; bottleneck mudou para prepare capacity/resumption.

### v12 — dedicated prepare executor

- coverage 94.0%; Pump 2.320s;
- prepare queue 10.683s;
- persistence queue 20.108s;
- pipeline 36.416s.

Conclusão: prepare executor ajudou e expôs reader/writer interference.

### v13 — SQLite WAL

- coverage 91.4%; Pump 3.645s;
- persistence queue 0.721s;
- persistence service 68ms;
- prepare queue 21.119s;
- pipeline 23.039s.

Conclusão: WAL resolveu reader/writer contention; atraso restante não era custo do detector.

### v14 — hidden-time diagnostic

- coverage ~95.2%; Pump ~3.965s;
- persistence queue ~0.671s;
- prepare queue ~20.557s;
- outer prepare service ~1.367s;
- inner prepare total p95 ~86ms;
- unaccounted inside thread ~0.1ms;
- pipeline ~21.825s.

Conclusão: thread terminava rápido; coroutine demorava para retomar. Event-loop/executor resumption starvation confirmado.

### v15 — dedicated SQLite writer

- coverage ~85.2%;
- Pump ~3.58s;
- PumpSwap persistence queue ~22.235s;
- persistence service ~1.67s;
- prepare queue ~5.877s;
- pipeline ~28.75s;
- writer queue ~0.912s; writer service ~81ms.

Conclusão: tirar SQLite síncrono do event loop funcionou, mas commit/result por notification deixou throughput limitado pelo writer.

### v16 — writer microbatch

Com 24 persistence workers:
- PumpSwap received ~6093, Pump ~2571;
- coverage 59.1%;
- PumpSwap persistence queue ~57s;
- prepare queue ~0.875s;
- pipeline ~57.77s;
- avg writer batch 16.57, max 24.

Root cause: cada persistence worker aguardava seu writer result, criando WIP cap de 24 e impedindo batches/throughput suficientes.

Controlled 64-worker run (`v16b`):
- coverage ~87.4%; backlog ~12.6%;
- Pump 2.975s;
- PumpSwap persistence queue 1.891s;
- persistence service 2.613s;
- prepare queue 7.515s;
- pipeline 11.046s;
- diferença writer results vs persistence completed = 64, mostrando resume pressure.

Conclusão: 64 resolveu ingress persistence, mas bottleneck migrou. Não subir para 96/128 cegamente.

### v17 — thread-owned writer loop

- received total 4554;
- coverage 88.4%;
- Pump 2.886s;
- PumpSwap persistence queue 424ms;
- persistence service 1.233s;
- persist->reservation 5.900s;
- prepare queue 38.516s;
- pipeline 40.526s;
- writer queue no deadline 0; writer saudável.

Conclusão: writer deixou de ser gargalo; async prepare submission/resumption passou a dominar.

### v18 — decoupled prepare submitters

Config: 48 async submitters, **12 actual prepare threads**.

Live:
- received 4983;
- coverage 94.5%; true backlog 5.46%;
- Pump p95 3.368s;
- persistence queue 675ms;
- prepare queue **489ms**;
- prepare service ~1.390s;
- persist->reservation ~7.177s;
- prepared->submit ~6.657s;
- causal dependency ~3.356s;
- pipeline **9.957s**;
- writer saudável; DB ~94ms; detector ~0.4ms.

Conclusão: decoupled submitters resolveram prepare queue. Novo HOL = global reservation watermark emitido tarde, depois de persistence completion.

### v19 — early reservation watermark

`src/pumpswap_deferred_persistence_v5.py` permite:
1. causal normalize/pool resolution;
2. conservative reservation asset superset;
3. early hint antes de writer completion;
4. authoritative writer result continua obrigatório para detector prepare;
5. guard final confirma que canonical `affected_tokens` está contido no early superset.

#### v19 inicial

- received 4585;
- processed 4442; true backlog **143/4585 = 3.12% PASS**;
- coverage **96.9% PASS**;
- Pump p95 **3.448s PASS**;
- PumpSwap persistence queue 846ms;
- normalization->reservation 1.885s;
- prepare queue 700ms;
- causal dependency 1.182s;
- pipeline **5.765s FAIL**;
- `reservation_superset_violations=0`;
- no drops/errors/budget skips/reference episodes.

Conclusão: early reservation removeu grande parte do HOL e levou pipeline de ~9.96s para ~5.76s.

#### v19b — immediate-ready scheduler fast path

Mudança: reservation já causalmente pronta entra direto na ready queue, sem criar task só para redescobrir que está pronta.

Live:
- coverage **97.1% PASS**;
- true backlog **129/4503 = 2.86% PASS**;
- Pump p95 **3.691s PASS**;
- pipeline **8.523s FAIL**;
- um hot asset concentrou >50% do causal wait: 178 reservations, 44 outstanding, 39 waiters, hot-asset p95 ~11.55s.

Diagnóstico: `Condition.notify_all()` acordava dezenas de waiters a cada ticket; thundering herd quase O(n²) em burst de mesmo asset.

#### scheduler direct-successor release

`src/pumpswap_ready_scheduler.py` foi alterado para indexar pending work por ticket exato. `complete(N)` considera somente jobs desbloqueáveis pelo ticket concluído, em vez de acordar todos os waiters.

Safety tests incluem:
- FIFO burst de dezenas de tickets do mesmo asset;
- multi-asset predecessor barrier;
- immediate-ready path.

#### v19c — após direct-successor release

- received **4372**;
- processed **4276**;
- true backlog **96/4372 = 2.20% PASS**;
- coverage **97.8% PASS**;
- drops 0; worker errors 0;
- reference assets 0;
- hydration budget skips 0;
- `reservation_superset_violations=0`;
- replay conflicts 0;
- bundles não vazios;
- Pump p95 **2.864s PASS**;
- PumpSwap writer queue p95 **86ms**, result p95 **270ms**;
- prepare queue p95 **715ms**;
- prepare service p95 **1.120s**;
- scheduler dispatch p95 **0.0ms**;
- causal dependency p95 **410ms**;
- hot-asset worst shown p95 ~**1.420s**, contra 11.55s no v19b;
- ready queue p95 **462ms**;
- normalization->reservation p95 **4.671s**;
- ingress->reservation p95 **6.231s**;
- prepared->submit p95 **3.519s**;
- PumpSwap pipeline p95 **6.281s FAIL**.

Conclusão v19c:
- scheduler thundering herd foi resolvido de forma clara;
- writer, prepare queue, detector e finalizer estão saudáveis;
- gate falha somente no PumpSwap pipeline;
- gargalo dominante atual = **global normalization reservation watermark / sequence holes antes da reservation**, amplificado por resolution latency.

### Resolver cache fast path — correção pós-v19c

Inspeção mostrou que `ConcurrentReusablePumpSwapPoolResolver` adquiria per-pool lock + global `Semaphore(max_concurrent_resolutions=18)` antes de chamar o reusable resolver, embora o reusable resolver começasse por cache/store/historical lookup.

No v19c:
- cache hits: **2518**;
- network hydrations: **101**;
- singleflight waits: 83.

Assim, a enorme maioria das resoluções baratas disputava o mesmo semaphore pensado para limitar trabalho caro/rede.

Correção:
- causally valid in-memory cache hit retorna **antes** de per-pool lock e semaphore;
- após esperar single-flight lock, cache é checado novamente antes de gastar slot global;
- misses continuam bounded pelo mesmo semaphore;
- canonical store reload após resolução cara permanece intacto;
- nenhuma mudança em detector/provider/replay/as_of/reservation FIFO.

Validation:
- teste específico esgota o semaphore e confirma que cache hit ainda retorna imediatamente;
- **608 tests / 0 failures**;
- GitHub Actions PASS.

## Gate atual — next v19 live validation

Frozen runnable config:
- duration 120s;
- commitment confirmed;
- Pump batch 32 / 25ms;
- PumpSwap persistence workers 64;
- thread-owned SQLite writer threads 1;
- writer batch 32 / 10ms;
- PumpSwap prepare submitters 48;
- actual prepare executor workers 12;
- finalizer workers 1;
- max concurrent expensive resolutions 18;
- max hydrations 1500;
- queue 5000;
- SQLite WAL;
- synchronous 2.

PASS conditions — todas obrigatórias:
1. no traceback/worker errors;
2. drops 0;
3. `reference_asset_episodes=0`;
4. coverage >=95%;
5. **true total deadline backlog = (total_received - total_radar_processed) / total_received <=5%**; não somar counters de backlog que se sobrepõem;
6. Pump radar p95 <=5s;
7. PumpSwap causal result availability / pipeline p95 <=5s;
8. hydration budget skips 0;
9. bundles não sistematicamente vazios;
10. replay counters auditáveis / sem corruption não explicada;
11. `reservation_superset_violations=0`.

Current hypothesis:
- se cache fast path reduzir normalization sequence holes, `normalization_to_reservation`, `prepared_to_submit` e pipeline devem cair sem alterar workers;
- se normalization->reservation continuar alto apesar do fast path, o próximo problema é o **global normalization watermark em si**, especialmente rare network-resolution outliers; não aumentar workers automaticamente;
- qualquer mudança futura que relaxe per-asset ingress FIFO é semanticamente relevante e exige prova separada, não tuning oportunista.

## Depois do latency PASS

Ordem congelada:
1. Jupiter executable quote somente para novo episode admitido;
2. hazard/risk provider mínimo com explicit missing/failure;
3. historical wallet outcomes resolvidos antes de T0 quando aplicável;
4. freeze final `decision_as_of` após provider attempts obrigatórias;
5. forward executable outcomes +5m/+15m/+60m;
6. short true economic E2E smoke;
7. auditar provider coverage/reconnect/dedup/clocks/cost;
8. definir hydration/rate/backpressure policy;
9. congelar protocolo runnable;
10. somente então primeira coleta de 12h.

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
- Pump latency: PASS;
- PumpSwap latency gate: **ainda não fechado**;
- economic edge: não estabelecido;
- executable fill/landing: não validado;
- shadow/live: **não liberado**.
