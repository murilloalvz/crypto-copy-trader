# Crypto Copy Trader — Project Context

Este arquivo é o **source of truth operacional e científico** do projeto. Ele registra somente o estado consolidado necessário para continuar o trabalho sem reabrir decisões já encerradas. Histórico detalhado permanece nos documentos em `docs/`.

## Estado atual

- Repositório: `murilloalvz/crypto-copy-trader`.
- Branch de pesquisa principal: `feat/exit-engine-v1`.
- Modo: **PAPER / RESEARCH / READ ONLY**.
- Nenhum fluxo liberado assina, envia ou executa transações reais.
- Persistência principal: SQLite via `DATABASE_PATH` (padrão `data/copytrader.db`).
- Tese ativa: **market-first Solana Opportunity Intelligence / Opportunity Engine**.
- Wallet Forward v2 está encerrado com **OUTCOME D — TOO LITTLE ECONOMIC SAMPLE**.
- Wallet Forward Run 3 **não deve ser iniciado**.
- O protocolo wallet-triggered `Causal Opportunity Acquisition v1` foi **SUPERSEDED BEFORE RUN**.
- Market Opportunity Radar v1.1 transaction-aware: implementado, testado e live-smoke aprovado.
- Native Pump bonding stream: implementado, testado e live-smoke aprovado.
- Pump -> Radar -> Opportunity Episode: implementado, testado e live-smoke aprovado.
- Opportunity Wallet Intelligence v1: contrato causal implementado/testado; integração live end-to-end ainda pendente.
- Native PumpSwap adapter + causal `pool -> base_mint` resolution: implementado, testado e **live-smoke aprovado**.
- Última suíte executável confirmada antes do smoke PumpSwap: **534 testes, zero falhas**, com `compileall` aprovado.
- Próximo gate: **unified Pump + PumpSwap market pipeline -> episode-scoped bounded enrichment -> short E2E smoke**.
- **Não iniciar 12h ainda.**

## Regra central de validação

```text
IMPLEMENTADO
-> TESTADO
-> VALIDADO OPERACIONALMENTE
-> EVIDÊNCIA ECONÔMICA
-> SHADOW EXECUTÁVEL
-> LIVE CANARY
```

Código funcionando não prova edge. Quote não prova fill. Backtest positivo não libera live. Nenhuma feature, wallet, score ou detector é promovido sem causalidade, cobertura, missingness, dependência, custos e validação forward adequados.

## Tese ativa

O projeto deixou de ser um CopyTrader estrito.

Arquitetura alvo:

```text
market changes state
-> radar detects causally
-> opportunity episode
-> flow / microstructure
-> liquidity / execution
-> token hazard / risk
-> wallets actually present in the episode
-> optional regime context
-> freeze decision_as_of
-> forward executable outcomes
```

North star:

> identificar movimentos precoces cujo resultado forward, líquido de custos e com executabilidade realista, permaneça favorável fora da amostra.

### Regra de wallet

**Não existe whitelist de “wallets boas” no caminho do radar.**

Wallets são descobertas dinamicamente dentro da oportunidade atual. A pergunta é se as wallets presentes demonstravam competência com base somente em histórico que já estava resolvido antes daquele T0.

Regras:

- wallet desconhecida continua válida;
- wallet historicamente forte não recebe passe livre;
- wallet sem histórico não invalida episódio;
- episódio atual nunca entra como histórico passado;
- outcome que só ficou conhecido depois de T0 não pode ser usado;
- o antigo `Copyability Score` não pode ser filtro oculto do radar.

## Core de pesquisa — manter enxuto

Prioridade ativa:

1. **market movement / lifecycle**;
2. **order flow / microstructure**;
3. **liquidity / execution / tradability**;
4. **token hazard / manipulation risk**;
5. **dynamic wallet intelligence**;
6. regime simples somente se houver cobertura e valor incremental.

### Deferred / frozen por enquanto

Não gastar desenvolvimento agora com:

- Social/X sentiment ou influencer monitoring;
- Telegram/NLP/LLM narrative analysis;
- graph intelligence avançada;
- whitelist/ranking sofisticado de wallets;
- ML complexo / deep learning;
- dashboard cosmético;
- expansão ampla para Raydium/Orca/Meteora;
- novas famílias de exit antes de provar edge de entrada/qualidade;
- live trading.

Código histórico útil não precisa ser apagado; deve permanecer claramente fora do caminho ativo.

## Wallet Forward v2 — histórico encerrado

Runs canônicas:

- Run 1: `wallet-forward-1788360461-8a3986f9`, ~10h, 15 ações, 4 BUYs enrolled;
- Run 2: `wallet-forward-1788400735-5cbe70af`, ~10h, 3 SELLs, 0 BUY enrolled.

Combinadas, ~20h produziram somente quatro BUYs econômicos, concentrados.

Classificação pré-registrada:

**OUTCOME D — TOO LITTLE ECONOMIC SAMPLE**.

Consequências:

- edge wallet-only não estabelecido;
- não retunar coorte/delays pelo P&L dessas runs;
- não iniciar Run 3;
- aquisição market-first substitui wallet-first.

Documento principal:

`docs/wallet-forward-v2-run1-run2-final-decision-2026-09-03.md`

## Opportunity Snapshot Core

`src/opportunity_snapshot_core.py`

Contrato dual-clock:

- `chain_time/event_time`: quando o mercado aconteceu;
- `observed_at`: quando o bot ficou sabendo;
- T0 só usa informação com `observed_at <= decision_as_of`;
- missingness não é imputada;
- quote freshness fica explícita;
- `decision_as_of` deve incluir o tempo real gasto para obter as features necessárias.

O Core não possui BUY decision automático.

## Market Opportunity Radar v1.1 — transaction-aware

Arquivos/documentos principais:

- `src/market_opportunity_radar.py`;
- `docs/market-opportunity-radar-v1-protocol-2026-09-03.md`;
- `docs/market-opportunity-radar-v1-design-2026-09-03.md`;
- `docs/market-opportunity-radar-v1-1-transaction-awareness-amendment-2026-09-03.md`.

Versão:

`market_opportunity_radar_v1_1_tx_aware`

Established market acquisition mechanics:

- fast window = 30s;
- baseline horizon = 300s;
- baseline = 270s anteriores;
- >=6 eventos fast;
- >=4 wallets únicas conhecidas;
- >=3 eventos baseline;
- aceleração >=3x;
- quando transaction identity possui 100% de cobertura, >=4 transações únicas fast.

Fresh market:

- market age causal <=120s;
- >=6 eventos/30s;
- >=4 wallets únicas conhecidas;
- quando transaction identity possui 100% de cobertura, >=4 transações únicas fast.

Esses thresholds são **acquisition/integrity mechanics**, não regras de trading. Não foram ajustados por P&L.

Direction (`upward_pressure`, `downward_pressure`, `mixed_pressure`) é descritiva.

### Transaction-awareness

Raw event count, wallet breadth e transaction breadth são separados.

Uma transação que emite vários eventos não pode ser confundida com várias transações independentes quando identity coverage é completa.

## Market observation / episode stores

`src/market_observation_store.py`

Persiste por acquisition run:

- source;
- side;
- token;
- `chain_time`;
- `observed_at`;
- wallet;
- venue;
- price/notional quando disponíveis;
- `transaction_key` quando disponível.

Replay semantics:

- primeira observação preserva first-seen `observed_at`;
- replay idêntico posterior é idempotente;
- replay que tenta backdatear disponibilidade é rejeitado;
- mutação real continua conflito visível.

Incidente fechado:

`docs/market-radar-replay-timestamp-incident-2026-09-03.md`

`src/market_opportunity_episode_store.py`

- episódio não exige tracked wallet;
- mesmo token + run em <60s reutiliza episode;
- exatamente +60s pode abrir novo episode;
- raw triggers permanecem persistidos;
- runs não compartilham episodes;
- `decision_as_of` é imutável depois do freeze;
- radar bridge não congela `decision_as_of` antes do enrichment.

## Opportunity Wallet Intelligence v1

Arquivos:

- `src/opportunity_wallet_intelligence.py`;
- `tests/test_opportunity_wallet_intelligence.py`;
- `docs/opportunity-wallet-intelligence-v1-design-2026-09-03.md`.

Fluxo:

`market episode -> wallets presentes -> causal resolved history -> wallet evidence`

Features descritivas possíveis:

- ação atual BUY/SELL/repetição;
- participação de notional quando coberta;
- episódios passados já resolvidos;
- diversidade histórica de tokens;
- histórico anterior no mesmo token;
- positive-outcome share;
- retorno médio/mediano quando coberto;
- holding time quando coberto;
- explicit missingness / small sample flags.

Não existe `wallet_score`, `passed`, `recommended` ou whitelist no contrato ativo.

## Native Pump bonding acquisition — LIVE PASS

Programa:

`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`

Pipeline:

`Solana logsSubscribe -> Pump TradeEvent/CreateEvent -> normalized market observations -> SQLite`

Smoke:

`pump-smoke-20260903-01`

Resultado:

```text
elapsed=120.2s
notifications=3476
decoded_events=3688
persisted=3600
unique_tokens=223
unique_wallets=1984
```

Decisão:

**NATIVE PUMP ACQUISITION PLUMBING: LIVE PASS.**

Isso valida aquisição, não edge.

## Pump -> Radar -> Opportunity Episode — LIVE PASS

Run canônica pós-fix:

`market-radar-smoke-20260903-03`

Resumo:

```text
elapsed=120.0s
notifications=2034
decoded_trades=2111
lifecycle_events=27
sol_eligible=2037
persisted=2037
evaluated_tokens=156
raw_radar_hits=738
continuation_hits=707
continuation_share=95.8%
unique_hit_tokens=29
unique_episodes=31
repeated_episode_tokens=2
opened_trigger_kinds={'activity_acceleration': 24, 'fresh_market_burst': 7}
opened_directions={'downward_pressure': 7, 'upward_pressure': 12, 'mixed_pressure': 12}
```

Interpretação:

- 738 hits não são 738 oportunidades;
- 707 eram continuações;
- enrichment caro deve ser **episode-scoped**, nunca raw-hit-scoped;
- 31 episodes cobriram 29 tokens;
- direction permaneceu diversa;
- nenhum threshold foi retunado.

Documento:

`docs/market-radar-live-smoke-2026-09-03-v2.md`

Decisão:

**PUMP BONDING -> RADAR -> OPPORTUNITY EPISODE: LIVE PASS.**

## Native PumpSwap acquisition — LIVE PASS

Programa:

`pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`

Arquivos:

- `src/pumpswap_stream.py`;
- `src/pumpswap_pool_store.py`;
- `tests/test_pumpswap_stream.py`;
- `tests/test_pumpswap_pool_store.py`;
- `pumpswap_market_stream_smoke.py`;
- `docs/pumpswap-native-stream-v1-design-2026-09-03.md`;
- `docs/pumpswap-native-stream-live-smoke-2026-09-03.md`.

O adapter não inventa token identity a partir de `BuyEvent`/`SellEvent`.

Resolução causal:

```text
trade event -> pool
-> mapping já conhecido via CreatePoolEvent/store/cache
OR
-> getAccountInfo(pool) -> decode PumpSwap Pool -> base_mint/quote_mint
```

Se trade chega em T1 e a identidade do pool só é descoberta em T2, a disponibilidade final não pode anteceder T2.

Smoke real:

`pumpswap-smoke-20260903-01`

Resumo:

```text
elapsed=120.8s
notifications=749
decoded_trades=837
buys=472
sells=365
create_pools=0
persisted_trades=837
duplicate_or_replayed=0
unresolved_trades=0
resolution_pct=100.0%
persisted_lifecycle=0
unique_pools=150
unique_wallets=737
pool_cache_hits=685
pool_store_hits=60
hydration_attempts=92
hydration_successes=92
hydration_failures=0
actual_network_hydrations=92
hydration_budget_skips=0
negative_cache_skips=0
```

Decisão:

**NATIVE PUMPSWAP ACQUISITION + CAUSAL POOL RESOLUTION: LIVE PASS.**

### Capacity finding

92 network hydrations em ~120s mostram que um `max_hydrations=100` fixo é apropriado para smoke curto, mas **não pode virar orçamento total de uma run multi-hora**.

Antes da 12h, a aquisição longa deve possuir:

- persistent/cross-run reuse de pool identity já causalmente conhecida;
- rate/throughput budget explícito;
- bounded concurrency;
- timeout;
- negative-cache TTL;
- hydration latency/failure/coverage telemetry.

Isso é capacidade operacional, não retuning econômico.

## Fonte de dados ativa

Preferência:

1. Solana on-chain stream como fonte canônica;
2. Pump bonding + PumpSwap como primeiros adapters;
3. Jupiter como execution proxy;
4. wallet intelligence somente depois que o mercado criou episódio;
5. Birdeye/PumpPortal apenas como enrichment/cross-check se trouxerem valor/custo justificável.

Não depender de scraping da UI Pump.fun.

## Próximos gates — ordem obrigatória

Ainda **não iniciar 12h**.

### Gate A — unified market acquisition

Unificar Pump bonding + PumpSwap no mesmo acquisition run / normalized market surface.

Requisitos:

- venue preservado;
- mesmo token pode acumular evidência entre venues sem duplicação semântica;
- transaction identity preservada;
- lifecycle/migration observável quando disponível;
- pool-resolution capacity bounded.

### Gate B — episode-scoped enrichment admission

Enrichment caro roda somente em **new opportunity episode**, nunca em raw radar hit.

Precisamos de:

- bounded concurrency;
- timeout por provider/família;
- explicit provider failure/missingness;
- deterministic/outcome-blind admission quando capacidade for insuficiente;
- nenhuma seleção baseada em performance futura.

### Gate C — Minimal Opportunity Evidence Bundle

Para cada episódio admitido, congelar o mínimo útil:

1. movement/lifecycle;
2. flow/microstructure;
3. execution/liquidity via Jupiter;
4. token hazard/risk mínimo;
5. dynamic wallet evidence;
6. regime apenas se barato e causal.

Depois que as tentativas obrigatórias terminarem:

`decision_as_of = momento real em que o snapshot estava disponível`.

### Gate D — short end-to-end smoke

Validar ao vivo:

`Pump/PumpSwap -> Radar -> Episode -> Enrichment -> decision_as_of -> scheduled forward outcome capture`

Auditar:

- latency;
- missingness;
- provider failures;
- throughput/backpressure;
- episode admission rate;
- Jupiter coverage;
- wallet evidence coverage;
- finality quando aplicável.

### Gate E — freeze runnable protocol

Somente após E2E short smoke aprovado:

- congelar thresholds e feature definitions;
- congelar fixed notional/execution-proxy semantics;
- congelar horizons forward;
- congelar admission/budget policy;
- documentar failure semantics.

### Gate F — first long acquisition

Só então iniciar a primeira janela de 12h.

## Primeira coleta econômica — objetivo

A primeira coleta longa deve responder antes de qualquer otimização:

> episódios detectados pelo radar possuem comportamento forward economicamente capturável depois de custos e constraints de execução?

Não procurar inicialmente “qual filtro deixa o backtest verde”.

Outcomes candidatos já planejados:

- +5m;
- +15m;
- +60m.

Sempre usar execution-proxy semantics consistentes; não substituir silenciosamente por candle ou preço posterior conveniente.

## DATA-READY target

Antes de inferência econômica séria:

- zero look-ahead;
- >=30 opportunity episodes;
- >=15 unique tokens;
- largest token share <=20%;
- diversidade real de participantes;
- >=90% episodes com timing/identity e pelo menos um execution proxy utilizável;
- provider failures/missingness explícitos;
- zero whitelist de wallet no trigger.

Os smokes atuais já provam que volume/diversidade de aquisição não são mais o gargalo principal. Ainda não são DATA-READY econômicos porque faltam enrichment completo, execution proxy e outcomes forward.

## Avaliação futura

Primeiro avaliar distribuição inteira dos episódios.

Depois ablations pequenas:

- movement only;
- flow only;
- execution only;
- risk only;
- wallet evidence only;
- flow + execution;
- flow + risk;
- flow + wallet;
- flow + execution + risk;
- Core completo.

Se uma família não acrescentar valor incremental OOS, ela deve ser removida/congelada.

Modelos iniciais, somente depois de dataset suficiente:

- baseline simples;
- logistic/linear regularized;
- small tree/gradient boosting comparison.

Não iniciar deep learning antes de existir uma razão empírica.

## Surf / exit research

O objetivo final inclui **surfar bem movimentos bons**, mas otimizar saída antes de provar qualidade de entrada cria espaço enorme para overfitting.

Ordem correta:

1. provar que os episódios/filters possuem edge capturável;
2. medir MFE/MAE/time-to-peak e deterioration de flow/liquidity;
3. comparar exits já existentes;
4. somente então testar exit adaptativo baseado em deterioração do estado, se houver hipótese clara.

Exits históricos atuais já são suficientes como baselines; não criar novas famílias agora.

## Shadow / live

- causal forward infrastructure: validada;
- quantity-aware accounting: validado;
- wallet-only edge: não estabelecido;
- Native Pump acquisition: live PASS;
- Market Radar: live PASS;
- Radar -> episode accounting: live PASS;
- replay timestamp incident: RESOLVED;
- Native PumpSwap acquisition/pool resolution: live PASS;
- Opportunity Wallet Intelligence: unit-tested, E2E live pendente;
- unified Pump + PumpSwap radar: pendente;
- episode-scoped Jupiter/risk/wallet enrichment: pendente;
- forward economic outcomes da arquitetura market-first: pendentes;
- executable landing/fill: não validado;
- shadow executável: não liberado;
- live: não liberado.

O projeto continua explicitamente **PAPER / RESEARCH / READ ONLY**.
