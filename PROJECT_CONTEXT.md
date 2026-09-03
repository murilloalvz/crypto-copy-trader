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
- Gate ativo: **Market Opportunity Radar v1 + Opportunity Wallet Intelligence v1 + native Pump market acquisition**.
- Última suíte confirmada: **508 testes, zero falhas**, com `compileall` aprovado.

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

## Market Opportunity Radar v1

Protocolo ativo:

`docs/market-opportunity-radar-v1-protocol-2026-09-03.md`

Design:

`docs/market-opportunity-radar-v1-design-2026-09-03.md`

Antes:

`tracked wallet BUY -> episode`

Agora:

`market activity changes state -> episode`

### Detector v1

`src/market_opportunity_radar.py`

Established market:

- fast window = 30s;
- baseline horizon = 300s;
- baseline = 270s anteriores;
- >=6 eventos fast;
- >=4 wallets únicas conhecidas;
- >=3 eventos baseline;
- aceleração >=3x.

Fresh market:

- market age causal <=120s;
- >=6 eventos/30s;
- >=4 wallets únicas conhecidas.

Esses thresholds são mecânica de aquisição, não regra de trading.

Direction (`upward_pressure`, `downward_pressure`, `mixed_pressure`) é descritiva. Grande alta de preço não é exigida para disparar o radar.

### Market observation store

`src/market_observation_store.py`

Persiste, por acquisition run, raw trades/lifecycle com source, side, token, `chain_time`, `observed_at`, wallet, notional, preço e venue quando disponíveis.

O store é idempotente, run-scoped e suporta leitura causal por `as_of` e market-time window.

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
- `pump_market_stream_smoke.py`
- `docs/pump-market-stream-v1-design-2026-09-03.md`

Primeiro adapter real-time implementado:

`Solana logsSubscribe -> Pump bonding-curve TradeEvent -> MarketTradeObservation -> SQLite`

Fonte canônica:

- Pump program `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`;
- filtro `logsSubscribe` por `mentions`;
- commitment explícito;
- Anchor TradeEvent discriminator `[189, 219, 127, 211, 78, 230, 97, 238]`.

O decoder usa somente o prefixo estável necessário do evento oficial:

- mint;
- `sol_amount`;
- `token_amount`;
- `is_buy`;
- user;
- timestamp.

Clocks:

- `chain_time` = timestamp emitido pelo Pump;
- `observed_at` = instante local em que o WebSocket entregou a notificação.

O adapter rejeita `observed_at < chain_time` e transações com erro. Persistência usa chave idempotente por acquisition run:

`pump:<signature>:<event-index>`

O stream possui reconnect com backoff exponencial limitado, ping/pong e confirmação explícita da subscription.

### Missingness / quote assets

Pump passou a suportar quote assets além de SOL. O v1 não tenta adivinhar o `quote_mint` a partir do prefixo parcial. Por isso:

- só persiste TradeEvent com `sol_amount > 0`;
- USD notional fica missing;
- USD price fica missing;
- eventos não-SOL ficam unsupported em vez de serem classificados incorretamente.

### Smoke operacional

`pump_market_stream_smoke.py` é limitado deliberadamente a 1–900s.

Primeiro smoke recomendado: **120s, confirmed**.

O smoke mede apenas plumbing operacional: aceitação do WebSocket, quantidade de eventos decodificados/persistidos, tokens/wallets únicas e comportamento do RPC sob burst.

**Ainda não foi validado na máquina local real do usuário.** Portanto o adapter está implementado + testado, mas ainda não validado operacionalmente.

### PumpSwap

PumpSwap usa programa e schemas próprios (`BuyEvent`, `SellEvent`, `CreatePoolEvent`). O adapter Pump bonding não pode ser reutilizado por inferência. PumpSwap permanece próximo adapter a implementar/validar, incluindo mapeamento causal pool -> base mint.

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

Ordem atual:

1. rodar smoke nativo Pump de 120s na máquina local real;
2. validar websocket endpoint, clocks, dedup e volume/burst;
3. implementar/validar adapter PumpSwap separado;
4. ligar market stream -> radar -> episode;
5. ligar dynamic wallet intelligence -> Opportunity Core -> Jupiter/risk/regime;
6. smoke end-to-end curto;
7. somente depois congelar e iniciar primeira janela de 12h.

Meta DATA-READY futura:

- zero look-ahead;
- >=30 opportunity episodes;
- >=15 tokens;
- diversidade real de participantes;
- largest token share <=20%;
- >=90% episodes com timing/identity e ao menos um execution proxy utilizável;
- zero uso de whitelist de wallet para criar/suprimir episódio.

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

Usar avaliação separada no tempo e cluster-aware por token/wallet.

## Shadow / live

- causal forward infrastructure: validada;
- quantity-aware accounting: validado;
- wallet-only edge: não estabelecido;
- Market Opportunity Radar: núcleo implementado/testado, stream real ainda não validado end-to-end;
- Opportunity Wallet Intelligence: contrato causal implementado/testado, integração live-read-only ainda não validada;
- Native Pump bonding stream: implementado/testado, **smoke operacional pendente**;
- executable landing/fill: não validado;
- shadow executável: não liberado;
- live: não liberado.

O projeto continua explicitamente **PAPER / RESEARCH / READ ONLY**.
