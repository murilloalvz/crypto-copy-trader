# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado fica em `docs/`; aqui permanecem somente decisões, evidências canônicas e gates necessários para continuar sem reabrir trabalho encerrado.

## Estado atual

- Repositório: `murilloalvz/crypto-copy-trader`.
- Branch de pesquisa principal: `feat/exit-engine-v1`.
- Modo: **PAPER / RESEARCH / READ ONLY**.
- Nenhum fluxo ativo assina, envia ou executa transações reais.
- Persistência: SQLite via `DATABASE_PATH`.
- Tese ativa: **market-first Solana Opportunity Intelligence / Opportunity Engine**.
- Wallet Forward v2: encerrado como **OUTCOME D — TOO LITTLE ECONOMIC SAMPLE**; não iniciar Run 3.
- Protocolo wallet-triggered antigo: **SUPERSEDED BEFORE RUN**.
- Pump bonding acquisition: live PASS.
- Pump -> Radar -> Opportunity Episode: live PASS.
- PumpSwap acquisition + causal pool resolution: live PASS.
- Unified local causal bundle: live PASS para flow/wallet semantics.
- Unified throughput v2: FAIL.
- Unified throughput v3: **semantic fixes PASS / capacity FAIL**.
- Throughput v4: implementado + CI green; **short live smoke é o próximo gate**.
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

## Core ativo

Prioridade:
1. market movement / lifecycle;
2. order flow / microstructure;
3. liquidity / execution / tradability;
4. token hazard / manipulation risk;
5. dynamic wallet intelligence;
6. regime simples somente se provar valor incremental.

Deferred/frozen: Social/X, Telegram/NLP, graph avançado, whitelist/ranking sofisticado de wallets, ML complexo, dashboard cosmético, expansão ampla para outras DEXs, novas famílias de exit e live trading.

## Regra de wallet

**Não existe whitelist de “wallets boas” no caminho do radar.** O mercado cria o episódio; depois analisamos as wallets realmente presentes usando apenas informação resolvida antes do T0 atual.

- wallet desconhecida não é ruim;
- wallet historicamente forte não recebe passe livre;
- missing history permanece missing;
- episódio atual não entra como histórico passado;
- outcome conhecido só depois de T0 não pode contaminar T0;
- `Copyability Score` antigo não pode ser filtro oculto.

## Detector ativo

`src/market_opportunity_radar.py`

Versão: `market_opportunity_radar_v1_1_tx_aware`.

Acquisition mechanics congeladas, não regras de trading:
- fast window 30s;
- baseline horizon 300s;
- >=6 fast events;
- >=4 known unique wallets;
- established: >=3 baseline events e >=3x activity-rate acceleration;
- fresh token: causal token age <=120s;
- quando transaction identity coverage = 100%, >=4 unique fast transactions;
- direction é apenas descritiva.

Nenhum threshold foi ajustado por P&L ou pelos live smokes.

## Causal clocks e episodes

`src/market_observation_store.py` separa `chain_time` de `observed_at`, persiste source/venue/wallet/transaction identity e missing price/notional explicitamente.

Replay idêntico posterior preserva o primeiro `observed_at`; backdating e mutação real são rejeitados.

`src/market_opportunity_episode_store.py` deduplica raw hits: mesmo run+token dentro de 60s reutiliza episode. `decision_as_of` é imutável depois do freeze e **não é congelado pelo radar**.

Lifecycle venue-aware:
- Pump bonding `CreateEvent` = token birth para `fresh_market_burst` v1;
- PumpSwap `CreatePoolEvent` = pool/venue lifecycle, não token birth;
- PumpSwap pool creation não pode rejuvenescer token migrado/antigo.

## Evidência live canônica

### Pump bonding

`pump-smoke-20260903-01`, ~120s:
- 3,476 notifications;
- 3,688 decoded trade events;
- 3,600 persisted;
- 223 tokens;
- 1,984 wallets.

Decisão: **NATIVE PUMP ACQUISITION PASS**.

### Pump -> radar -> episode

`market-radar-smoke-20260903-03`, 120s:
- 2,037 persisted trades;
- 156 evaluated tokens;
- 738 raw hits;
- 707 continuation hits = 95.8%;
- 31 unique episodes;
- 29 unique hit tokens.

Decisão: **PUMP -> RADAR -> OPPORTUNITY EPISODE PASS**.

Conclusão: enrichment caro deve ser **episode-scoped**, nunca raw-hit-scoped.

### PumpSwap native acquisition

`pumpswap-smoke-20260903-01`, 120.8s:
- 749 notifications;
- 837 decoded/persisted trades;
- 150 pools;
- 737 wallets;
- 0 unresolved;
- 92/92 network hydrations successful;
- 0 hydration failures / budget skips.

Decisão: **NATIVE PUMPSWAP ACQUISITION + CAUSAL POOL RESOLUTION PASS**.

### Unified v2

`unified-market-smoke-20260903-02`:
- received 2,480;
- processed by deadline 480 (~19.4%);
- backlog 2,000;
- bundle flow/wallet semantics valid after T0 clock fix.

Decisão: **CAUSAL BUNDLE PASS / THROUGHPUT FAIL**.

### Unified throughput v3

`unified-market-smoke-20260903-03`, 120s:
- received: Pump 2,181 / PumpSwap 2,484 = 4,665;
- dropped: 0;
- worker errors: 0;
- radar processed: Pump 1,270 / PumpSwap 2,468;
- total radar coverage: **80.1%**;
- Pump backlog: 910;
- Pump queue wait p95: **52.6s**;
- PumpSwap radar end-to-end p95: **29.0s**;
- reference-asset episodes: 0;
- unique episodes: 77;
- enrichment admitted: 77;
- populated bundle totals: flow30 896 / wallets 754;
- PumpSwap hydrations: 300/300 successful;
- real RPC failures: 0;
- hydration budget skips: 41.

Decisão: **SEMANTIC FIXES PASS / THROUGHPUT CAPACITY FAIL**.

Canonical report: `docs/unified-market-throughput-v3-live-smoke-2026-09-03.md`.

Não retunar radar. Jupiter continua bloqueado até throughput PASS.

## PumpSwap asset-role normalization

Active files:
- `src/pumpswap_asset_role.py`;
- `src/pumpswap_normalized_persistence.py`;
- `src/pumpswap_concurrent_resolver.py`;
- `src/pumpswap_radar_bridge_v3.py`.

V1 reference assets: WSOL e USDC.

Rules:
- exactly one pool side must be a known reference asset;
- the other side becomes the opportunity token;
- if opportunity token is PumpSwap base, buy/sell is preserved;
- if opportunity token is quote, buy/sell is inverted because PumpSwap events are base-relative;
- two-reference or two-unknown pairs are explicit `role_filtered`, never guessed;
- WSOL/USDC cannot become opportunity episodes.

## Throughput v4

Design freeze: `docs/unified-market-throughput-v4-design-2026-09-03.md`.

Runner: `unified_market_throughput_smoke_v4.py`.

New Pump path:

```text
Pump websocket
-> dedicated ingress queue
-> bounded concurrent batch-persistence workers
-> one SQLite transaction per notification
-> completed queue
-> ingress-order radar coordinator
```

PumpSwap keeps bounded concurrent persistence/pool resolution plus ingress-order radar coordination.

The important causal invariant is unchanged: persistence may finish out of order, but **radar/episode assignment is released in websocket ingress order**, and loaders still enforce `observed_at <= as_of`.

New files:
- `src/pump_batch_persistence.py`;
- `src/pump_radar_bridge_v4.py`;
- `unified_market_throughput_smoke_v4.py`.

CI at v4 code state:
- `python -m compileall -q .`: PASS;
- `python -m unittest discover -s tests -q`: **557 tests, 0 failures**.

## Throughput v4 live PASS gate

The next 120s smoke is PASS only if:
1. no traceback / worker errors;
2. zero dropped notifications;
3. `reference_asset_episodes == 0`;
4. both venues persist observations;
5. total radar coverage >=95%;
6. total remaining backlog <=5% of enqueued;
7. Pump radar end-to-end p95 <=5s;
8. PumpSwap radar end-to-end p95 <=5s;
9. short-smoke `budget_skips == 0`;
10. admitted bundles are not systematically empty.

These are capture/capacity gates, not trading thresholds, and are frozen before the live run.

Initial v4 short-smoke configuration:
- Pump workers: 4;
- PumpSwap workers: 8;
- max concurrent PumpSwap resolutions: 6;
- queue size: 5,000;
- PumpSwap hydration ceiling: 1,000 **only as a non-binding short-smoke ceiling**.

A v4 PASS permits Jupiter episode-scoped work, but **does not permit 12h yet**. Long-run hydration/rate/cost policy remains mandatory before 12h.

## Próximo gate obrigatório

Run short live throughput v4. **Não adicionar Jupiter antes do PASS.**

Depois do PASS:
1. Jupiter executable quote somente para novo episode admitido;
2. hazard provider mínimo com explicit missing/failure;
3. historical wallet outcomes resolvidos antes do T0;
4. freeze final `decision_as_of` depois das tentativas obrigatórias de provider;
5. short true economic E2E smoke;
6. auditar provider coverage/reconnect/dedup/clocks/cost;
7. definir long-run PumpSwap hydration/rate/backpressure policy;
8. congelar protocolo runnable;
9. somente então primeira coleta de 12h.

## Avaliação econômica futura

Outcomes inicialmente separados em +5m / +15m / +60m, com semântica executável/route-aware quando possível. Não substituir silenciosamente quote/fill ausente por candle posterior.

Ablations devem testar valor incremental de movement, flow, execution, wallet e risk. Features sem valor OOS devem ser removidas.

Métricas mínimas: mean/median, win rate, profit factor, drawdown, coverage, token/cluster concentration e contribuição dos maiores winners.

## Shadow / live

- native acquisition: Pump PASS / PumpSwap PASS;
- causal unified local bundle: PASS;
- unified throughput v2: FAIL;
- throughput v3: semantic PASS / capacity FAIL;
- throughput v4: CI PASS / live pending;
- economic edge market-first: não estabelecido;
- executable fill/landing: não validado;
- shadow: não liberado;
- live: não liberado.
