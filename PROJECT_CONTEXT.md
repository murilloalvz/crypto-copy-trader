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
- Unified latency v5: **FAIL sob burst — Pump melhorou, PumpSwap sofreu head-of-line/capacity pressure**.
- Primeiro v5b: **ABORTED BEFORE SUMMARY** por conflito Pump `signature:index`; não é resultado de throughput/latência.
- Reuso acidental do namespace `05b`: inválido/contaminado; preservar como evidência, não usar para métricas.
- v5c limpo: **ABORTED BEFORE SUMMARY** por conflito PumpSwap no shared `market_observation_store`; confirmou bug compartilhado de replay/concurrency.
- Shared market replay integrity: **RESOLVED IN CODE / LIVE REVALIDATION PENDING**.
- Gate atual: repetir capacity stress com `run_key` novo e a mesma configuração congelada; não alterar detector/estratégia.
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

## Causalidade e episodes

`src/market_observation_store.py` separa `chain_time` de `observed_at`.

Shared replay semantics agora são:
- exact replay é idempotente;
- SQLite completion order não define causalidade;
- o menor collector `observed_at` vence, mesmo se persistir depois;
- replay conflitante no mesmo run+event_key é auditado em `market_replay_conflicts`;
- identidade conflitante posterior não sobrescreve observação causalmente anterior;
- se `observed_at` empata na resolução de segundos, identidade serializada estável é apenas tie-break determinístico e a ambiguidade continua auditada;
- conflito não vira evento adicional de flow e não derruba a aquisição.

No adapter Pump batch, `pump_replay_conflicts` permanece como telemetria específica do incidente anterior.

`src/market_opportunity_episode_store.py` deduplica raw hits por run+token em 60s. `decision_as_of` é imutável depois do freeze e não é congelado pelo radar.

Lifecycle venue-aware:
- Pump `CreateEvent` = token birth para `fresh_market_burst`;
- PumpSwap `CreatePoolEvent` = venue/pool lifecycle, não token birth.

Wallet é evidência pós-episódio, nunca whitelist de aquisição.

## PumpSwap asset-role normalization

V1 reference assets: WSOL e USDC.

- exatamente um lado da pool deve ser reference asset;
- o outro vira opportunity token;
- se opportunity token é base, side é preservado;
- se é quote, buy/sell é invertido porque PumpSwap events são base-relative;
- pares two-reference/two-unknown são `role_filtered`;
- WSOL/USDC não podem virar opportunity episodes.

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

### Unified latency v5
`unified-market-smoke-20260903-05`, 120s:
- received 4,945 = PumpSwap 3,606 + Pump 1,339;
- dropped 0; worker errors 0;
- radar coverage **79.6%**;
- Pump radar p50 2.19s / p95 **8.52s**;
- PumpSwap persistence p50 48.11s / p95 55.80s;
- PumpSwap radar p50 53.37s / p95 **71.15s**;
- PumpSwap hydrations 350, successes 348, RPC failures 0, budget skips 0;
- 68 episodes/enrichments; reference-asset episodes 0;
- bundle totals flow30 1,818 / wallets 1,292.

Decision: **FAIL — burst capacity/latency**. The Pump path improved materially after schema caching, but v4/v5 are not a controlled A/B because PumpSwap ingress rose from 1,517 to 3,606. PumpSwap failure is queue/head-of-line pressure, not RPC failure or budget exhaustion.

Canonical report: `docs/unified-market-latency-v5-live-smoke-2026-09-03.md`.

### v5b / v5c replay integrity incidents

Primeiro `unified-market-smoke-20260903-05b` abortou no Pump antes de SUMMARY por conflito no mesmo `signature:index`. O adapter Pump foi corrigido para earliest-observed canonical semantics e auditoria em `pump_replay_conflicts`.

A repetição acidental usando o mesmo `05b` foi classificada como **INVALID / CONTAMINATED RUN** porque o namespace já continha dados parciais.

A run limpa `unified-market-smoke-20260903-05c` reproduziu o mesmo tipo de falha no PumpSwap, agora dentro de `record_market_trade()`:

```text
ValueError: market trade event already exists with different data
```

Decision: **ABORTED BEFORE SUMMARY — SHARED REPLAY INTEGRITY FAILURE**. Não usar para throughput/latência.

A correção foi movida para o shared `market_observation_store`:
- exact replay idempotente;
- earliest collector `observed_at` canônico;
- conflicting identity auditada em `market_replay_conflicts`;
- same-second conflict recebe tie-break determinístico explícito;
- conflict não cria flow extra nem derruba a run;
- wrapper v5 reporta `pump_replay_conflicts` e `market_replay_conflicts` uma vez no final.

Canonical docs:
- `docs/pump-replay-integrity-v5b-incident-2026-09-03.md`;
- `docs/shared-market-replay-integrity-v5c-incident-2026-09-03.md`.

Validation da correção compartilhada: `compileall` PASS; **565 tests / 0 failures** antes do tie-break final; CI do tie-break final também PASS. Live revalidation ainda pendente.

## Throughput / latency architecture

Current v5 runner: `unified_market_latency_smoke_v5.py` over the v4 pipeline.

Pump:
```text
websocket -> queue -> concurrent batch persistence -> completed queue -> ingress-order radar
```

PumpSwap:
```text
websocket -> queue -> concurrent pool resolution/persistence -> completed queue -> ingress-order radar
```

Persistence may complete out of order, but radar assignment remains globally ingress-ordered per venue. This is causally conservative but can create cross-pool head-of-line blocking.

v5 caches schema readiness per active SQLite DB path, avoiding repeated DDL in observation/episode hot paths. Detector, T0, ordering and episode semantics are unchanged.

## Gate atual — fresh capacity stress after shared replay fix

Repeat the exact operational stress after the shared replay-integrity fix. No threshold/strategy change.

Configuration:
- Pump workers 8;
- PumpSwap workers 24;
- max concurrent PumpSwap resolutions 18;
- max hydrations 1500;
- queue size 5000;
- duration 120s.

PASS only if:
1. no worker errors / traceback;
2. zero dropped notifications;
3. `reference_asset_episodes == 0`;
4. radar coverage >=95%;
5. total deadline backlog <=5% of received;
6. Pump radar p95 <=5s;
7. PumpSwap radar p95 <=5s;
8. budget skips == 0;
9. admitted bundles are not systematically empty.

Replay-conflict counters are audit telemetry, not automatic FAIL by themselves. Any non-zero count must be inspected before long acquisition.

If the fresh stress still fails latency/capacity, **do not keep increasing concurrency blindly**. Redesign PumpSwap to remove global cross-pool head-of-line blocking while preserving causal ordering at the opportunity-asset level.

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
- v5: burst capacity/latency FAIL;
- first v5b: aborted on Pump replay integrity; no throughput conclusion;
- repeated same-key 05b: invalid/contaminated;
- v5c: clean reproduction of shared PumpSwap replay conflict; aborted before summary;
- shared replay integrity fix: CI PASS / live revalidation pending;
- economic edge: não estabelecido;
- executable fill/landing: não validado;
- shadow/live: não liberado.
