# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Histórico detalhado fica em `docs/`; aqui permanecem apenas decisões e gates necessários para continuar sem reabrir trabalho encerrado.

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
- Unified Pump + PumpSwap radar + episode-scoped local enrichment: implementado/testado; **short live smoke ainda pendente**.
- `decision_as_of` final, Jupiter live enrichment, hazard provider e forward outcomes ainda não estão ligados no unified smoke.
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

## Regra de wallet

**Não existe whitelist de “wallets boas” no caminho do radar.**

O mercado cria o episódio. Depois analisamos as wallets realmente presentes usando somente histórico já resolvido antes do T0 atual.

- wallet desconhecida não é ruim;
- wallet historicamente forte não recebe passe livre;
- missing history permanece missing;
- episódio atual não entra como histórico passado;
- outcome conhecido só depois de T0 não pode contaminar T0;
- `Copyability Score` antigo não pode ser filtro oculto.

## Core ativo — manter enxuto

Prioridade:

1. market movement / lifecycle;
2. order flow / microstructure;
3. liquidity / execution / tradability;
4. token hazard / manipulation risk;
5. dynamic wallet intelligence;
6. regime simples somente se provar valor incremental.

Deferred/frozen: Social/X, Telegram/NLP, graph avançado, whitelist/ranking sofisticado de wallets, ML complexo, dashboard cosmético, expansão ampla para outras DEXs, novas famílias de exit e live trading.

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

Nenhum threshold foi ajustado por P&L.

## Causal clocks e stores

`src/market_observation_store.py` separa `chain_time` de `observed_at`, persiste source/venue/wallet/transaction identity e missing price/notional explicitamente.

Replay idêntico posterior preserva o primeiro `observed_at`; backdating e mutação real são rejeitados.

`src/market_opportunity_episode_store.py` deduplica raw hits em episódios: mesmo run+token dentro da janela de 60s reutiliza episode. `decision_as_of` é imutável depois do freeze e **não é congelado pelo radar**.

Lifecycle em unified mode tem semântica venue-aware:

- Pump bonding `CreateEvent` = token birth para `fresh_market_burst` v1;
- PumpSwap `CreatePoolEvent` = pool/venue lifecycle, não token birth;
- PumpSwap pool creation não pode rejuvenescer um token migrado/antigo.

## Evidência live confirmada

### Pump bonding smoke

`pump-smoke-20260903-01`, 120.2s:

- 3476 notifications;
- 3688 decoded events;
- 3600 persisted;
- 223 unique tokens;
- 1984 unique wallets.

Decisão: **NATIVE PUMP ACQUISITION PASS**.

### Pump -> radar -> episode smoke

`market-radar-smoke-20260903-03`, 120s:

- 2037 eligible/persisted trades;
- 156 evaluated tokens;
- 738 raw radar hits;
- 707 continuation hits = 95.8%;
- 31 unique episodes;
- 29 unique hit tokens;
- 24 acceleration / 7 fresh episode openings;
- 12 upward / 12 mixed / 7 downward openings.

Decisão: **PUMP -> RADAR -> OPPORTUNITY EPISODE PASS**.

Conclusão operacional: enrichment caro deve ser **episode-scoped**, nunca raw-hit-scoped.

### PumpSwap smoke

`pumpswap-smoke-20260903-01`, 120.8s:

- 749 notifications;
- 837 decoded/persisted trades: 472 BUY / 365 SELL;
- 150 unique pools;
- 737 unique wallets;
- unresolved trades: 0;
- resolution: 100%;
- hydration attempts/successes: 92/92;
- hydration failures: 0;
- budget skips: 0.

Decisão: **NATIVE PUMPSWAP ACQUISITION + CAUSAL POOL RESOLUTION PASS**.

Capacity finding: 92 network hydrations em ~2min tornam um limite total fixo de 100 inadequado para multi-hora.

## PumpSwap identity reuse

`src/pumpswap_pool_store.py` + `src/pumpswap_reusable_resolver.py` agora permitem reutilizar `pool -> base_mint/quote_mint` aprendido em runs anteriores **somente se já era conhecido até o `as_of` atual**.

Regras:

- identidade futura continua invisível;
- primeiro `observed_at` causal é preservado;
- conflito histórico de identidade é erro visível;
- network hydration só ocorre depois de cache/current-run/historical-store miss.

Objetivo: reduzir chamadas `getAccountInfo` sem sacrificar causalidade.

## Unified market pipeline — implementado, live pendente

Design freeze:

`docs/unified-market-enrichment-v1-design-2026-09-03.md`

Componentes novos:

- `src/pumpswap_radar_bridge.py`;
- `src/pumpswap_reusable_resolver.py`;
- `src/opportunity_enrichment_store.py`;
- `src/opportunity_episode_enrichment.py`;
- `unified_market_enrichment_smoke.py`.

Pipeline atual:

```text
Pump + PumpSwap streams
-> same acquisition run / normalized market store
-> venue-aware radar bridges
-> shared Opportunity Episode store
-> exactly-once episode enrichment admission
-> shared flow Core + dynamic wallet evidence
```

Enrichment admission é `UNIQUE(run, episode)`, então continuation hits e replays não duplicam trabalho caro.

O bundle local atual:

- agrega flow causal de Pump e PumpSwap para o mesmo token/run;
- inclui wallets realmente presentes na janela atual;
- aceita quotes causais quando fornecidos;
- mantém token hazard como `not_integrated` até existir provider causal;
- não cria score ou decisão.

**O unified smoke atual não chama Jupiter nem risk provider e não congela `decision_as_of`.** Ele valida somente coexistência dos streams, shared radar/store, episode admission, wallet/flow bundle, hydration reuse e backpressure básico.

## Próximo gate obrigatório

Executar um short live smoke do unified pipeline. PASS exige, no mínimo:

- Pump e PumpSwap coexistirem sem crash;
- persistência dos dois sources;
- episodes de mercado abrirem de forma idempotente;
- enrichment admitted == novos episodes admitidos;
- flow/wallet bundles gerados;
- PumpSwap pool reuse/hydration telemetria explícita;
- ausência de fake fresh-token lifecycle por PumpSwap;
- nenhuma decisão/ordem/live.

Depois de PASS:

1. adicionar Jupiter execution enrichment limitado a new episode;
2. adicionar interface/provider mínimo de hazard com failure/missingness explícitos;
3. ligar historical wallet outcomes resolvidos;
4. definir bounded concurrency/timeouts/admission quando providers saturarem;
5. congelar `decision_as_of` no tempo real final das tentativas obrigatórias;
6. short true E2E smoke;
7. congelar protocolo runnable;
8. somente então primeira coleta de 12h.

## Avaliação econômica futura

Outcomes inicialmente separados em +5m / +15m / +60m, com semântica executável/route-aware quando possível. Não substituir silenciosamente quote/fill ausente por candle posterior.

Ablations mínimas devem perguntar se cada família acrescenta valor incremental: movement, flow, execution, wallet, risk e combinações pequenas. Features que não acrescentarem valor OOS devem ser removidas.

Métricas precisam incluir pelo menos mean/median, win rate, profit factor, drawdown, coverage, token/cluster concentration e contribuição dos maiores winners.

## Shadow / live

- acquisition causal: validada para Pump e PumpSwap separadamente;
- shared unified acquisition/enrichment: código pronto para short smoke;
- economic edge market-first: não estabelecido;
- executable fill/landing: não validado;
- shadow executável: não liberado;
- live: não liberado.
