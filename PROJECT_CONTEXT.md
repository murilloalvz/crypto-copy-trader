# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado fica em `docs/`; aqui permanecem somente decisões, evidências canônicas e gates necessários para continuar sem reabrir trabalho encerrado.

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
- Unified throughput v3: semantic fixes PASS / capacity FAIL.
- Unified throughput v4: coverage/capacity PASS / latency FAIL.
- Unified latency v5 inicial: **FAIL sob burst — PumpSwap head-of-line/capacity pressure**.
- v5b/v5c/v5d: três replay-integrity incidents sucessivos; todos preservados como evidência, não como throughput results.
- End-to-end replay hardening de observation → pool mapping → trigger/episode: **CODE/CI PASS + LIVE REVALIDATION PASS** em v5e; todos os replay-conflict counters ficaram zero.
- v5e: **INTEGRITY PASS / COVERAGE PASS / PUMPSWAP LATENCY PASS / PUMP LATENCY FAIL**.
- PumpSwap pool schema hot-path cache + canonical resolver: live v5e p95 4.854s, sem RPC failures/budget skips.
- Gate atual: **Unified latency v6 — Pump ordered SQLite microbatch**. Não aumentar writer concurrency cegamente.
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

Objetivo: identificar movimentos precoces cujo resultado forward, líquido de custos e com executabilidade realista, permaneça favorável fora da amostra.

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
- direction é apenas descritiva.

**Nenhum threshold foi ajustado por P&L ou pelos live smokes.**

## Causalidade, replay e episodes

`src/market_observation_store.py` separa `chain_time` de `observed_at`.

Shared market observation replay semantics:
- exact replay é idempotente;
- SQLite completion order não define causalidade;
- o menor collector `observed_at` vence, mesmo se persistir depois;
- replay conflitante no mesmo run+event_key é auditado em `market_replay_conflicts`;
- identidade conflitante posterior não sobrescreve observação causalmente anterior;
- se `observed_at` empata na resolução de segundos, identidade serializada estável é tie-break determinístico e a ambiguidade continua auditada;
- conflito não vira evento adicional de flow e não derruba a aquisição.

No adapter Pump batch, `pump_replay_conflicts` permanece como telemetria específica do incidente anterior.

`src/market_opportunity_episode_store.py` deduplica raw hits por run+token em 60s. O `trigger_key` representa uma única avaliação de uma notification/token e tem replay semantics explícitas:
- exact replay posterior é idempotente;
- replay posterior que recomputa kind/direction/identity diferente é auditado em `market_trigger_replay_conflicts`;
- o primeiro trigger-to-episode persistido permanece canônico;
- replay não cria trigger/episode/enrichment adicional;
- replay mais cedo recebido depois não retroativamente reparticiona um episode já aberto; é auditado conservadoramente;
- referential corruption real continua fatal.

`decision_as_of` é imutável depois do freeze e não é congelado pelo radar.

Lifecycle venue-aware:
- Pump `CreateEvent` = token birth para `fresh_market_burst`;
- PumpSwap `CreatePoolEvent` = venue/pool lifecycle, não token birth.

Wallet é evidência pós-episódio, nunca whitelist de aquisição.

## PumpSwap asset-role e pool identity

V1 reference assets: WSOL e USDC.

- exatamente um lado da pool deve ser reference asset;
- o outro vira opportunity token;
- se opportunity token é base, side é preservado;
- se é quote, buy/sell é invertido porque PumpSwap events são base-relative;
- pares two-reference/two-unknown são `role_filtered`;
- WSOL/USDC não podem virar opportunity episodes.

Pool identity no caminho concorrente:
- schema readiness é cacheada por active SQLite path; DDL não roda em todo lookup;
- mesma identidade com observação anterior move first-known time/provenance para trás;
- conflito de identidade é auditado em `pumpswap_pool_mapping_conflicts`;
- earliest observed identity vence; empate usa tie-break determinístico e continua auditado;
- histórico cross-run ambíguo não é reutilizado; força fresh resolution;
- concurrent resolver recarrega o mapping canônico do store antes de devolver/cachear, fechando race RPC vs `CreatePoolEvent`.

## Evidência live canônica

### Pump bonding
`pump-smoke-20260903-01`: 3,476 notifications; 3,688 decoded trades; 3,600 persisted; 223 tokens; 1,984 wallets. **PASS**.

### Pump -> radar
`market-radar-smoke-20260903-03`: 2,037 persisted trades; 738 raw hits; 31 episodes; 29 hit tokens. 95.8% dos raw hits eram continuation; enrichment caro deve ser episode-scoped. **PASS**.

### PumpSwap native
`pumpswap-smoke-20260903-01`: 837/837 trades persistidos; 150 pools; 737 wallets; 92/92 hydrations; 0 failures/skips. **PASS**.

### Unified v2
`unified-market-smoke-20260903-02`: 2,480 received; ~19.4% processed; backlog 2,000; causal bundle flow/wallet semantics válidas. **BUNDLE PASS / THROUGHPUT FAIL**.

### Unified v3
`unified-market-smoke-20260903-03`: 4,665 received; coverage 80.1%; Pump backlog 910; Pump p95 52.6s; PumpSwap p95 29.0s; budget skips 41. **SEMANTICS PASS / CAPACITY FAIL**.

### Unified v4
`unified-market-smoke-20260903-04`: 2,949 received; coverage 99.2%; backlog ~0.85%; Pump p95 38.3s; PumpSwap p95 7.8s; zero drops/errors/reference episodes/budget skips. **CAPACITY PASS / LATENCY FAIL**.

### Unified latency v5 inicial
`unified-market-smoke-20260903-05`, 120s:
- received 4,945 = PumpSwap 3,606 + Pump 1,339;
- dropped 0; worker errors 0;
- radar coverage 79.6%;
- Pump p95 8.52s;
- PumpSwap p95 71.15s;
- PumpSwap hydrations 350, successes 348, RPC failures 0, budget skips 0;
- 68 episodes/enrichments; reference-asset episodes 0.

Decision: **FAIL — burst capacity/latency**. v4/v5 não são controlled A/B porque o ingress mudou muito.

### v5b / v5c / v5d replay integrity incidents

- `05b`: Pump `signature:index` replay conflict antes de SUMMARY;
- reutilização acidental do namespace `05b`: INVALID / CONTAMINATED;
- `05c`: shared `market_observation_store` PumpSwap replay conflict antes de SUMMARY;
- `05d`: `market_opportunity_episode_store` trigger replay conflict antes de SUMMARY.

Esses incidents produziram o end-to-end hardening atual:
- observation replay canonicalization + audit;
- trigger replay idempotent/auditável sem episode duplicado;
- PumpSwap pool mapping replay/conflict auditável;
- PumpSwap pool schema fora do hot path;
- ambiguous historical pool identity não reutilizada;
- concurrent resolver sempre devolve mapping canônico persistido;
- wrapper de latency imprime replay diagnostics em `finally`.

Canonical docs:
- `docs/pump-replay-integrity-v5b-incident-2026-09-03.md`;
- `docs/shared-market-replay-integrity-v5c-incident-2026-09-03.md`;
- `docs/end-to-end-replay-integrity-v5d-incident-2026-09-03.md`.

### Unified latency v5e — clean end-to-end revalidation

Run: `unified-market-smoke-20260903-05e`, 120s.

- received 4,256 = Pump 1,878 + PumpSwap 2,378;
- dropped 0; worker errors 0;
- persistence completed: Pump 1,856 / PumpSwap 2,378;
- radar processed: Pump 1,751 / PumpSwap 2,378;
- radar coverage: **97.0%**;
- deadline backlog: 127 = Pump ingress 21 + Pump inflight 1 + Pump reorder 105;
- backlog / received: **2.98%**;
- Pump persistence queue p95: **23.901s**;
- Pump radar end-to-end p95: **24.504s**;
- PumpSwap persistence queue p95: **0.698s**;
- PumpSwap radar end-to-end p95: **4.854s**;
- PumpSwap network hydrations 74 / successes 74 / RPC failures 0 / budget skips 0;
- 62 unique episodes / 62 enrichments;
- reference-asset episodes 0;
- bundle flow30 total 908 / wallets total 787;
- all four replay-conflict counters: **0**.

Frozen v5 gate:
- errors PASS;
- drops PASS;
- reference assets PASS;
- coverage PASS;
- backlog PASS;
- **Pump latency FAIL**;
- PumpSwap latency PASS;
- budget PASS;
- bundle population PASS.

Classification: **INTEGRITY PASS / COVERAGE PASS / PUMPSWAP LATENCY PASS / PUMP LATENCY FAIL**.

The near-equality of Pump persistence queue p95 (23.901s) and Pump radar p95 (24.504s) localizes the dominant delay to Pump persistence admission, not detector computation. Eight SQLite writers complete out of ingress order while SQLite still serializes actual writes; this also creates the 105-item Pump reorder backlog.

Canonical report/design: `docs/unified-market-latency-v5e-and-v6-design-2026-09-03.md`.

## Throughput / latency architecture

Historical v5 Pump path:
```text
websocket -> queue -> 8 concurrent per-notification SQLite transactions -> completed queue -> ingress-order radar
```

Current v6 Pump path under test:
```text
websocket
-> FIFO queue
-> ONE ordered microbatch writer
-> one SQLite transaction for up to N notifications
-> completed queue in ingress order
-> ingress-order radar
```

Implementation:
- `src/pump_microbatch_persistence.py`;
- optional microbatch mode in `unified_market_throughput_smoke_v4.run_smoke` with legacy defaults unchanged;
- `unified_market_latency_smoke_v6.py` as the dedicated live runner.

PumpSwap remains:
```text
websocket -> concurrent pool resolution/persistence -> completed queue -> ingress-order radar
```

v6 changes only Pump write scheduling. Detector, T0, raw event identity, replay semantics, episode semantics and PumpSwap configuration remain unchanged.

## Gate atual — Unified latency v6 Pump microbatch

Frozen before any v6 live result.

Configuration:
- duration 120s;
- commitment confirmed;
- Pump writer: one ordered SQLite microbatch writer;
- Pump batch size ceiling: 32 notifications;
- Pump maximum batch dwell: 25ms;
- PumpSwap workers 24;
- max concurrent PumpSwap resolutions 18;
- max hydrations 1500;
- RPC timeout 3s;
- queue size 5000.

PASS only if:
1. no worker errors / traceback;
2. zero dropped notifications;
3. `reference_asset_episodes == 0`;
4. radar coverage >=95%;
5. total deadline backlog <=5% of received;
6. Pump radar p95 <=5s;
7. PumpSwap radar p95 <=5s;
8. budget skips == 0;
9. admitted bundles are not systematically empty;
10. replay-conflict telemetry is inspected; unexplained non-zero conflicts block long acquisition.

If Pump still fails, **do not increase SQLite writer concurrency**. Profile transaction time versus radar read/enrichment time and consider a dedicated append-only ingestion DB / WAL-oriented writer or staged causal in-memory window only with explicit crash/recovery invariants.

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

Ablations: movement, flow, execution, wallet e risk. Métricas mínimas: mean/median, win rate, profit factor, drawdown, coverage, token/cluster concentration e contribuição dos maiores winners.

## Shadow / live

- native acquisition: Pump PASS / PumpSwap PASS;
- causal unified local bundle: PASS;
- v4: capacity PASS / latency FAIL;
- v5 inicial: burst capacity/latency FAIL;
- v5b/v5c/v5d: replay integrity incidents, todos resolvidos em código;
- v5e: replay integrity LIVE PASS, coverage/backlog PASS, PumpSwap latency PASS, Pump latency FAIL;
- v6 Pump microbatch: code/CI validation em andamento, live pending;
- economic edge: não estabelecido;
- executable fill/landing: não validado;
- shadow/live: não liberado.
