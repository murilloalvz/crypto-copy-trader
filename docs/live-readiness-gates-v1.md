# Live Readiness Gates v1

## Status

PLANEJADO / CONGELADO COMO PROCESSO. Este documento define o funil de promoção antes de observar resultados futuros. Ele não aprova nenhuma estratégia atual para live.

## Objetivo

Evitar que uma estratégia seja promovida para dinheiro real apenas porque um backtest, paper run ou pequena amostra forward parece boa. Cada estágio precisa provar uma propriedade diferente.

## Gate 0 — Integridade causal

Obrigatório antes de qualquer argumento de edge:

- entradas e confirmações usam apenas informação realmente observável naquele instante;
- wallets forward possuem `chain_time` e `observed_at` reais;
- social usa primeira observação para membership temporal;
- preços/quotes usados como evidência de execução carregam `observed_at` real;
- dados sincronizados retrospectivamente não são representados como se fossem conhecidos antes;
- nenhum candle/proxy é chamado de quote executável.

Falha neste gate invalida a conclusão, mesmo que o retorno aparente seja alto.

## Gate 1 — Hipótese descritiva congelada

Antes de procurar performance:

- definir qual comportamento/estratégia está sendo testado;
- congelar regra de entrada, regra de saída e universo aplicável;
- registrar critérios que enfraquecem/rejeitam a hipótese;
- não ajustar a narrativa depois de observar o resultado da mesma coorte.

Wallet fingerprints e Wallet Strategy Readiness servem para formular essa hipótese; não provam edge.

## Gate 2 — Replay causal com custos

Uma estratégia candidata só avança se puder ser reproduzida usando:

- delay real de detecção;
- delay adicional de decisão quando aplicável;
- quote causal disponível após a decisão;
- slippage e fees contra o replay;
- restrição de stale quote;
- liquidez/route context quando disponível;
- tratamento explícito de missing data e falhas.

Resultados precisam ser reportados com cobertura, não apenas sobre fills bem-sucedidos.

## Gate 3 — Robustez estatística mínima

O projeto continua usando `n < 30` como amostra inconclusiva para promoção. `n >= 30` é apenas um primeiro gate operacional, não prova robustez. Quando possível, buscar amostra maior e diferentes condições de mercado.

A avaliação deve incluir pelo menos:

- média e mediana;
- win rate;
- profit factor;
- drawdown;
- melhor/pior resultado;
- dependência do maior vencedor;
- sensibilidade a slippage/fees/latência;
- cobertura e missingness;
- stress para observações ausentes quando a ausência puder ser informativa.

Uma média positiva isolada não é suficiente.

## Gate 4 — Shadow execution

A estratégia roda em tempo real tomando exatamente as decisões que tomaria em live, mas sem assinar/enviar transações.

Obrigatório registrar:

- decisão e timestamp;
- quote/route que seria usado;
- tamanho pretendido;
- slippage/fees estimados;
- motivo de entrada/saída;
- falhas/retries;
- estado da posição e reconciliação simulada.

A estratégia não deve ser modificada silenciosamente durante a mesma coorte shadow.

## Gate 5 — Execution Engine operacional

Antes de qualquer canary real, a infraestrutura precisa suportar:

- obtenção de quote/route executável;
- rejeição de stale quote;
- limites de slippage;
- criação/submissão de transação;
- confirmação on-chain;
- idempotência para evitar ordem duplicada;
- retry apenas quando seguro;
- reconciliação entre intenção, transação confirmada e saldo real;
- tratamento de partial/failed transaction;
- limites de exposição e concorrência;
- kill switch;
- logs suficientes para reconstruir uma decisão.

Ter um paper stop-loss não satisfaz este gate.

## Gate 6 — Live Canary

Primeira execução com dinheiro real deve ser deliberadamente limitada:

- wallet separada;
- apenas estratégia que passou os gates anteriores;
- capital pequeno definido antes da execução;
- limite por posição;
- limite de perda diária/sessão;
- limite de posições simultâneas;
- kill switch manual/automático;
- nenhuma escala automática de banca;
- comparação contínua `shadow esperado x live executado`.

Objetivo primário do canary: validar execução e desvio real, não maximizar lucro.

## Gate 7 — Promoção gradual

Só considerar aumento de capital após demonstrar que:

- a execução live corresponde razoavelmente ao shadow/replay;
- custos reais não destroem o edge observado;
- falhas operacionais estão dentro do esperado e são recuperáveis;
- risco permanece dentro dos limites congelados;
- resultados não dependem de uma anomalia ou de poucos trades extremos.

Escala deve ser gradual e reversível.

## Estado atual em relação aos gates

- Gate 0: infraestrutura causal parcialmente implementada; wallet forward e social possuem `observed_at`; camada de quote causal foi criada, mas ainda precisa de fonte executável real.
- Gate 1: IMPLEMENTADO para as hipóteses atuais de Wallet Strategy Lab; `wave_v3_volume_integrity` segue congelada.
- Gate 2: engine base de Wallet Causal Replay IMPLEMENTADO; falta alimentar quotes executáveis e depois métricas de PnL/edge.
- Gate 3: Wave/Exit ainda em coleta; Wallet archetypes ainda não têm amostra de edge causal.
- Gate 4: PLANEJADO.
- Gate 5: PLANEJADO.
- Gate 6: BLOQUEADO pelos gates anteriores.
- Gate 7: NÃO INICIADO.

## Regra de promoção

Nenhum resultado histórico forte pode pular gates. Um estágio pode ser desenvolvido em paralelo para economizar calendário, mas só pode ser **ativado como evidência** quando os pré-requisitos anteriores estiverem satisfeitos.
