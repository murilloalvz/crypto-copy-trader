# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado fica em `docs/`; aqui permanecem decisões, evidências canônicas e gates necessários para continuar sem reabrir trabalho encerrado.

## Estado atual

- Repositório: `murilloalvz/crypto-copy-trader`.
- Branch principal de pesquisa: `feat/exit-engine-v1`.
- Modo: **PAPER / RESEARCH / READ ONLY**.
- Tese ativa: **market-first Solana Opportunity Intelligence / Opportunity Engine**.
- Wallet Forward v2: encerrado como **OUTCOME D — TOO LITTLE ECONOMIC SAMPLE**; não iniciar Run 3.
- Pump native acquisition: PASS.
- Pump -> radar -> opportunity episode: PASS.
- PumpSwap native acquisition + causal pool resolution: PASS.
- Unified local causal bundle flow/wallet semantics: PASS.
- End-to-end replay hardening observation → pool mapping → trigger/episode: CODE/CI/LIVE PASS; conflitos continuam auditáveis.
- Pump ordered SQLite microbatch (v6): live PASS para Pump latency.
- Unified v7 per-asset PumpSwap worker pool: **FAIL — scheduler starvation / capacity fail**.
- v8 nonblocking ready scheduler: **CODE/CI PASS / LIVE REVALIDATION PENDING**.
- Jupiter, hazard/risk provider, final decision_as_of, executable forward outcomes e historical wallet outcomes no unified path ainda não estão ligados.
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

- exatamente um lado reference → outro é opportunity token;
- opportunity token base → side preservado;
- opportunity token quote → side invertido;
- two-reference/two-unknown → role_filtered;
- WSOL/USDC não podem virar opportunity episodes.

Pool identity:
- schema cacheado por DB path;
- earliest observed mapping vence;
- conflitos auditados;
- histórico ambíguo não é reutilizado;
- concurrent resolver recarrega mapping canônico persistido antes de normalizar.

## Evidência live canônica

### Pump native
`pump-smoke-20260903-01`: 3,476 notifications; 3,688 decoded trades; 3,600 persisted; 223 tokens; 1,984 wallets. PASS.

### Pump radar
`market-radar-smoke-20260903-03`: 2,037 trades; 738 raw hits; 31 episodes; 29 tokens. 95.8% dos raw hits eram continuation → enrichment caro deve ser episode-scoped. PASS.

### PumpSwap native
`pumpswap-smoke-20260903-01`: 837/837 trades persisted; 150 pools; 737 wallets; 92/92 hydrations; 0 failures/skips. PASS.

### Unified v2/v3/v4/v5
- v2: bundle PASS / throughput FAIL.
- v3: semantics PASS / capacity FAIL.
- v4: coverage/capacity PASS / latency FAIL.
- v5: burst capacity/latency FAIL; PumpSwap global HOL sob carga.

### Replay incidents v5b/v5c/v5d
- v5b: Pump replay integrity abort.
- reused 05b namespace: invalid/contaminated.
- v5c: shared market replay integrity abort.
- v5d: trigger replay integrity abort.
- hardening posterior: 571+ tests, CI PASS e live revalidation posterior sem crash.

### v5e
`unified-market-smoke-20260903-05e`:
- received 4,256;
- coverage 97.0%;
- deadline backlog ~2.98%;
- Pump radar p95 24.50s FAIL;
- PumpSwap radar p95 4.85s PASS;
- replay counters all zero.

Decision: Pump persistence era gargalo; implementar writer ordenado microbatch.

### v6
`unified-market-smoke-20260903-06`:
- received PumpSwap 2,181 + Pump 1,349 = 3,530;
- coverage 100%; backlog 1 item;
- Pump persistence p95 1.91s;
- Pump radar p95 **2.80s PASS**;
- Pump microbatch 163 batches, avg 8.28, max 32;
- PumpSwap persistence p95 0.58s;
- PumpSwap radar p95 **7.95s FAIL**;
- hydrations 71/71, RPC failures 0, budget skips 0;
- one `market_replay_conflicts` retain-earlier observation; deve ser auditado, não é edge evidence.

Decision: Pump microbatch resolveu Pump. PumpSwap persistence não era gargalo; global radar ordering ainda causava latency.

### v7
`unified-market-smoke-20260903-07`:
- received PumpSwap 3,297 + Pump 2,742 = 6,039;
- persistence completed 100% em ambos;
- radar processed Pump 2,742 / PumpSwap 2,206;
- coverage **81.9% FAIL**;
- deadline backlog PumpSwap **1,091**;
- Pump radar p95 **2.42s PASS**;
- PumpSwap persistence p95 2.26s;
- PumpSwap radar p95 **65.05s FAIL**;
- 4 radar workers, 3,297 reservations, work backlog 1,091;
- 93/93 hydrations, RPC failures 0, budget skips 0;
- replay telemetry: Pump 17 retain-earlier; market 4 retain-earlier; trigger 4 retain-first; pool 0.

Classification: **FAIL — PUMPSWAP RADAR SCHEDULER STARVATION / CAPACITY FAIL**.

Root cause: v7 workers retiravam work item da fila e só depois esperavam o ticket causal do asset. Um ticket futuro bloqueado consumia um dos quatro worker slots, permitindo que todos os slots ficassem presos enquanto trabalho de assets independentes e já executável permanecia na fila. A vazão ficou ~18.4 notifications/s, praticamente sem ganho sobre o caminho sequencial anterior, enquanto o ingress foi ~27.5/s.

Canonical report: `docs/unified-market-latency-v7-live-result-2026-09-03.md`.

## v8 — nonblocking per-asset ready scheduler

Files:
- `src/pumpswap_ready_scheduler.py`;
- `unified_market_latency_smoke_v8.py`;
- `tests/test_pumpswap_ready_scheduler.py`.

Semantics:
1. dispatcher continua emitindo reservations em websocket ingress order;
2. cada reservation recebe tickets FIFO por opportunity asset;
3. waiter de dependência **não consome radar execution slot**;
4. somente reservation cujos predecessors terminaram entra na ready queue;
5. quatro workers executam somente trabalho causalmente pronto;
6. multi-asset notification espera todos os predecessors; relações continuam acíclicas por derivarem de uma ordem global de ingress;
7. replay sem nenhuma nova observação/lifecycle é reconhecido como no-op e não recomputa radar; conta como processado, pois nenhuma nova evidência causal foi perdida;
8. detector, clocks, thresholds, episode semantics e provider policy não mudam.

Nova telemetria:
- `pumpswap_radar_service_time_ms` separa custo real de avaliação de queue/end-to-end latency;
- `ready_backlog` = trabalho causalmente pronto esperando execução;
- `waiting_backlog` = trabalho esperando predecessor do mesmo asset;
- `no_new_evidence_skips` e `duplicate_or_replayed_trades` tornam replay load explícito.

Validation v8: `compileall` PASS; **581 tests / 0 failures**; CI PASS. Live pending.

## Gate atual — v8 live

Config congelada:
- duration 120s;
- commitment confirmed;
- Pump batch size 32;
- Pump batch max dwell 25ms;
- PumpSwap persistence workers 24;
- PumpSwap radar workers 4;
- max concurrent resolutions 18;
- max hydrations 1500;
- queue 5000.

PASS somente se:
1. no traceback/worker errors;
2. drops 0;
3. reference_asset_episodes 0;
4. coverage >=95%;
5. total deadline backlog <=5% do received;
6. Pump radar p95 <=5s;
7. PumpSwap radar p95 <=5s;
8. budget skips 0;
9. bundles não sistematicamente vazios;
10. replay counters inspecionáveis e sem corrupção não explicada.

Se v8 ainda falhar, **não aumentar radar workers automaticamente**. Usar `pumpswap_radar_service_time_ms`, `ready_backlog` e `waiting_backlog` para decidir:
- service time alto + ready backlog alto → otimizar custo do radar/DB;
- waiting backlog alto + service time baixo → hot-asset serialization é limite causal real;
- ambos baixos mas E2E alto → revisar dispatcher/persistence clocks.

## Depois do latency PASS

1. Jupiter executable quote somente para novo episode admitido;
2. hazard/risk provider mínimo com explicit missing/failure;
3. historical wallet outcomes resolvidos antes de T0;
4. freeze final `decision_as_of` após provider attempts obrigatórias;
5. short true economic E2E smoke;
6. auditar provider coverage/reconnect/dedup/clocks/cost;
7. definir hydration/rate/backpressure policy para long run;
8. congelar protocolo runnable;
9. somente então primeira coleta de 12h.

## Avaliação econômica futura

Outcomes +5m/+15m/+60m com semântica executável/route-aware quando possível. Nunca substituir silenciosamente quote/fill ausente por candle posterior.

Ablations: movement, flow, execution, wallet e risk. Métricas mínimas: mean/median, win rate, profit factor, drawdown, coverage, token/cluster concentration, top-winner contribution e robustez removendo top1/top3 winners.

## Shadow / live

- native acquisition: Pump PASS / PumpSwap PASS;
- causal unified local bundle: PASS;
- replay integrity: hardened + live validated;
- Pump latency: PASS via v6 microbatch;
- PumpSwap v7: scheduler starvation FAIL;
- PumpSwap v8: code/CI PASS, live pending;
- economic edge: não estabelecido;
- executable fill/landing: não validado;
- shadow/live: não liberado.
