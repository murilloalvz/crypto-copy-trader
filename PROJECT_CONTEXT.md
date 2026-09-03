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
- Unified single-consumer throughput: **FAIL**; substituído pela arquitetura throughput v3.
- Throughput v3: implementado e CI green; **short live smoke é o próximo gate**.
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
- 472 BUY / 365 SELL;
- 150 pools;
- 737 wallets;
- 0 unresolved;
- 92/92 network hydrations successful;
- 0 hydration failures / budget skips.

Decisão: **NATIVE PUMPSWAP ACQUISITION + CAUSAL POOL RESOLUTION PASS**.

### Unified v2

`unified-market-smoke-20260903-02`, requested 120s:
- received: 1,054 Pump + 1,426 PumpSwap = 2,480;
- processed before deadline: 252 Pump + 228 PumpSwap = 480 (~19.4%);
- backlog: 802 Pump + 1,198 PumpSwap = 2,000;
- queue high-water: 2,000/2,000;
- persisted: 234 Pump + 255 PumpSwap trades;
- 2 unique episodes / 2 enrichments;
- bundle totals: flow30=29, wallets=23;
- PumpSwap hydrations 97/97, 0 real RPC failures, 0 budget skips.

Decision: **CAUSAL BUNDLE PASS / THROUGHPUT FAIL**.

The v2 bundle fixed the prior clock bug: enrichment is anchored to `episode.first_trigger_observed_at`, not delayed queue-processing wall time. Jupiter must remain blocked until throughput is healthy.

The run also exposed a PumpSwap asset-role bug by opening an episode on WSOL. This is fixed in throughput v3.

## PumpSwap asset-role normalization v3

Active files:

- `src/pumpswap_asset_role.py`;
- `src/pumpswap_normalized_persistence.py`;
- `src/pumpswap_concurrent_resolver.py`;
- `src/pumpswap_radar_bridge_v3.py`.

V1 reference assets are intentionally narrow: WSOL and USDC.

Rules:

- exactly one pool side must be a known reference asset;
- the other side becomes the opportunity token;
- if opportunity token is PumpSwap base, event buy/sell is preserved;
- if opportunity token is quote, buy/sell is inverted because PumpSwap events are base-relative;
- two-reference or two-unknown pairs are explicit `role_filtered`, never guessed;
- WSOL/USDC cannot become opportunity episodes;
- immutable pool `base_mint/quote_mint` identity remains preserved separately.

## Throughput v3

Design freeze:
`docs/unified-market-throughput-v3-design-2026-09-03.md`

Runner:
`unified_market_throughput_smoke_v3.py`

Architecture:

```text
Pump websocket
-> dedicated Pump queue
-> ordered Pump persist+radar worker

PumpSwap websocket
-> dedicated PumpSwap queue
-> bounded concurrent persistence/pool-resolution workers
-> completed queue
-> ingress-order PumpSwap radar coordinator

Both
-> shared Opportunity Episode store
-> exactly-once local episode bundle
```

PumpSwap persistence may complete concurrently/out of order, but radar/episode assignment remains in ingress order. Radar loaders apply causal `as_of`, so later-persisted observations remain invisible to earlier evaluation boundaries.

Pool resolver adds per-pool single-flight + bounded global concurrency while retaining cache/current-run/historical reuse.

CI at the v3 code state:
- `python -m compileall -q .`: PASS;
- `python -m unittest discover -s tests -q`: **553 tests, 0 failures**.

## Throughput v3 live PASS gate

The 120s v3 smoke is an operational PASS only if:

1. no traceback / worker errors;
2. zero dropped notifications;
3. `reference_asset_episodes == 0`;
4. Pump and PumpSwap both persist observations;
5. total radar coverage >=95% at deadline;
6. total remaining backlog <=5% of enqueued notifications;
7. Pump queue-wait p95 <=2s;
8. PumpSwap radar end-to-end wait p95 <=5s;
9. `budget_skips == 0`;
10. if episodes are admitted, flow/wallet bundles are not systematically empty.

These are **capture/capacity criteria**, not economic thresholds. Failure here means fix acquisition/backpressure, never retune radar.

## Próximo gate obrigatório

Run short live throughput v3. **Não adicionar Jupiter antes do PASS.**

Depois do PASS:

1. Jupiter executable quote somente para novo episode admitido;
2. hazard provider mínimo com explicit missing/failure;
3. historical wallet outcomes resolvidos antes do T0;
4. freeze final `decision_as_of` depois das tentativas obrigatórias de provider;
5. short true economic E2E smoke;
6. auditar provider coverage/reconnect/dedup/clocks/cost;
7. congelar protocolo runnable;
8. somente então primeira coleta de 12h.

## Avaliação econômica futura

Outcomes inicialmente separados em +5m / +15m / +60m, com semântica executável/route-aware quando possível. Não substituir silenciosamente quote/fill ausente por candle posterior.

Ablations devem testar valor incremental de movement, flow, execution, wallet e risk. Features sem valor OOS devem ser removidas.

Métricas mínimas: mean/median, win rate, profit factor, drawdown, coverage, token/cluster concentration e contribuição dos maiores winners.

## Shadow / live

- native acquisition: Pump PASS / PumpSwap PASS;
- causal unified local bundle: PASS;
- unified throughput v2: FAIL;
- throughput v3: CI PASS / live pending;
- economic edge market-first: não estabelecido;
- executable fill/landing: não validado;
- shadow: não liberado;
- live: não liberado.
