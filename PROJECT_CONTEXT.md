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
- End-to-end replay hardening observation -> pool mapping -> trigger/episode: CODE/CI/LIVE PASS; conflitos continuam auditáveis.
- Pump ordered SQLite microbatch: live PASS para Pump latency.
- Unified v7 PumpSwap worker pool: **FAIL — scheduler starvation**.
- v8 nonblocking ready scheduler: **CODE/CI PASS / LIVE FAIL — gross PumpSwap capacity deficit**.
- v9 bounded 8-worker capacity stress: **LIVE FAIL SOMENTE NO PUMPSWAP LATENCY TAIL**; coverage/backlog/Pump passaram.
- Próximo gate: **v10 diagnostic-only latency decomposition**, sem tuning especulativo.
- Jupiter executable quotes, hazard/risk provider, final `decision_as_of`, executable forward outcomes e historical wallet outcomes no unified path ainda não estão ligados.
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

### Pump native
`pump-smoke-20260903-01`: 3,476 notifications; 3,688 decoded trades; 3,600 persisted; 223 tokens; 1,984 wallets. PASS.

### Pump radar
`market-radar-smoke-20260903-03`: 2,037 trades; 738 raw hits; 31 episodes; 29 tokens. 95.8% dos raw hits eram continuation; enrichment caro deve ser episode-scoped. PASS.

### PumpSwap native
`pumpswap-smoke-20260903-01`: 837/837 trades persisted; 150 pools; 737 wallets; 92/92 hydrations; 0 failures/skips. PASS.

### Unified v2-v5
- v2: bundle PASS / throughput FAIL.
- v3: semantics PASS / capacity FAIL.
- v4: coverage/capacity PASS / latency FAIL.
- v5: burst capacity/latency FAIL; PumpSwap global HOL sob carga.
- replay incidents v5b/v5c/v5d levaram ao hardening posterior; conflitos permanecem explícitos.

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
- received 3,530;
- coverage 100%; backlog 1 item;
- Pump persistence p95 1.91s;
- Pump radar p95 **2.80s PASS**;
- PumpSwap persistence p95 0.58s;
- PumpSwap radar p95 **7.95s FAIL**;
- hydration 71/71; RPC failures 0; budget skips 0.

Decision: Pump microbatch resolveu Pump. PumpSwap global radar ordering continuava limitando latency.

### v7
`unified-market-smoke-20260903-07`:
- received 6,039;
- PumpSwap persistence completed 100%;
- radar processed Pump 2,742 / PumpSwap 2,206;
- coverage **81.9% FAIL**;
- PumpSwap deadline backlog **1,091**;
- Pump radar p95 **2.42s PASS**;
- PumpSwap radar p95 **65.05s FAIL**;
- 4 radar workers.

Classification: **FAIL — PUMPSWAP RADAR SCHEDULER STARVATION / CAPACITY FAIL**.

Root cause: worker consumia execution slot antes de o ticket causal do asset estar pronto. Tickets futuros bloqueados podiam ocupar todos os workers enquanto assets independentes aguardavam.

### v8 — nonblocking per-asset ready scheduler

Architecture:
1. dispatcher em websocket ingress order;
2. reservation recebe ticket FIFO por opportunity asset;
3. espera causal não consome radar worker;
4. somente work causalmente pronto entra na ready queue;
5. multi-asset espera todos os predecessors;
6. replay sem nova evidência causal é reconhecido sem recomputar radar;
7. thresholds/clocks/replay/episode/provider semantics não mudam.

Validation pre-live: compileall PASS; **581 tests / 0 failures**; CI PASS.

Live `unified-market-smoke-20260903-08`:
- PumpSwap received 3,553;
- persistence completed 3,531 (~29.4/s);
- radar processed 2,157 (~18.0/s);
- coverage **75.6% FAIL**;
- PumpSwap reorder backlog **1,374**;
- Pump radar p95 **2.319s PASS**;
- PumpSwap persistence p95 **0.498s**;
- PumpSwap radar service p95 **0.790s**;
- PumpSwap radar end-to-end p95 **54.973s FAIL**;
- drops 0; worker errors 0; RPC failures 0; budget skips 0;
- replay conflicts 0.

Classification: **PUMP PASS / PUMPSWAP RADAR CAPACITY FAIL**.

The v8 summary's `waiting_backlog=0` was not trustworthy because waiters had already been cancelled before the snapshot. This telemetry defect was fixed for v9.

### v9 — measured 8-worker capacity stress

v9 deliberately changed only PumpSwap radar execution capacity from 4 -> 8 workers and preserved a pre-cancellation scheduler snapshot.

Live `unified-market-smoke-20260903-09`:
- received Pump 1,525 + PumpSwap 1,979 = 3,504;
- persistence completed Pump 1,502 / PumpSwap 1,978;
- radar processed Pump 1,481 / PumpSwap 1,927;
- coverage **97.3% PASS**;
- deadline backlog 96 / 3,504 = **~2.74% PASS**;
- Pump radar p95 **1.798s PASS**;
- PumpSwap persistence p95 **0.390s**;
- PumpSwap radar service p95 **0.676s**;
- PumpSwap radar end-to-end p50/p95/max **2.271s / 18.311s / 27.176s**;
- scheduler snapshot: ready backlog 22 / waiting backlog 17;
- hydration 99/99; RPC failures 0; budget skips 0;
- drops 0; worker errors 0; reference asset episodes 0;
- replay: Pump 1 retain-earlier; market 2 retain-earlier; trigger 0; pool mapping 0.

Classification: **PUMP PASS / PUMPSWAP LATENCY TAIL FAIL**.

Important inference:
- v9 removed the gross capacity deficit enough to pass coverage/backlog;
- radar service itself is not the 18s tail;
- most latency occurs before radar execution starts;
- do **not** raise worker count again automatically.

Canonical report: `docs/unified-market-latency-v9-live-and-v10-diagnostic-2026-09-03.md`.

## Gate atual — v10 diagnostic-only

v10 must keep:
- duration 120s;
- commitment confirmed;
- Pump batch 32 / 25ms;
- PumpSwap persistence workers 24;
- PumpSwap radar workers **8**;
- max concurrent resolutions 18;
- max hydrations 1500;
- queue 5000;
- all detector/causal/replay/persistence/provider semantics frozen.

v10 instruments:
- persistence queue wait;
- persistence service;
- persistence-complete -> reservation/reorder wait;
- reservation -> scheduler waiter task dispatch;
- causal dependency wait;
- ready queue wait;
- radar service (same boundary as v8/v9: evaluation + result handling/enrichment);
- full pipeline E2E;
- transaction-view DB read;
- token-history DB read;
- detector compute;
- episode assignment/write;
- radar evaluation vs post-evaluation handling/enrichment;
- per-asset reservations, outstanding depth, waiting depth and causal-wait concentration.

v10 is **measurement only**, not an optimization.

Interpretation:
- scheduler task dispatch dominates -> event-loop/scheduler dispatch overhead;
- causal wait dominates + concentrated in few assets -> hot-asset serialization;
- ready queue dominates -> execution scheduling/capacity;
- persist-to-reservation dominates -> ingress reorder/dispatcher HOL;
- DB reads inflate under load -> shared SQLite/read contention;
- post-evaluation handling dominates -> episode admission/enrichment bottleneck;
- none explains E2E -> reconcile phase clocks before changing architecture.

## Frozen latency PASS gate

PASS somente se:
1. no traceback/worker errors;
2. drops 0;
3. reference_asset_episodes 0;
4. coverage >=95%;
5. total deadline backlog <=5% do received;
6. Pump radar p95 <=5s;
7. PumpSwap radar p95 <=5s;
8. hydration budget skips 0;
9. bundles não sistematicamente vazios;
10. replay counters inspecionáveis e sem corrupção não explicada.

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
- PumpSwap v8: gross capacity FAIL;
- PumpSwap v9: coverage/backlog PASS, p95 latency FAIL;
- v10: diagnostic gate atual;
- economic edge: não estabelecido;
- executable fill/landing: não validado;
- shadow/live: **não liberado**.
