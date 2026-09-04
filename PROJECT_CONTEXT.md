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
- Replay hardening observation -> pool mapping -> trigger/episode: CODE/CI/LIVE PASS; conflitos continuam auditáveis.
- Pump ordered SQLite microbatch: live PASS para Pump latency.
- Unified v7 PumpSwap worker pool: **FAIL — scheduler starvation**.
- v8 nonblocking ready scheduler: **LIVE FAIL — gross PumpSwap capacity deficit**.
- v9 8-worker stress: **coverage/backlog PASS; PumpSwap latency tail FAIL**.
- v10 diagnostic: **FAIL — hot-asset causal serialization + secondary PumpSwap persistence/reorder pressure**.
- v11 prepared-radar split: **CODE/CI PASS; live validation is the current gate**.
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

### Unified v2-v6

- v2: bundle PASS / throughput FAIL.
- v3: semantics PASS / capacity FAIL.
- v4: coverage/capacity PASS / latency FAIL.
- v5: burst capacity/latency FAIL; PumpSwap global HOL sob carga.
- replay incidents v5b/v5c/v5d levaram ao hardening posterior.
- v5e: coverage 97.0%; Pump radar p95 24.50s FAIL; PumpSwap radar p95 4.85s PASS.
- v6: coverage 100%; Pump radar p95 2.80s PASS; PumpSwap radar p95 7.95s FAIL.

Decision after v6: Pump writer was solved; PumpSwap radar path became the active latency problem.

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

Root cause: workers consumiam execution slots antes de tickets causais estarem prontos.

### v8 — nonblocking per-asset ready scheduler

Architecture:
1. dispatcher em websocket ingress order;
2. reservation recebe ticket FIFO por opportunity asset;
3. espera causal não consome radar worker;
4. somente work causalmente pronto entra na ready queue;
5. multi-asset espera todos os predecessors;
6. replay sem nova evidência causal não recomputa radar;
7. thresholds/clocks/replay/episode/provider semantics não mudam.

Live `unified-market-smoke-20260903-08`:

- PumpSwap received 3,553;
- persistence completed 3,531;
- radar processed 2,157;
- coverage **75.6% FAIL**;
- Pump radar p95 **2.319s PASS**;
- PumpSwap persistence p95 **0.498s**;
- PumpSwap radar service p95 **0.790s**;
- PumpSwap radar end-to-end p95 **54.973s FAIL**;
- drops/worker errors/RPC failures/budget skips/replay conflicts: 0.

Classification: **PUMP PASS / PUMPSWAP RADAR CAPACITY FAIL**.

### v9 — 8-worker measured capacity stress

Live `unified-market-smoke-20260903-09`:

- received Pump 1,525 + PumpSwap 1,979 = 3,504;
- coverage **97.3% PASS**;
- deadline backlog ~2.74% PASS;
- Pump radar p95 **1.798s PASS**;
- PumpSwap persistence p95 **0.390s**;
- PumpSwap radar service p95 **0.676s**;
- PumpSwap radar end-to-end p50/p95/max **2.271s / 18.311s / 27.176s**;
- scheduler snapshot: ready 22 / waiting 17;
- hydration 99/99; budget skips 0;
- drops 0; worker errors 0; reference asset episodes 0.

Classification: **PUMP PASS / PUMPSWAP LATENCY TAIL FAIL**.

Inference: service time did not explain the 18s tail. Do not raise worker count again automatically.

### v10 — diagnostic decomposition

Live `unified-market-smoke-20260903-10`:

- received Pump 1,743 + PumpSwap 3,789 = 5,532;
- persistence completed Pump 1,743 / PumpSwap 3,787;
- radar processed Pump 1,743 / PumpSwap 2,460;
- coverage **76.0% FAIL**;
- drops 0; worker errors 0;
- reference asset episodes 0;
- RPC failures 0; budget skips 0;
- replay conflicts 0.

Pump:
- persistence queue p95 **2.242s**;
- radar end-to-end p95 **3.864s PASS**.

PumpSwap:
- persistence queue p50/p95/max **10.807s / 29.094s / 33.188s**;
- persistence service p50/p95/max **0.016s / 2.754s / 13.985s**;
- persist-complete -> reservation p95 **11.112s**;
- scheduler dispatch p95 **0.999s**;
- causal dependency wait p50/p95/max **11.894s / 54.449s / 68.103s**;
- ready queue wait p95 **10.644s**;
- radar evaluation p95 **1.138s**;
- full pipeline p50/p95/max **39.279s / 90.996s / 101.449s**;
- radar DB read p95 **106.9ms**;
- detector compute p95 **0.3ms**;
- episode assignment p95 **16.6ms**;
- post-evaluation handling p95 **0ms**.

Hot-asset evidence:
- 3,733 reservations;
- 222 assets with reservations;
- 1,198 waiting on causal predecessors at deadline;
- 75 ready;
- max waiting jobs on one asset **108**;
- 11 assets generated 50% of causal wait;
- 32 assets generated 90% of causal wait;
- hottest assets carried roughly 137-159 reservations each.

Classification:

**FAIL — PUMPSWAP HOT-ASSET SERIALIZATION, WITH SECONDARY PERSISTENCE/REORDER PRESSURE.**

Primary inference: v8-v10 serialize the entire same-asset radar evaluation even though transaction/history reads and the frozen detector are read-only under the causal `as_of` boundary. The stateful operation that truly requires per-asset FIFO is trigger/episode assignment.

Secondary inference: the 29.1s persistence queue p95 is independently large enough to remain a future gate blocker under a similar burst. Do not ignore it after the radar split is measured.

Canonical report:
`docs/unified-market-latency-v10-live-and-v11-prepared-radar-2026-09-03.md`.

## v11 — parallel prepare, FIFO finalize

Files:
- `src/pumpswap_radar_bridge_v5.py`;
- `unified_market_latency_smoke_v11.py`;
- `tests/test_pumpswap_radar_bridge_v5.py`;
- `tests/test_pumpswap_ready_scheduler_diagnostics.py`.

Architecture:

```text
PumpSwap persistence
      |
      +--> parallel prepare (8 workers)
      |    - canonical transaction view
      |    - causal history read (`observed_at <= token_as_of`)
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

Semantics:
1. preparation creates no trigger/episode side effects;
2. later notifications may prepare before earlier notifications;
3. asset tickets are still issued from canonical ingress order;
4. a later prepared result cannot finalize before its predecessor on the same asset;
5. trigger key remains `market-radar:pumpswap-v3:<signature>:<mint>`;
6. detector config, `token_as_of`, episode window, replay semantics and provider policy are unchanged;
7. PumpSwap preparation workers remain **8** in the frozen live smoke;
8. finalization starts with one worker because v10 measured the stateful commit as cheap; do not increase it unless the v11 ready queue proves it necessary.

Validation:
- compileall PASS;
- **590 tests / 0 failures**;
- GitHub Actions CI PASS.

v11 also fixes telemetry naming by separating:
- total PumpSwap radar backlog;
- actual order/reorder backlog;
- prepare queue;
- prepared waiting for reservation;
- reservation waiting for prepare;
- ready finalization queue;
- causal finalization waiters.

## Gate atual — v11 live

Frozen config:
- duration 120s;
- commitment confirmed;
- Pump batch 32 / 25ms;
- PumpSwap persistence workers 24;
- PumpSwap prepare workers 8;
- PumpSwap finalizer workers 1;
- max concurrent resolutions 18;
- max hydrations 1500;
- queue 5000.

PASS conditions remain:
1. no traceback/worker errors;
2. drops 0;
3. reference_asset_episodes 0;
4. coverage >=95%;
5. total deadline backlog <=5% of received;
6. Pump radar p95 <=5s;
7. PumpSwap causal result availability p95 <=5s;
8. hydration budget skips 0;
9. bundles not systematically empty;
10. replay counters inspectable and no unexplained integrity corruption.

Interpretation after v11:
- causal wait collapses but persistence queue remains high -> target PumpSwap persistence architecture next;
- actual order/reorder dominates -> remove global HOL without weakening canonical identity;
- prepare queue dominates -> optimize preparation/thread-pool behavior;
- finalizer ready queue dominates -> measured finalizer capacity issue;
- finalizer causal wait remains concentrated -> inspect stateful commit/ticket release;
- all phase clocks low but E2E high -> reconcile clocks before changing architecture.

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
- PumpSwap v10: diagnostic FAIL, root cause measured;
- PumpSwap v11: code/CI PASS / live pending;
- economic edge: não estabelecido;
- executable fill/landing: não validado;
- shadow/live: **não liberado**.
