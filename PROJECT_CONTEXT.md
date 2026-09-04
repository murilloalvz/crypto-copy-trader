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
- **Unified Market Latency v30: FORMAL PASS histórico/canônico.**
- **v31 live: FAIL do executable-quote gate e evidência de regressão de robustez sob burst de unknown-pool hydration.**
- v32 batched unknown-pool hydration: **CODE/CI pronto; live pendente**.
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
- mapping canônico é recarregado antes da normalização final;
- quando identidade só fica conhecida por RPC, trade normalized usa `effective_observed_at=max(notification.observed_at, mapping.observed_at)`.

## Arquitetura vencedora de acquisition/radar — v30 baseline

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

## Unified Market Latency v30 — FORMAL PASS baseline

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

Frozen latency PASS conditions:
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

O v30 permanece o **baseline histórico PASS**, mas qualquer pipeline integrado com novos providers deve continuar satisfazendo esses critérios no mesmo live run. O v31 mostrou que robustez sob unknown-pool burst ainda precisava endurecimento.

## v31 live — executable quote FAIL + robustness regression

Primeiro live v31, 2026-09-04:
- elapsed: 123.3s;
- received total: **5769**;
- processed total: **5753**;
- coverage: **99.7% PASS**;
- true backlog: `16/5769 = 0.277% PASS`;
- errors: 0;
- drops: 0;
- reference asset episodes: 0;
- budget skips: 0;
- superset violations: 0;
- Pump radar p95: **7.223s FAIL**;
- PumpSwap pipeline p95: **50.768s FAIL**.

Critical systems telemetry:
- PumpSwap writer batch service p95: **76.2ms** — healthy;
- event-loop lag p95: **28.6ms** — healthy;
- network pool hydrations: **299**;
- hydration successes: 299;
- singleflight waits: **271**;
- normalization->reservation p95: **50.006s**;
- prepared->submit p95: **49.079s**.

Interpretation:
- SQLite writer did not regress;
- event loop did not regress;
- burst de pools desconhecidos criou long resolution sequence holes;
- global ingress-ordered reservation coordinator reteve hints posteriores atrás desses holes;
- late release criou burst stateful e também elevou Pump trigger-commit queue;
- portanto v31 reabriu **robustness of systems latency**, não a validade histórica do v30 PASS.

Jupiter v31 result, first predeclared 12 new admissions:
- `AVAILABLE=0`;
- `UNAVAILABLE=11`;
- `METADATA_ERROR=1`;
- other terminal errors=0;
- terminal coverage=100%;
- quotes persisted=11;
- executable quotes=0;
- reused attempts=0;
- quote worker errors=0.

Formal classification: **v31 executable-quote gate FAIL** because no persisted executable quote existed and the same run violated latency gates #6/#7.

The 11 `UNAVAILABLE` rows contained normalizable Jupiter order evidence but no assembled transaction. The first live did not surface Jupiter's `errorCode/errorMessage`, so no causal claim is made yet about why assembly was unavailable.

## v32 — batched unknown-pool hydration + Jupiter terminal reason

Goal: harden v30/v31 against unknown-pool bursts **without weakening ordering or causal semantics**.

New systems layer:
- `src/pumpswap_batched_resolver_v32.py`;
- concurrent unknown-pool misses still pass through cache/store/historical, per-pool single-flight and global expensive-resolution semaphore;
- final network reads are coalesced into Solana `getMultipleAccounts` batches;
- hydration budget remains counted per pool, not per RPC call;
- default batch: 64 pools / max wait 5ms;
- same `max_concurrent_resolutions=18`;
- same global reservation sequence coordinator;
- same per-asset FIFO;
- same `effective_observed_at`;
- same persistence/replay/detector/episode semantics.

Jupiter diagnostics hardening:
- `provider_error_code` and `provider_error_message` from `/order` are persisted in provider-attempt details;
- `[jupiter-episode]` lines now print explicit terminal `reason=...`;
- unavailable provider evidence is not guessed or rewritten.

Wrapper:
- `unified_market_execution_quote_smoke_v32.py`;
- patches only the resolver class during the nested v31 run and restores it in `finally`;
- prints `V32 BATCHED PUMPSWAP UNKNOWN-POOL HYDRATION DIAGNOSTIC`.

Pre-live validation:
- **671 tests / 0 failures**;
- GitHub Actions PASS on HEAD `b81a0f49e4c95f8d25608e0c64681e1cb7d1b440` before this context-only commit;
- batch behavior, per-pool budget and patch restoration are covered.

Expected evidence if v32 works:
- `network_batch_calls << pool_hydrations`;
- average batch size >1 under miss bursts;
- normalization->reservation and prepared->submit p95 collapse;
- current-run Pump/PumpSwap latency gates return <=5s;
- Jupiter reason lines explain `UNAVAILABLE` without inference.

## Current executable quote protocol

Provider attempt lifecycle:
- `STARTED` persisted before I/O;
- terminal statuses: `AVAILABLE`, `UNAVAILABLE`, `CONFIG_MISSING`, `PROVIDER_ERROR`, `METADATA_ERROR`, `NORMALIZATION_ERROR`;
- terminal immutable;
- crash with STARTED remains visible;
- replay does not silently reexecute provider.

Frozen cohort/config:
- first 12 **new admissions** of fresh run;
- 2 Jupiter workers;
- input USDC;
- notional US$25;
- slippage request 100 bps;
- token decimals via causal `getTokenSupply`;
- Jupiter timeout 5s;
- taker = public Solana address only;
- no private key;
- no signing;
- no `/execute` or submit.

Gate remains:
- all 11 current-run market-latency conditions green;
- selected >0 (`0 => INCONCLUSIVE_NO_SAMPLE`);
- terminal coverage=100%;
- no selected STARTED;
- CONFIG_MISSING=0;
- quote_worker_errors=0;
- reused_attempts=0 on fresh run;
- >=1 `AVAILABLE` executable quote persisted;
- causal clocks valid;
- no synthetic/backfilled provider evidence.

Não existe threshold arbitrário de `% AVAILABLE`; distribuição é evidence descritiva. Não alterar notional/slippage/taker retroativamente para fabricar PASS sem primeiro interpretar o motivo explícito do provider.

## Ordem congelada após executable-quote PASS

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
- unified systems latency: **v30 historical FORMAL PASS; v31 integrated run exposed robustness regression now targeted by v32**;
- executable Jupiter entry quote: **v31 first live FAIL; v32 live pending**;
- hazard/risk integration: pending;
- economic edge: not established;
- executable fill/landing: not validated;
- shadow/live: **not released**.
