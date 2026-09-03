# Crypto Copy Trader — Project Context

Este arquivo registra o estado técnico consolidado do projeto. Ideias discutidas fora do código são hipóteses até serem confirmadas por implementação, testes e evidência reproduzível.

## Estado atual

- Branch de pesquisa principal: `feat/exit-engine-v1`.
- Modo: **PAPER / RESEARCH / READ ONLY**.
- Nenhum fluxo liberado assina, envia ou executa transações reais.
- Persistência principal: SQLite via `DATABASE_PATH` (padrão `data/copytrader.db`).
- Wallet Forward v2 encerrou a replicação Run 1 × Run 2.
- Classificação final pré-registrada: **OUTCOME D — TOO LITTLE ECONOMIC SAMPLE**.
- Wallet Forward v2 Run 3 **não deve ser iniciado**.
- O protocolo wallet-triggered `Causal Opportunity Acquisition v1` foi **SUPERSEDED BEFORE RUN**.
- Gate ativo: **Market Opportunity Radar v1.1 transaction-aware + Opportunity Wallet Intelligence v1 + native Pump market acquisition**.
- Native Pump bonding-curve acquisition teve **live smoke operacional aprovado** na máquina local real em 2026-09-03.
- `Pump -> Market Radar -> Opportunity Episode` teve **live smoke operacional aprovado** em `market-radar-smoke-20260903-03`.
- O incidente de replay timestamp da run `market-radar-smoke-20260903-02` está **RESOLVED**; a run permanece FAILED/PARTIAL como evidência preservada.
- Última suíte executável confirmada: **523 testes, zero falhas**, com `compileall` aprovado.
- Próximo bloqueador técnico: **PumpSwap adapter + episode-scoped enrichment end-to-end**.

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

## Tese atual

O projeto evoluiu de um CopyTrader estrito para um **Solana Opportunity Intelligence / Opportunity Engine**.

Arquitetura alvo:

`mercado muda de estado -> radar detecta -> opportunity episode -> identifica as wallets realmente presentes -> cruza wallet evidence + flow + execução + risco + regime -> decision_as_of -> outcome forward`

### Regra de wallet

**Não existe whitelist de “wallets boas” no caminho do radar.**

Wallets são descobertas dinamicamente dentro de cada oportunidade. O bot deve avaliar se aquelas wallets demonstravam comportamento competente com base apenas em histórico já resolvido antes do T0 atual.

Uma wallet desconhecida continua válida. Uma wallet historicamente forte não recebe passe livre. Uma wallet sem histórico não invalida o episódio.

O antigo `Copyability Score` permanece infraestrutura histórica de Discovery e não pode ser usado como filtro oculto de admissão do Market Opportunity Radar.

Pump.fun/PumpSwap é o primeiro laboratório de alta atividade, não um pilar obrigatório. A interface permanece venue-agnostic para Raydium, Meteora e outros venues.

North star:

> identificar movimentos precoces cujo resultado forward, ajustado por risco, custos e executabilidade realista, permaneça favorável fora da amostra.

## Evidência externa que orienta o desenho

Prioridade atual:

1. execução / liquidez / tradability;
2. order flow / microestrutura;
3. token-risk / hazard rejection;
4. wallet intelligence + independência;
5. market/network regime;
6. preço/momentum/reversal;
7. lifecycle/launch intelligence;
8. graph/relationship intelligence;
9. social/attention apenas se provar valor incremental.

Modelos simples continuam candidatos fortes. Complexidade/ML não é objetivo por si só.

Documentos principais:

- `docs/research-signal-universe-v1-2026-09-02.md`
- `docs/research-evidence-registry-v1-2026-09-02.md`
- `docs/post-run2-evidence-decision-framework-2026-09-02.md`

## Wallet Forward v2 — encerrado

Runtime validado:

`wallet_forward_runtime_v5_enrollment_followup_rotating_poll_confirmed_commitment`

Coorte congelada:

1. `7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH`
2. `3tc4BVAdzjr1JpeZu6NAjLHyp4kK3iic7TexMBYGJ4Xk`
3. `2RssnB7hcrnBEx55hXMKT1E7gN27g9ecQFbbCc5Zjajq`

### Run 1

`wallet-forward-1788360461-8a3986f9`

- COMPLETED, ~10h;
- 15 ações: 9 BUY / 6 SELL;
- 4 BUYs enrolled;
- 3/4 enrolled BUYs no mesmo wallet×token cluster;
- finality 15/15;
- BUY quote readiness 45/45;
- causal boundary clean.

Quantity-aware replay descritivo:

- +0s mean net: -28.76%;
- +15s: -30.37%;
- +60s: -25.36%;
- +30s/+120s: censurados sem saída causal adequada.

Esses valores não provam que a estratégia perde ~30%; a amostra é pequena e altamente dependente.

### Run 2

`wallet-forward-1788400735-5cbe70af`

- COMPLETED, ~10h;
- 3 ações: 0 BUY / 3 SELL;
- 0 BUYs enrolled;
- 0 RPC failures;
- finality 3/3 finalized success.

Run 2 não possui amostra econômica.

### Decisão final

As duas runs somam ~20h, mas apenas quatro BUYs econômicos, todos no Run 1.

**OUTCOME D — TOO LITTLE ECONOMIC SAMPLE**.

Consequências:

- edge wallet-only não estabelecido;
- não retunar coorte/delays com base nesse P&L;
- não iniciar Run 3;
- não promover shadow/live;
- redesenhar aquisição antes de coletar mais evidência.

Documento:

`docs/wallet-forward-v2-run1-run2-final-decision-2026-09-03.md`

## Fixes pós-Run2

- replay resolve quote pela identidade exata de `quote_key`;
- SELL quote lineage bloqueia reutilização cross-run;
- logs BUY/SELL são side-aware;
- quantity-aware accounting permanece obrigatório.

## Opportunity Snapshot Core

`src/opportunity_snapshot_core.py`

Contrato causal dual-clock:

- `chain_time/event_time`: quando o mercado aconteceu;
- `observed_at`: quando o bot ficou sabendo;
- market window exige tempo de mercado correto;
- T0 exige `observed_at <= decision_as_of`;
- missingness não é imputada;
- quote freshness fica explícita;
- `decision_as_of` inclui o tempo gasto para obter features.

Nenhum score ou BUY decision automático existe no Core.

## Market Opportunity Radar v1.1 — transaction-aware

Protocolo base:

`docs/market-opportunity-radar-v1-protocol-2026-09-03.md`

Design:

`docs/market-opportunity-radar-v1-design-2026-09-03.md`

Amendment pós-smoke, pré-econômico:

`docs/market-opportunity-radar-v1-1-transaction-awareness-amendment-2026-09-03.md`

Antes:

`tracked wallet BUY -> episode`

Agora:

`market activity changes state -> episode`

### Detector

`src/market_opportunity_radar.py`

Versão atual:

`market_opportunity_radar_v1_1_tx_aware`

Established market:

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

Esses thresholds são mecânica de aquisição/integridade, não regra de trading e não foram ajustados com P&L.

Direction (`upward_pressure`, `downward_pressure`, `mixed_pressure`) é descritiva. Grande alta de preço não é exigida para disparar o radar.

### Transaction-awareness

O live smoke mostrou transações com múltiplos `TradeEvent`s, inclusive assinaturas com quatro eventos.

Por isso `MarketTradeObservation` agora pode preservar `transaction_key`. No adapter Pump a chave é a assinatura Solana.

O radar separa:

- raw event count;
- unique wallet breadth;
- unique transaction breadth;
- transaction-identity coverage.

Raw events continuam persistidos; a proteção existe apenas para impedir que um único tx/bundle seja confundido com várias transações independentes.

Sources legadas/provider sem transaction identity continuam utilizáveis com missingness explícita; ausência de identidade não é silenciosamente tratada como zero atividade independente.

### Market observation store

`src/market_observation_store.py`

Persiste, por acquisition run, raw trades/lifecycle com source, side, token, `chain_time`, `observed_at`, wallet, notional, preço, venue e `transaction_key` quando disponíveis.

O store é idempotente, run-scoped e suporta leitura causal por `as_of` e market-time window.

A migração de SQLite adiciona `transaction_key` de forma compatível com bancos locais já existentes. Linhas legadas permanecem com `NULL`, sem apagar ou reclassificar evidência histórica.

Replay semantics corrigidas e regression-tested:

- primeira observação preserva o causal first-seen `observed_at`;
- replay idêntico posterior retorna duplicate sem regravar o relógio;
- replay que tentaria backdatear disponibilidade é rejeitado;
- mutação real de payload continua conflito visível.

Documento do incidente:

`docs/market-radar-replay-timestamp-incident-2026-09-03.md`

### Market opportunity episodes

`src/market_opportunity_episode_store.py`

- trigger de mercado não exige wallet previamente rastreada;
- mesmo token + run em <60s reutiliza episode;
- exatamente +60s abre novo episode;
- runs diferentes nunca compartilham episode;
- raw triggers permanecem persistidos;
- `decision_as_of` é imutável;
- loader causal esconde triggers futuros.

## Opportunity Wallet Intelligence v1

Arquivos:

- `src/opportunity_wallet_intelligence.py`
- `tests/test_opportunity_wallet_intelligence.py`
- `docs/opportunity-wallet-intelligence-v1-design-2026-09-03.md`

Fluxo obrigatório:

`market episode -> wallets presentes -> histórico causal já resolvido -> wallet evidence`

Para cada participante do episódio, a camada pode descrever:

- BUY/SELL/repetição atual;
- participação de notional quando cobertura é completa;
- quantidade de episódios passados já resolvidos;
- diversidade de tokens no histórico;
- histórico anterior no mesmo token;
- positive-outcome share;
- retorno médio/mediano quando coberto;
- holding time mediano quando coberto;
- flags de missingness e amostra pequena.

Regras anti-leakage:

- resultado histórico só entra se já estava observado antes do `decision_as_of` atual;
- episódio atual nunca entra como “histórico passado”;
- evento atual observado depois de T0 é excluído;
- histórico não resolvido permanece missing, não vira loss;
- notional incompleto não gera concentração falsa.

O contrato não possui `wallet_score`, `passed`, `recommended`, whitelist ou BUY decision.

## Native Pump Market Stream v1

Arquivos:

- `src/pump_bonding_stream.py`
- `tests/test_pump_bonding_stream.py`
- `tests/test_pump_lifecycle_capture.py`
- `pump_market_stream_smoke.py`
- `docs/pump-market-stream-v1-design-2026-09-03.md`
- `docs/pump-market-stream-v1-smoke-2026-09-03.md`

Primeiro adapter real-time implementado:

`Solana logsSubscribe -> Pump bonding-curve events -> MarketTradeObservation/MarketLifecycleObservation -> SQLite`

Fonte canônica:

- Pump program `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`;
- filtro `logsSubscribe` por `mentions`;
- commitment explícito;
- Anchor TradeEvent discriminator `[189, 219, 127, 211, 78, 230, 97, 238]`;
- Anchor CreateEvent discriminator `[27, 114, 169, 77, 222, 235, 99, 118]`.

TradeEvent decoder usa somente o prefixo estável necessário:

- mint;
- `sol_amount`;
- `token_amount`;
- `is_buy`;
- user;
- timestamp.

CreateEvent decoder preserva o prefixo causal necessário para lifecycle:

- name/symbol/uri são atravessados como Borsh strings;
- mint;
- bonding curve;
- user;
- creator;
- timestamp.

Campos posteriores do evento são ignorados quando não necessários para o contrato causal atual.

Clocks:

- `chain_time` = timestamp emitido pelo Pump;
- `observed_at` = instante local em que o WebSocket entregou a notificação.

O adapter rejeita `observed_at < chain_time` e transações com erro. Persistência de trades usa chave idempotente por acquisition run:

`pump:<signature>:<event-index>`

Cada trade Pump agora também preserva `transaction_key=<signature>`.

Lifecycle usa chave:

`pump-create:<signature>:<event-index>`

O stream possui reconnect com backoff exponencial limitado, ping/pong e confirmação explícita da subscription.

### Missingness / quote assets

Pump passou a suportar quote assets além de SOL. O v1 não tenta adivinhar o `quote_mint` a partir do prefixo parcial. Por isso:

- só persiste TradeEvent com `sol_amount > 0`;
- USD notional fica missing;
- USD price fica missing;
- eventos não-SOL ficam unsupported em vez de serem classificados incorretamente.

### Live smoke operacional — PASS

Em 2026-09-03 o usuário executou na máquina local real:

```text
python pump_market_stream_smoke.py --run-key pump-smoke-20260903-01 --duration-seconds 120 --commitment confirmed
```

Resultado observado:

```text
elapsed=120.2s
notifications=3476
decoded_events=3688
persisted=3600
unique_tokens=223
unique_wallets=1984
```

Taxas descritivas aproximadas:

- 28.92 notifications/s;
- 30.68 decoded TradeEvents/s;
- 29.95 persisted observations/s;
- 1.86 unique tokens/s;
- 16.51 unique wallets/s;
- 97.61% decoded events persisted.

Os 88 decoded-but-not-persisted foram depois separados pelo smoke do radar em non-SOL-prefix versus replay/duplicate, sem inferência silenciosa.

Decisão operacional:

**NATIVE PUMP ACQUISITION PLUMBING: LIVE SMOKE PASS.**

Isso valida WebSocket, decoding, clocks e persistência sob atividade real. Não valida edge, rentabilidade, finality de cada assinatura, detector precision ou execução.

A escassez de raw acquisition candidates deixou de ser o gargalo imediato no Pump bonding curve. O novo problema de pesquisa é reduzir milhares de eventos para oportunidades independentes e economicamente relevantes sem introduzir selection/leakage bias.

### PumpSwap

PumpSwap usa programa e schemas próprios (`BuyEvent`, `SellEvent`, `CreatePoolEvent`). O adapter Pump bonding não pode ser reutilizado por inferência.

A documentação/IDL oficial atual mostra:

- programa `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`;
- `BuyEvent` e `SellEvent` carregam `pool` e `user`, mas não carregam diretamente `base_mint`;
- `CreatePoolEvent` carrega `base_mint`, `quote_mint` e `pool`;
- a conta `Pool` também carrega `base_mint` e `quote_mint`.

Consequência de arquitetura: o adapter PumpSwap precisa de resolução causal `pool -> base_mint`, usando CreatePoolEvent quando disponível e hidratação/cache de Pool account para pools pré-existentes. Não é aceitável inferir mint pelo evento de trade.

## Live Market Radar Bridge

Arquivos:

- `src/market_radar_bridge.py`
- `tests/test_market_radar_bridge.py`
- `tests/test_market_radar_tx_awareness.py`
- `tests/test_market_observation_transaction_identity.py`
- `market_radar_smoke.py`

Pipeline implementado/testado:

`Pump notification -> raw trade/lifecycle persistence -> causal 300s token state -> transaction-aware radar -> market opportunity episode`

Regras:

- cada token afetado numa notificação é avaliado uma vez;
- todos os raw events continuam persistidos;
- assinatura Solana preserva transaction breadth;
- um tx com vários eventos não pode sozinho satisfazer o gate quando identity coverage é completa;
- trigger id é determinístico e idempotente;
- `decision_as_of` **não é congelado pelo radar bridge**.

O freeze de `decision_as_of` permanece reservado à camada de enrichment, depois que as tentativas obrigatórias de execution/risk/regime/wallet evidence terminarem. O relógio final deve refletir quando a informação realmente ficou disponível.

### Live radar smoke — PASS

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
filtered_non_sol_prefix=74
duplicate_or_replayed_eligible=0
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

Interpretação operacional:

- 738 raw hits **não** são 738 oportunidades independentes;
- 707 eram continuações de episode já aberto;
- só 31 opportunity episodes independentes foram abertos;
- 31 episodes cobriram 29 tokens;
- os dois tokens repetidos abriram duas vezes cada na saída observada, então maior share de token = 2/31 ~= 6.5%;
- expensive enrichment deve ser **episode-scoped**, nunca raw-hit-scoped;
- direction permaneceu diversa: 12 upward, 12 mixed, 7 downward;
- nenhum threshold foi retunado.

Documento:

`docs/market-radar-live-smoke-2026-09-03-v2.md`

Decisão:

**PUMP BONDING STREAM -> MARKET RADAR -> OPPORTUNITY EPISODE: LIVE OPERATIONAL PASS.**

Isso ainda não mede edge ou profitability.

## Cruzamento das análises

O futuro snapshot/evidence bundle da oportunidade deve reunir no mesmo T0:

1. **market movement/lifecycle**;
2. **execution/liquidity** via Jupiter e superfícies causais;
3. **order flow/microstructure**;
4. **wallet intelligence das wallets realmente presentes**;
5. **token/hazard risk**;
6. **network/market regime**.

A hipótese é que as interações possam ser mais informativas do que qualquer família isolada, por exemplo:

`activity acceleration + broad independent buying + participantes com bom histórico resolvido + liquidez saudável + execução aceitável + hazard baixo`

Isso é hipótese de pesquisa, não regra de BUY. Ablations futuras devem provar valor incremental.

## Fonte de dados planejada

Preferência:

1. Solana on-chain stream como fonte canônica;
2. Pump bonding curve + PumpSwap como primeiros adapters;
3. Birdeye/PumpPortal como enrichment/cross-check quando custo permitir;
4. Jupiter como execution proxy;
5. wallet history/enrichment somente depois que o mercado criou o episódio.

Pump program IDs:

- Pump: `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`;
- PumpSwap: `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`.

Não depender de scraping da UI Pump.fun.

## Próximo gate operacional

Ainda **não iniciar 12h**.

Pump bonding stream + radar + episode accounting já passaram o short live gate. Ordem atual:

1. implementar/validar adapter PumpSwap separado com resolução causal `pool -> base_mint`;
2. definir scheduler de enrichment limitado a **new episode only** e com budgets explícitos de concorrência/timeout;
3. ligar `episode -> dynamic wallet intelligence -> Opportunity Core -> Jupiter/risk/regime`;
4. smoke end-to-end curto incluindo verdadeiro `decision_as_of`;
5. auditar provider/RPC cost, missingness, latency e finality quando aplicável;
6. congelar o protocolo runnable;
7. somente depois iniciar primeira janela de 12h.

Meta DATA-READY futura:

- zero look-ahead;
- >=30 opportunity episodes;
- >=15 tokens;
- diversidade real de participantes;
- largest token share <=20%;
- >=90% episodes com timing/identity e ao menos um execution proxy utilizável;
- zero uso de whitelist de wallet para criar/suprimir episódio.

O smoke `-03` já mostra que volume/diversidade de aquisição conseguem atingir numericamente >=30 episodes e >=15 tokens em uma janela curta, mas **não conta como DATA-READY econômico**, pois ainda faltam execution proxy, enrichment e outcomes forward preregistrados.

Passar o gate valida aquisição, não edge.

## Avaliação futura

Ablations mínimas:

- market movement only;
- wallet evidence only;
- execution only;
- flow only;
- market + wallet;
- market + flow;
- wallet + flow;
- market + wallet + execution;
- all Core families;
- risk/regime quando cobertura suportar comparação justa.

Usar avaliação separada no tempo e cluster-aware por token/wallet/transaction quando aplicável.

## Shadow / live

- causal forward infrastructure: validada;
- quantity-aware accounting: validado;
- wallet-only edge: não estabelecido;
- Market Opportunity Radar v1.1: implementado/testado e **live radar smoke aprovado**;
- Opportunity Wallet Intelligence: contrato causal implementado/testado, integração live-read-only ainda não validada end-to-end;
- Native Pump bonding stream: implementado/testado e **live smoke operacional aprovado**;
- Pump lifecycle CreateEvent capture: implementado/testado e observado em live radar smoke;
- stream -> radar -> episode bridge: implementado/testado e **live smoke aprovado**;
- replay timestamp incident: **RESOLVED / regression-tested / local re-smoke pass**;
- PumpSwap coverage: pendente;
- episode-scoped Jupiter/risk/regime enrichment: pendente;
- executable landing/fill: não validado;
- shadow executável: não liberado;
- live: não liberado.

O projeto continua explicitamente **PAPER / RESEARCH / READ ONLY**.
