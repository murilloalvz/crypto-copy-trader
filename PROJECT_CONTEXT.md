# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado fica em `docs/`; aqui permanecem decisões, evidências canônicas e gates necessários para continuar sem reabrir trabalho encerrado.

## Estado atual

- Repositório: `murilloalvz/crypto-copy-trader`.
- Branch de pesquisa principal: `feat/exit-engine-v1`.
- Modo: **PAPER / RESEARCH / READ ONLY**.
- Persistência: SQLite via `DATABASE_PATH`.
- Tese ativa: **market-first Solana Opportunity Intelligence / Opportunity Engine**.
- Wallet Forward v2: encerrado como **OUTCOME D — TOO LITTLE ECONOMIC SAMPLE**; não iniciar Run 3.
- Pump bonding acquisition: live PASS.
- Pump -> Radar -> Opportunity Episode: live PASS.
- PumpSwap acquisition + causal pool resolution: live PASS.
- Unified local causal bundle: live PASS para flow/wallet semantics.
- Unified throughput v2: FAIL.
- Unified throughput v3: semantics PASS / capacity FAIL.
- Unified throughput v4: coverage/capacity PASS / latency FAIL.
- Unified latency v5 inicial: FAIL sob burst.
- v5b/v5c/v5d: replay-integrity incidents sucessivos; preservados como evidência, não como throughput results.
- End-to-end replay hardening observation → pool mapping → trigger/episode: **CODE/CI PASS + LIVE PASS**.
- v5e: integrity/coverage/PumpSwap latency PASS; Pump latency FAIL.
- v6: **INTEGRITY PASS / COVERAGE PASS / PUMP LATENCY PASS / PUMPSWAP LATENCY FAIL**.
- Gate atual: **Unified latency v7 — PumpSwap per-asset radar ordering/concurrency**.
- Jupiter, hazard provider, historical wallet outcomes no unified path, final `decision_as_of` e forward outcomes ainda não estão ligados.
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

Objetivo: detectar cedo movimentos anormais, rejeitar oportunidades tóxicas/não executáveis e medir retorno forward capturável líquido de custos. Wallet é evidência contextual do episódio atual, nunca trigger obrigatório nem whitelist fixa.

## Detector ativo

`src/market_opportunity_radar.py` — `market_opportunity_radar_v1_1_tx_aware`.

Acquisition mechanics congeladas, não regras de trading:
- fast window 30s;
- baseline horizon 300s;
- >=6 fast events;
- >=4 known unique wallets;
- established: >=3 baseline events e >=3x activity-rate acceleration;
- fresh token: causal token age <=120s;
- quando transaction identity coverage = 100%, >=4 unique fast transactions;
- direction é descritiva.

**Nenhum threshold foi ajustado por P&L ou pelos live smokes.**

## Causalidade e replay

`src/market_observation_store.py` separa `chain_time` de `observed_at`.

Shared market replay semantics:
- exact replay é idempotente;
- SQLite completion order não define causalidade;
- menor collector `observed_at` vence;
- conflito de identidade no mesmo run+event_key é auditado em `market_replay_conflicts`;
- conflito não cria flow adicional nem derruba a aquisição;
- empate de `observed_at` usa tie-break determinístico apenas para estabilidade, mantendo a ambiguidade auditada.

Pump mantém telemetria específica em `pump_replay_conflicts`.

Trigger/episode replay semantics em `src/market_opportunity_episode_store.py`:
- mesmo `trigger_key` não cria raw trigger/episode/enrichment duplicado;
- recomputação posterior divergente é auditada em `market_trigger_replay_conflicts`;
- o trigger-to-episode já persistido permanece canônico;
- replay recebido depois não reescreve retroativamente um episódio já aberto.

`decision_as_of` é imutável depois do freeze e ainda não é congelado pelo radar atual.

Lifecycle:
- Pump `CreateEvent` = token birth para `fresh_market_burst`;
- PumpSwap `CreatePoolEvent` = pool/venue lifecycle, não token birth.

## PumpSwap asset role e pool identity

Reference assets v1:
- WSOL `So11111111111111111111111111111111111111112`
- USDC `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`

Regras:
- exatamente um lado reference → outro lado é opportunity token;
- opportunity token base → side preservado;
- opportunity token quote → side invertido porque PumpSwap event é base-relative;
- two-reference/two-unknown → role filtered;
- reference assets nunca podem abrir opportunity episodes.

Pool identity:
- schema readiness cacheada por DB path;
- earliest observed identity é canônica;
- conflito é auditado em `pumpswap_pool_mapping_conflicts`;
- histórico cross-run ambíguo não é reutilizado;
- resolver concorrente recarrega mapping canônico persistido antes de devolver/cachear.

## Evidência live canônica

### Pump bonding
`pump-smoke-20260903-01`: 3,476 notifications; 3,688 decoded trades; 3,600 persisted; 223 tokens; 1,984 wallets. **PASS**.

### Pump -> radar
`market-radar-smoke-20260903-03`: 2,037 trades; 738 raw hits; 31 episodes; 29 hit tokens. 95.8% dos hits eram continuation. **PASS**. Enrichment caro deve ser episode-scoped.

### PumpSwap native
`pumpswap-smoke-20260903-01`: 837 trades; 150 pools; 737 wallets; 92/92 hydrations; zero failures/skips. **PASS**.

### Unified v2
2,480 received; ~19.4% processed; backlog 2,000. **CAUSAL BUNDLE PASS / THROUGHPUT FAIL**.

### Unified v3
4,665 received; coverage 80.1%; Pump p95 52.6s; PumpSwap p95 29.0s; budget skips 41. **SEMANTICS PASS / CAPACITY FAIL**.

### Unified v4
2,949 received; coverage 99.2%; backlog ~0.85%; Pump p95 38.3s; PumpSwap p95 7.8s. **CAPACITY PASS / LATENCY FAIL**.

### Unified v5
`unified-market-smoke-20260903-05`: 4,945 received; coverage 79.6%; Pump p95 8.52s; PumpSwap p95 71.15s; RPC failures 0; budget skips 0. **BURST CAPACITY/LATENCY FAIL**.

### v5b/v5c/v5d replay incidents
- v5b: Pump `signature:index` replay conflict → aborted before summary;
- repeated 05b namespace: invalid/contaminated;
- v5c: shared PumpSwap market observation replay conflict → aborted before summary;
- v5d: market trigger replay conflict → aborted before summary.

Correções resultantes:
- Pump replay audit;
- shared market replay audit/canonicalization;
- trigger replay audit;
- PumpSwap pool mapping audit;
- canonical resolver reload;
- PumpSwap pool schema hot-path cache;
- replay diagnostics mesmo em fail-fast.

### v5e
Fresh clean stress após hardening:
- coverage 97.0%;
- backlog ~2.98%;
- zero drops/errors/reference episodes/budget skips;
- Pump radar p95 24.50s;
- PumpSwap radar p95 4.854s;
- replay counters todos zero.

Classification: **INTEGRITY PASS / COVERAGE PASS / PUMPSWAP LATENCY PASS / PUMP LATENCY FAIL**.

### v6 — Pump ordered microbatch
Run: `unified-market-smoke-20260903-06`.

Observed:
- received 3,530 = PumpSwap 2,181 + Pump 1,349;
- persistence completed PumpSwap 2,181 / Pump 1,349;
- radar processed PumpSwap 2,181 / Pump 1,348;
- radar coverage **100.0%**;
- deadline backlog 1 item (~0.03%);
- dropped 0; worker errors 0; reference episodes 0; budget skips 0;
- Pump persist p95 **1.909s**;
- Pump radar p95 **2.802s**;
- PumpSwap persist p95 **0.583s**;
- PumpSwap radar p95 **7.952s**;
- Pump microbatch: 163 batches, avg 8.28, max 32;
- 84 episodes/enrichments; bundles populated;
- Pump replay conflicts 0;
- shared market replay conflicts 1 (`trade:retain_earlier_observation`);
- trigger replay conflicts 0;
- pool mapping conflicts 0.

Classification: **INTEGRITY PASS / COVERAGE PASS / PUMP LATENCY PASS / PUMPSWAP LATENCY FAIL**.

The single shared replay conflict is audited and not an automatic short-smoke failure, but must be inspected before long acquisition. Use:

```powershell
python market_replay_conflict_report.py --run-key unified-market-smoke-20260903-06
```

Canonical report/design: `docs/unified-market-latency-v6-live-and-v7-design-2026-09-03.md`.

## Throughput / latency architecture

### Pump — v6 active

```text
Pump websocket
-> FIFO queue
-> one ordered writer
-> microbatch <=32 notifications, max dwell 25ms
-> one SQLite transaction per microbatch
-> completed queue already in ingress order
-> radar
```

v6 proved this architecture can satisfy the Pump p95 <=5s gate under the observed live load.

### PumpSwap — v7 current gate

v6 PumpSwap persistence is healthy (<1s p95), but one global radar coordinator caused cross-asset head-of-line pressure.

v7:

```text
PumpSwap websocket
-> bounded concurrent resolution/persistence
-> completed queue
-> lightweight global ingress-order dispatcher
-> canonical opportunity-asset ticket reservations
-> 4 concurrent radar workers
```

Causal invariant:
- dispatcher issues reservations in original websocket sequence;
- same opportunity token cannot be evaluated out of order;
- overlapping multi-token notifications preserve the induced partial order;
- disjoint assets may be evaluated concurrently;
- canonical affected assets are read back from persisted transaction identity, so rejected replay identities cannot influence scheduling.

Implementation files:
- `src/pumpswap_asset_order.py`;
- canonical `affected_tokens` on `PumpSwapNormalizedPersistResult`;
- optional per-asset radar mode in `unified_market_throughput_smoke_v4.py`;
- runner `unified_market_latency_smoke_v7.py`.

Code/CI status: **578 tests / 0 failures; compileall PASS; CI PASS**. Live v7 pending.

## v7 frozen live gate

Configuration:
- duration 120s;
- confirmed;
- Pump writer 1 ordered microbatch;
- Pump batch size 32;
- Pump batch max wait 25ms;
- PumpSwap persistence workers 24;
- PumpSwap radar workers 4;
- max concurrent resolutions 18;
- max hydrations 1500;
- queue size 5000.

PASS only if all are true:
1. no traceback / worker errors;
2. zero dropped notifications;
3. `reference_asset_episodes == 0`;
4. both venues persist observations;
5. total radar coverage >=95%;
6. total deadline backlog <=5% received;
7. Pump radar e2e p95 <=5s;
8. PumpSwap radar e2e p95 <=5s;
9. budget skips == 0;
10. admitted bundles not systematically empty.

Replay-conflict counters são audit telemetry, não automatic FAIL. Todo non-zero precisa ser inspecionado antes de long acquisition.

## Depois do latency PASS

1. Jupiter executable quote somente para novo episode admitido;
2. hazard provider mínimo com explicit missing/failure;
3. historical wallet outcomes resolvidos antes do T0;
4. freeze final `decision_as_of` depois das tentativas obrigatórias de provider;
5. short true economic E2E smoke;
6. auditar provider coverage/reconnect/dedup/clocks/cost;
7. definir long-run hydration/rate/backpressure policy;
8. congelar protocolo runnable;
9. somente então primeira coleta de 12h.

## Avaliação econômica futura

Outcomes +5m/+15m/+60m com semântica executável/route-aware quando possível. Nunca substituir silenciosamente quote/fill ausente por candle posterior.

Ablations: movement, flow, execution, wallet e risk. Métricas mínimas: mean/median, win rate, profit factor, drawdown, coverage, token/cluster concentration e contribuição dos maiores winners. Resultados devem ser testados removendo top winners para medir fragilidade de heavy tails.

## Shadow / live

- native acquisition: Pump PASS / PumpSwap PASS;
- causal unified local bundle: PASS;
- replay integrity: code/CI/live PASS;
- Pump latency: PASS em v6;
- PumpSwap latency: FAIL em v6, v7 pending;
- economic edge: não estabelecido;
- executable fill/landing: não validado;
- shadow/live: **não liberado**.
