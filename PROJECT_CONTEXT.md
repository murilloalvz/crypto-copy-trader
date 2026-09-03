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
- Próximo gate ativo: **Market Opportunity Radar v1**.
- Última suíte confirmada após o pivot: **491 testes, zero falhas**, com `compileall` aprovado.

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

`mercado começa a mudar de estado -> radar detecta causalmente -> opportunity episode -> execução + order flow + risco + wallet context + regime -> decision_as_of -> outcome forward`

Wallets continuam importantes, mas agora são **features / confirmação / contexto**, não a única porta de entrada da amostra.

Pump.fun/PumpSwap é o primeiro laboratório de alta atividade, não um pilar obrigatório. A interface do radar deve permanecer venue-agnostic para permitir Raydium, Meteora e outros venues depois.

North star:

> identificar movimentos precoces cujo resultado forward, ajustado por risco, custos e executabilidade realista, permaneça favorável fora da amostra.

## Evidência externa que orienta o desenho

A pesquisa registrada prioriza:

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

## Wallet Forward v2 — estado encerrado

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

Esses valores **não** provam que a estratégia perde ~30%; a amostra é pequena e altamente dependente.

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
- T0 exige disponibilidade `observed_at <= decision_as_of`;
- missingness não é imputada;
- quote freshness fica explícita;
- `decision_as_of` inclui o tempo gasto para obter features.

Nenhum score ou BUY decision automático existe no Core.

## Market Opportunity Radar v1

Protocolo ativo:

`docs/market-opportunity-radar-v1-protocol-2026-09-03.md`

Design:

`docs/market-opportunity-radar-v1-design-2026-09-03.md`

### Mudança principal

Antes:

`tracked wallet BUY -> episode`

Agora:

`market activity changes state -> episode`

Tracked wallet participation é apenas feature/contexto.

### Detector v1

`src/market_opportunity_radar.py`

Detector de aquisição simples, causal e auditável.

Established-market candidate:

- fast window = 30s;
- baseline horizon = 300s;
- segmento baseline = 270s anteriores, excluindo fast window;
- >=6 eventos no fast window;
- >=4 wallets únicas conhecidas;
- >=3 eventos baseline;
- aceleração de event-rate >=3x.

Fresh-market burst:

- market age causal <=120s;
- >=6 eventos/30s;
- >=4 wallets únicas conhecidas.

Esses thresholds são **mecânica de aquisição**, não regra de trading e não foram escolhidos como thresholds de P&L.

Direction (`upward_pressure`, `downward_pressure`, `mixed_pressure`) é descritiva. Grande alta de preço não é exigida para disparar o radar, evitando detectar apenas depois do pump.

### Market observation store

`src/market_observation_store.py`

Persiste por acquisition run:

- raw market trades;
- source provider;
- side;
- token;
- `chain_time`;
- `observed_at`;
- wallet quando disponível;
- notional/preço quando disponíveis;
- venue;
- lifecycle/market-start observations.

O store é idempotente, run-scoped e suporta leitura causal por `as_of` e janela de market time.

### Market opportunity episodes

`src/market_opportunity_episode_store.py`

- market trigger não exige tracked wallet;
- mesmo token + mesma run em <60s reutiliza episode;
- exatamente +60s abre novo episode;
- runs diferentes nunca compartilham episode;
- raw triggers permanecem persistidos;
- `decision_as_of` é imutável;
- loader causal esconde triggers não disponíveis no cutoff.

## Fonte de dados planejada

Preferência arquitetural:

1. **Solana on-chain stream** como fonte canônica;
2. Pump bonding-curve program + PumpSwap como primeiros venue adapters;
3. Birdeye/PumpPortal como enrichment/cross-check quando custo/entitlement permitirem;
4. Jupiter como execution proxy;
5. wallet intelligence anexada depois do market trigger.

Pump public program IDs congelados no protocolo:

- Pump: `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`;
- PumpSwap: `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`.

Não depender de scraping da UI Pump.fun.

## Próximo gate operacional

Ainda **não iniciar 12h**.

Ordem:

1. implementar adapter de stream nativo/provider;
2. fazer smoke curto de eventos reais;
3. validar reconnect, dedup, clocks e burst handling;
4. medir custo/rate-limit/provider coverage;
5. ligar radar -> episode -> Opportunity Core -> Jupiter;
6. smoke end-to-end curto;
7. somente depois congelar e iniciar primeira janela de 12h.

Meta DATA-READY futura:

- zero look-ahead;
- >=30 opportunity episodes;
- >=15 tokens;
- diversidade real de participantes;
- largest token share <=20%;
- >=90% episodes com timing/identity e ao menos um execution proxy utilizável.

Passar o gate valida aquisição, não edge.

## Shadow / live

- causal forward infrastructure: validada;
- quantity-aware accounting: validado;
- wallet-only edge: não estabelecido;
- Market Opportunity Radar: núcleo implementado/testado, stream real ainda não validado;
- executable landing/fill: não validado;
- shadow executável: não liberado;
- live: não liberado.

O projeto continua explicitamente **PAPER / RESEARCH / READ ONLY**.