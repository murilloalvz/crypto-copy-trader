# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado fica em `docs/`; aqui permanecem decisões, evidências canônicas e gates necessários para continuar sem reabrir trabalho encerrado.

## Estado atual

- Repositório: `murilloalvz/crypto-copy-trader`.
- Branch principal de pesquisa: `feat/exit-engine-v1`.
- Modo: **PAPER / RESEARCH / READ ONLY**.
- Tese ativa: **market-first Solana Opportunity Intelligence / Opportunity Engine**.
- Fluxo conceitual: `market data -> unified radar -> detector -> opportunity episode -> wallets/flow/context -> execution/risk -> decision_as_of -> forward executable outcomes`.
- Wallet Forward v2: encerrado como **OUTCOME D — TOO LITTLE ECONOMIC SAMPLE**; não iniciar Run 3.
- Pump native acquisition: PASS.
- Pump -> radar -> opportunity episode: PASS.
- PumpSwap native acquisition + causal pool resolution: PASS.
- Unified local causal bundle flow/wallet semantics: PASS.
- Replay hardening observation -> pool mapping -> trigger/episode: CODE/CI/LIVE PASS; conflitos continuam auditáveis.
- Pump ordered SQLite microbatch: live PASS para Pump latency.
- PumpSwap v7-v10 localizaram scheduler starvation, gross capacity deficit e hot-asset causal serialization.
- v11 split prepare/finalize: **arquitetura validada; causal wait colapsou**.
- v12 dedicated prepare executor: **melhorou prepare queue, expôs reader/writer interference**.
- v13 SQLite WAL: **persistence reader/writer contention resolvida; prepare queue permaneceu dominante**.
- v14 hidden-time diagnostic: **prepare interno é barato (~86ms p95); atraso dominante ocorre fora da thread, na retomada do event loop/executor**.
- v15 dedicated SQLite writer: **CODE/CI PASS; live validation é o gate atual**.
- Jupiter executable quotes, hazard/risk provider, final `decision_as_of`, executable forward outcomes e historical wallet outcomes ainda não estão ligados no unified path.
- **Não iniciar 12h ainda.**

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

## Detector congelado

`src/market_opportunity_radar.py` — `market_opportunity_radar_v1_1_tx_aware`.

Acquisition mechanics, não regras de trading:
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

Shared market observation semantics:
- exact replay idempotente;
- SQLite completion order não define causalidade;
- earliest collector `observed_at` vence;
- identidade conflitante é auditada em `market_replay_conflicts`;
- conflito não vira flow novo nem derruba a aquisição.

Trigger/episode semantics:
- replay do mesmo trigger não cria novo episode/enrichment;
- recomputação divergente fica em `market_trigger_replay_conflicts`;
- primeiro trigger-to-episode persistido permanece canônico;
- corrupção referencial real continua fatal.

Pump-specific replay telemetry permanece em `pump_replay_conflicts`.
PumpSwap pool conflicts permanecem em `pumpswap_pool_mapping_conflicts`.

Lifecycle:
- Pump `CreateEvent` = token birth;
- PumpSwap `CreatePoolEvent` = venue/pool lifecycle, não token birth.

Wallet é evidência pós-episódio, nunca whitelist de aquisição.

## PumpSwap identity / asset role

Reference assets v1: WSOL e USDC.

- exatamente um lado reference -> outro é opportunity token;
- opportunity token base -> side preservado;
- opportunity token quote -> side invertido;
- two-reference/two-unknown -> role_filtered;
- WSOL/USDC não podem virar opportunity episodes.

Pool identity:
- schema cacheado por DB path;
- earliest observed mapping vence;
- conflitos auditados;
- histórico ambíguo não é reutilizado;
- concurrent resolver recarrega mapping canônico persistido antes de normalizar.

## Evidência live canônica

### Native / early unified

- Pump native `pump-smoke-20260903-01`: 3,476 notifications; 3,688 decoded trades; 3,600 persisted; 223 tokens; 1,984 wallets. PASS.
- Pump radar `market-radar-smoke-20260903-03`: 2,037 trades; 738 raw hits; 31 episodes; 29 tokens. 95.8% raw hits eram continuation; enrichment caro deve ser episode-scoped. PASS.
- PumpSwap native `pumpswap-smoke-20260903-01`: 837/837 trades persisted; 150 pools; 737 wallets; 92/92 hydrations; 0 failures/skips. PASS.
- unified v2-v6: semantics/capacity progressivos; v6 coverage 100%, Pump p95 2.80s PASS, PumpSwap p95 7.95s FAIL.

### v7-v10 — root-cause discovery

- v7: coverage 81.9%, PumpSwap backlog 1,091, PumpSwap p95 65.05s. **Scheduler starvation**.
- v8: nonblocking per-asset ready scheduler removeu worker starvation, mas coverage 75.6% e PumpSwap p95 54.973s. **Gross capacity deficit**.
- v9: 8 workers, coverage 97.3% PASS, backlog ~2.74% PASS, Pump p95 1.798s PASS, PumpSwap p95 18.311s FAIL. Service p95 só 0.676s.
- v10 diagnostic: coverage 76.0%; PumpSwap pipeline p95 90.996s; causal dependency p95 54.449s; ready queue p95 10.644s; DB read p95 106.9ms; detector p95 0.3ms. 11 assets concentraram 50% do causal wait, max 108 waiting em um asset.

Conclusão v10: **serializar a avaliação inteira por asset era o erro arquitetural**. Apenas trigger/episode finalization exige FIFO estrito.

## v11 — parallel prepare, FIFO finalize

Architecture:

```text
PumpSwap persistence
      |
      +--> parallel prepare
      |    - canonical transaction view
      |    - causal history read (observed_at <= token_as_of)
      |    - frozen detector
      |
      +--> ingress-ordered asset reservation
                    |
                    v
             per-asset FIFO barrier
                    |
                    v
             finalize trigger/episode
                    |
                    v
             episode-scoped enrichment
```

Semantics preservadas:
1. preparation cria zero side effects de trigger/episode;
2. later notifications podem preparar antes das anteriores;
3. asset tickets continuam emitidos em canonical ingress order;
4. later prepared result não finaliza antes do predecessor do mesmo asset;
5. trigger key permanece `market-radar:pumpswap-v3:<signature>:<mint>`;
6. detector config, `token_as_of`, episode window, replay e provider policy não mudam.

### v11 live, 8 prepare workers

- coverage 83.7%;
- causal dependency p95 **346ms** versus 54.449s no v10;
- max waiting single asset **11** versus 108;
- prepare queue p95 **50.387s**;
- prepare service p95 **875ms**;
- DB read p95 **83.9ms**;
- detector p95 **0.3ms**.

Conclusão: split arquitetural funcionou; novo gargalo = **prepare capacity**.

### v11b, 12 prepare workers

- coverage 84.9%;
- Pump p95 4.279s PASS;
- PumpSwap persistence p95 0.629s;
- prepare queue p95 30.187s;
- prepare service p95 1.127s;
- DB read p95 100.1ms;
- detector p95 0.6ms.

Conclusão: subir coroutines 8 -> 12 não escalou linearmente; não aumentar workers cegamente.

## v12 — dedicated prepare executor

Mudança: 12 prepare coroutines passam a usar `ThreadPoolExecutor` dedicado de 12 threads; demais semânticas intactas.

Live `unified-market-smoke-20260903-12`:
- coverage **94.0%**;
- Pump p95 **2.320s PASS**;
- prepare queue p95 **10.683s**, melhora forte versus 30.187s;
- porém PumpSwap persistence queue p95 explodiu para **20.108s**;
- pipeline p95 **36.416s**.

Conclusão: executor isolation ajudou prepare, mas criou/expôs **SQLite reader-writer interference** sob muitas leituras concorrentes.

## v13 — SQLite WAL

Mudança única adicional: `PRAGMA journal_mode=WAL`; `PRAGMA synchronous` preservado (`2`).

Live `unified-market-smoke-20260903-13`:
- coverage **91.4%**;
- Pump p95 **3.645s PASS**;
- PumpSwap persistence queue p95 **0.721s** versus 20.108s no v12;
- persistence service p95 **68.2ms**;
- prepare queue p95 **21.119s**;
- prepare service p95 **1.258s**;
- DB read p95 **104.1ms**;
- detector p95 **0.3ms**;
- pipeline p95 **23.039s**.

Conclusão: **WAL resolveu reader/writer contention**. Persistence voltou saudável. Prepare continua dominante.

## v14 — prepare hidden-time diagnostic

Live `unified-market-smoke-20260903-14`:
- received PumpSwap 1,961 + Pump 1,632;
- coverage **95.2% PASS**;
- backlog total PumpSwap 170 + ingress 1 = ~4.8% do total recebido, aproximadamente no limite PASS;
- Pump p95 **3.965s PASS**;
- PumpSwap persistence queue p95 **0.671s PASS**;
- persistence service p95 **65.5ms**;
- prepare queue p95 **20.557s FAIL**;
- outer prepare service p95 **1.367s**;
- pipeline p95 **21.825s FAIL**;
- finalize causal p95 **596ms**;
- finalize service p95 **15.8ms**;
- DB read p95 **86.2ms**;
- detector p95 **0.2ms**;
- drops 0; worker errors 0; RPC failures 0; budget skips 0; reference assets 0.

V14 inner-thread diagnostic:
- prepare calls 1,811;
- inner total p50/p95/max **49.2ms / 86.3ms / 173.6ms**;
- accounted DB+detector p50/p95/max **49.2ms / 86.3ms / 173.5ms**;
- unaccounted p95 **0.1ms**.

Conclusão definitiva:

**O prepare não é computacionalmente pesado. O ~1.3s outer service não acontece dentro da thread.** A thread termina em ~50-86ms e a coroutine demora para retomar. A principal fonte restante é event-loop starvation/dispatch delay. O caminho PumpSwap persistence ainda executa `record_market_trade`, `record_market_lifecycle` e canonical readback síncronos diretamente em 24 asyncio workers; bursts de pequenas operações SQLite bloqueiam o event loop em sequência.

## v15 — dedicated SQLite writer (gate atual)

Novos arquivos:
- `src/pumpswap_normalized_persistence_v2.py`;
- `unified_market_latency_smoke_v15.py`;
- `tests/test_pumpswap_normalized_persistence_v2.py`.

Architecture:

```text
24 async PumpSwap persistence workers
        |
        +--> pool resolution / normalization stays async
        |
        +--> canonical market observation write request
                         |
                         v
            single dedicated SQLite writer thread
                         |
                         +--> record trade/lifecycle
                         +--> canonical transaction readback

12 dedicated prepare reader threads (WAL)
                         |
                         v
                   FIFO finalize
```

Rationale:
- SQLite possui um writer efetivo por vez; múltiplas writer threads não trazem benefício estrutural;
- WAL permite este writer coexistir com prepare readers;
- mover canonical writes para fora do asyncio loop evita que bursts de commits bloqueiem a retomada de futures já concluídos;
- pool resolver cache/network state continua no event loop, evitando thread-safety drift;
- event identity, replay, `observed_at`, trigger keys, detector, `as_of`, reservation FIFO e provider policy permanecem intactos.

V15 diagnostic adicional mede:
- resolver/normalize time;
- SQLite writer queue wait;
- SQLite writer service time.

Validation:
- compileall PASS;
- **595 tests / 0 failures**;
- teste confirma semântica v2 equivalente ao caminho legado;
- teste confirma DB stage executando no executor fornecido;
- GitHub Actions CI PASS.

## Gate atual — v15 live

Frozen smoke config:
- duration 120s;
- commitment confirmed;
- Pump batch 32 / 25ms;
- PumpSwap persistence workers 24;
- SQLite writer workers 1;
- PumpSwap prepare workers 12;
- PumpSwap prepare executor workers 12;
- PumpSwap finalizer workers 1;
- max concurrent resolutions 18;
- max hydrations 1500;
- queue 5000;
- SQLite WAL;
- synchronous unchanged.

PASS conditions:
1. no traceback/worker errors;
2. drops 0;
3. reference_asset_episodes 0;
4. coverage >=95%;
5. total deadline backlog <=5% of received;
6. Pump radar p95 <=5s;
7. PumpSwap causal result availability / pipeline p95 <=5s;
8. hydration budget skips 0;
9. bundles not systematically empty;
10. replay counters inspectable and no unexplained integrity corruption.

Interpretation after v15:
- prepare queue + outer prepare service collapse -> event-loop starvation diagnosis confirmed; evaluate full gate;
- writer queue dominates -> add measured writer batching, not extra writer threads;
- prepare queue remains high while writer/event-loop clocks stay low -> build causal per-asset read batching/cache;
- all phase clocks low but E2E high -> instrument explicit event-loop lag before any architecture change.

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
- Pump latency: PASS via ordered microbatch;
- PumpSwap latency gate: **ainda não fechado**;
- economic edge: não estabelecido;
- executable fill/landing: não validado;
- shadow/live: **não liberado**.
