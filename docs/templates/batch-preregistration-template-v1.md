# Pré-registro em lote — LOTE-<ID> — <data>

Status: **PRE-REGISTRADO**. Este arquivo precisa estar commitado (e de preferência com push) **antes** do início da coleta que vai julgá-lo. Sign-off do operador: `<nome, data>`.

Regras do programa: `docs/research-hypothesis-registry-v1-2026-10-04.md`.

## 1. Coleta que julga este lote

- Run key(s): `<...>` (frescas, nunca usadas)
- Caminho de aquisição: `<script + versão>`, git head esperado `<sha>`
- Janela e cohorts: `<ex.: 2 subcohorts A/B de 120s, 12h-19h BRT>`
- Instrumento de medida: `<ex.: Jupiter route-only US$25, 100 bps>` (trocar o instrumento exige um lote novo)
- Gates de sistema que precisam passar antes de qualquer número econômico: `<lista>`
- Condições operacionais: saída redirecionada para arquivo, PC sem suspensão, nenhum outro uso das chaves de provider

## 2. Hipóteses (K = <n>)

Repetir o bloco abaixo para cada hipótese.

### H<k> — <nome curto>

- Família: `<fluxo | concentração | qualidade de wallet | coordenação | metadado do token | ...>`
- Tipo: `<entrada (alpha) | filtro de rejeição>`
- Origem: `<nova | derivada de X (X segue fechada)>`
- Feature: definição causal exata, campo e arquivo. Limitada por `decision_as_of`, faltante fica explícito (nunca 0).
- Regra congelada: corte/bins, direção favorável e como o corte foi obtido. O corte tem que ser obtido sem olhar resultado; se veio de dado antigo, citar qual amostra e confirmar que ela não é a deste lote.
- Horizonte primário: `<s>` (os outros são só diagnóstico)
- Suporte mínimo: `<n por grupo / por subcohort>`
- PASS exige todos: `<lista numerada, inclusive mediana > 0 e PF > 1 quando for alpha>`
- FAIL: `<...>` · INCONCLUSIVE: `<suporte insuficiente / cobertura da feature abaixo de X%>`
- Controles / placebo: `<ex.: placebo pareado por atividade; slot deslocado>`
- Dependências de observabilidade: `<campos que precisam estar persistidos causalmente; se faltarem, a hipótese é INCONCLUSIVE, nunca reinterpretada>`
- O que um PASS **não** prova: `<fill, custos, saída, shadow, live>`

## 3. Multiplicidade e próximos passos

- Este lote julga K = `<n>` hipóteses na mesma coleta.
- Hipótese com PASS → status `PASS (aguarda replicação)` no registro → replicação **sozinha**, com a mesma regra, chave nova e pré-registro próprio commitado antes.
- Hipótese com FAIL/KILL → fecha. Nenhuma variação dela é testada de novo nesta amostra.
- Falha de sistema da coleta → nenhuma hipótese recebe veredito; o lote pode ser reaproveitado numa coleta nova sem mudança de regra.

## 4. Proibido depois de ver dado

Mudar corte, direção, horizonte, suporte, gates ou controles; incluir ou remover hipóteses do lote; olhar só um subgrupo; combinar hipóteses num score.

## 5. Atualização do registro

Depois do resultado: uma linha por hipótese em `docs/research-hypothesis-registry-v1-2026-10-04.md` e os contadores atualizados, no mesmo commit que registra o resultado.
