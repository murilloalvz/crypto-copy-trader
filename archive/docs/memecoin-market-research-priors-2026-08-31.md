# Memecoin Market Research Priors — 2026-08-31

## Status

RESEARCH / CONTEXT ONLY. Este documento não altera `wave_v3_volume_integrity`, não cria uma nova estratégia e não promove nenhuma regra para live. O objetivo é registrar evidência externa útil como **prior**: conhecimento de mercado usado para avaliar se hipóteses internas do CopyTrader são plausíveis e para escolher testes com maior ganho de informação.

## Regra central

Evidência externa pode:

- sugerir perguntas;
- inspirar variáveis;
- ajudar a rejeitar hipóteses obviamente frágeis;
- fornecer benchmarks e testes de robustez.

Evidência externa NÃO pode:

- ser tratada como prova de edge no nosso universo;
- substituir forward/shadow próprios;
- justificar tuning pós-resultado;
- transformar comportamento de insider/sniper em estratégia copiável.

## O que a literatura/estudos recentes sugerem

### 1. O mercado é extremamente seletivo e heavy-tailed

Resultados de memecoins tendem a depender de poucos vencedores muito grandes. Estudos recentes de paper trading em Solana mostram que retirar poucos top trades pode inverter o resultado agregado. Portanto, média positiva isolada é fraca evidência.

Implicações para o CopyTrader:

- sempre reportar média e mediana;
- profit factor;
- drawdown;
- retorno sem top 1/top 3;
- participação do maior vencedor no lucro bruto;
- missingness e censura;
- resultados por regime/coorte.

### 2. Regras públicas simples de preço/volume podem não ser edge suficiente

Um estudo público de 2.380 memecoins e mais de 100 combinações rule-based, com slippage, reportou resultado nulo/reliavelmente não positivo. Embora a fonte não seja peer-reviewed e a metodologia precise ser auditada antes de reutilização quantitativa, o resultado é um prior forte contra a ideia de que uma combinação simples de indicadores públicos e lentos produzirá edge robusto por si só.

Implicação:

- `wave_v3` deve continuar como hipótese/sensor de oportunidade, não ser presumida como estratégia final;
- Wallet Intelligence, contexto social e execução causal podem carregar informação incremental que OHLCV público isolado não carrega.

### 3. Traders lucrativos não parecem formar um único arquétipo

Levantamentos públicos de wallets lucrativas mostram holding times que vão de segundos/minutos a horas/dias. Portanto, procurar uma única regra universal de saída/holding provavelmente perde estrutura do mercado.

Implicação:

- Strategy Lab e fingerprint por wallet fazem sentido;
- testar múltiplos arquétipos antes de um Strategy Router;
- não inferir que a wallet de maior PnL é a mais copiável.

### 4. Latência importa de forma diferente por arquétipo

Se a estratégia original segura por dias, atraso de dezenas de segundos pode ser tolerável. Se ela segura por 2–6 minutos, o mesmo atraso pode destruir o edge. Assim, `chain_time -> observed_at -> route quote -> eventual fill` é uma dimensão central da copyability.

Implicação:

- manter delays 0/15/30/60/120s no replay;
- cruzar resultado com holding/exit archetype;
- rejeitar cópia ultra-short se o edge desaparecer sob nosso lag real.

### 5. Snipers/creators podem parecer excelentes e ainda serem incopiáveis

Pesquisa com milhares de Pump.fun launches encontra creators/snipers com vantagens ligadas a acumulação precoce, funding links, front-running e timing privilegiado. Estudos também encontram coortes persistentes de first buyers, mas alertam que associação com maior fluxo não prova causalidade.

Implicação:

- alto PnL de wallet não basta;
- procurar funding/creator linkage, posição inicial anormal, first-buyer behavior e pre-existing inventory;
- marcar esses casos como possivelmente `structural/information advantage`, não automaticamente `copyable edge`.

### 6. Liquidez e execução são parte da estratégia, não detalhe operacional

Em pools pequenas, slippage e inability-to-exit podem dominar taxas de rede. Quote/route real e tamanho da posição precisam fazer parte do replay.

Implicação:

- usar Jupiter route quote causal;
- stress de notional;
- observar price impact;
- não extrapolar performance de wallet grande/pequena para nosso tamanho sem replay de rota.

### 7. Rejeitar trades ruins pode ser tão importante quanto encontrar winners

Pesquisa forward de filter-rejection em Solana encontrou grande parcela de tokens rejeitados sofrendo drawdowns severos depois. Isso sugere que qualidade de filtro pode ser avaliada também via contra-factual dos sinais rejeitados, não apenas via trades realizados.

Implicação futura:

- persistir razões de rejeição;
- acompanhar amostra de rejeitados;
- medir false negatives e drawdown evitado;
- evitar otimizar filtro apenas olhando winners aceitos.

### 8. Social/contexto aparenta ter informação, mas não deve virar `tweet -> buy`

Estudos de Pump.fun encontram associação forte entre presença social e probabilidade de graduação. Ao mesmo tempo, wash trading, comment bots e fabricação de atenção são documentados. Portanto social é variável contextual e potencial confirmação, não oracle.

Implicação:

- Social Intelligence deve medir informação incremental causal;
- separar presença/engajamento orgânico de manipulação;
- manter timestamps de primeira observação;
- testar se social melhora baseline depois de custos e lag.

### 9. Regime de mercado muda rápido

Taxas de graduação e distribuição de traders lucrativos variaram fortemente entre janelas de 2024–2026. Resultados históricos podem expirar rapidamente.

Implicação:

- usar janelas forward recentes;
- registrar regime/coorte/provider;
- evitar juntar dados separados por mudanças importantes de mercado;
- revalidar periodicamente sem retunar silenciosamente.

## Conhecimento de mercado que passa a orientar nossas análises

Quando uma hipótese nova aparecer, perguntar:

1. Qual é a provável fonte de edge: timing, seleção, informação, execução, sizing, exit ou manipulação?
2. É observável antes da decisão ou só aparece olhando o futuro?
3. Um copiador consegue observar a mesma informação?
4. O edge sobrevive a 15/30/60/120s de lag?
5. O edge sobrevive a quote real, slippage, price impact e failures?
6. A média depende de poucos outliers?
7. A wallet tem sinais de creator/sniper/insider/pre-existing inventory?
8. O padrão reaparece em mais de uma wallet/regime?
9. Existe um contra-factual/rejeitado que devemos acompanhar?
10. O resultado é histórico, forward, shadow ou live?

## Testes externos que podemos aproveitar

Não copiar resultados; reaproveitar **desenho de experimento** e, quando licenciado/publicado, datasets/código para benchmarks.

Prioridade:

1. RED-REJECT-2026-v1: corpus público de rejeições + follow-up, útil para estudar filter precision e desenho de counterfactual.
2. Pump.fun prediction/graduation research: útil para variáveis estruturais e early-stage context.
3. Sniper cohort datasets: úteis para detectar comportamento coordenado e separar smart-wallet de vantagem estrutural/incopiável.
4. Null-result rule-based dataset/study: útil como benchmark adversarial para evitar reinventar regras públicas frágeis.
5. Wallet-profiler datasets públicos: úteis para comparar nossos fingerprints, mas com auditoria de metodologia de PnL e inventory.

## Prior atualizado para o CopyTrader

A hipótese de arquitetura mais plausível não é `um indicador perfeito`, mas uma combinação causal de camadas independentes:

```text
market opportunity
-> wallet behavior / confirmation
-> optional social/context evidence
-> execution/copyability gate
-> strategy-specific management
-> shadow/live validation
```

Isso é um norte de pesquisa, não uma estratégia aprovada.

## Guardrails

- Não transformar creator/sniper/insider behavior em recomendação de cópia.
- Não assumir que PnL realizado de uma wallet inclui inventory não vendido.
- Não tratar graduação como sinônimo de trade lucrativo.
- Não tratar associação social como causalidade.
- Não tratar backtest externo como validação interna.
- Não promover nenhuma regra sem causal replay + custos + forward/shadow próprios.
