# Pré-registro 2026-11-06 — "saída fiel" (variante de gestão pós-entrada, EXPLORATÓRIA)

PAPER/READ-ONLY. V3 roda com regras CONGELADAS (`ParamsV3=56762db29cd6`) — este documento e o módulo
`pos_runner/saida_fiel.py` NUNCA alteram detector/simulate/parâmetros/H1/critério de sinal. A
"saída fiel" é uma variante de **gestão da posição depois da entrada** (quando/quanto vender), nunca
uma mudança em quando ENTRAR — a V3 decide a entrada exatamente como hoje.

## Por que este documento existe, e por que NÃO é um pré-registro "a frio"

O pedido (rodada 12, Parte 1) exige registrar o algoritmo exato **antes** de rodar o retrospectivo
não condicionado (Parte 2) ou a sombra ao vivo (Parte 3) — mesma disciplina de pré-registro do resto
do projeto. **Mas, diferente de um pré-registro cego**: esta variante foi **motivada por achados
exploratórios já vistos** — a rodada 11 (item B3b, `scripts/auditoria_fidelidade_v3.py`) já mediu uma
variante PARECIDA (TP1 no 1º power candle OU no topo da própria caixa, breakeven, saída num stop
dinâmico único) sobre os mesmos dados. Isto é dito aqui **explicitamente, nunca escondido**: o
algoritmo abaixo **não é cego** em relação aos dados já coletados — por isso continua **EXPLORATÓRIO**
(nunca confirmatório), nunca entra no N=30 nem na H1, e qualquer promoção a hipótese formal exigirá
um pré-registro **novo e próprio**, julgado sobre coleta **ainda não vista** (mesma disciplina de
`CLAUDE.md`: "a hypothesis is entered as PRE-REGISTRADA before the collection that judges it" — o
que já foi visto nunca pode julgar a si mesmo).

## Algoritmo exato (congelado por hash — `garantir_saida_fiel_registrada`, nunca editado em
silêncio depois de registrado; qualquer mudança abre uma emenda datada nova)

1. **Stop inicial** = exatamente o stop já calculado pelo detector V3 para o sinal (`event.data["stop"]`)
   — nunca um valor novo.
2. **TP1 de 30% da posição** (`tp1_frac` já existente em `ParamsV3`), decidido no FECHAMENTO,
   executado no OPEN do candle seguinte (mesma convenção do resto do projeto) — dispara no
   **PRIMEIRO** entre:
   - **(i)** o 1º "power candle" depois da entrada: amplitude do candle (`high - low`) >=
     `power_atr_mult` × ATR(`atr_period`) — **MESMA** fórmula já existente
     (`pos_runner/simulate_v1.py: _exhaustion`, componente de amplitude; reusada byte a byte, nunca
     duplicada com um número novo); candle corrompido (`candle_corrompido_provavel`) NUNCA decide;
   - **(ii)** o preço alcança o **TOPO ANTERIOR** (`P_peak`, `event.data["TOPO"]` — a máxima do
     runner **antes** da queda que formou a caixa atual, NUNCA o topo da própria caixa): `high >=
     TOPO`, **independente** de exaustão (diferente da regra OFICIAL de TP1, que exige os dois
     juntos — aqui é OR, não AND; é uma variante nova, nunca a regra oficial).
3. **Depois do TP1**: o stop do RESTANTE (70%) move para o preço de entrada (**breakeven**) —
   verificado via `low` (prioridade-do-stop intracandle, mesma convenção causal do resto do
   projeto).
4. **Saída do restante**: no PRIMEIRO **fechamento de 1h**, em candle **VERMELHO** (`close < open`),
   **ABAIXO** da linha de tendência de alta traçada pelos **2 últimos fundos horários CONFIRMADOS
   que sejam ascendentes** entre si (reta de exatamente 2 pontos — nunca uma regressão sobre mais
   pontos). Pivô (fundo) = candle cuja mínima é **menor que as 2 vizinhas de CADA lado** (2 antes, 2
   depois) — confirmado causalmente só 2 candles depois (zero lookahead). Se os 2 últimos pivôs
   confirmados **não** forem ascendentes entre si (ou só existir 1 pivô confirmado até agora), usa-se
   o **último fundo estrutural confirmado** como nível único (nunca uma reta nesse caso). No MESMO
   candle, o stop de breakeven (passo 3) tem prioridade sobre esta regra de fechamento (mesma
   convenção de prioridade-do-stop).
5. **Custos e slippage**: exatamente os mesmos do `CostModel` oficial da V3 (`leg_pct`, por perna,
   mesma fórmula de `simulate_v1.py` — nunca um custo/slippage novo inventado para esta variante).

**Resultado em R** = combinação ponderada das 2 pernas (30% na saída do TP1 + 70% no restante),
mesma convenção de blend de pernas de `simulate_v1`. Se o restante nunca sair até o horizonte fixo
(72h/7d), marca-se a mercado no FECHAMENTO do candle no corte (mesma convenção de
`horizonte_fixo.calcular_r_horizonte`); se o horizonte ainda não decorreu, o sinal fica `pendente`
(nunca contado como perda, nunca descartado — só fora da amostra ainda).

## O que esta variante NÃO faz

- Não altera a entrada, o detector, os parâmetros congelados ou o critério de sinal da V3.
- Não decide nada por si — zero capital, zero vagas, zero alertas reais (Parte 3 é só leitura,
  tabela própria, nunca grava em `pr3_signals`/alertas/trajetória).
- Não é escolhida comparando-se a outras variantes nesta rodada depois de ver o resultado — esta é a
  ÚNICA variante que será medida como "saída fiel" a partir de agora; **nenhuma outra variante será
  usada para escolher** (declaração explícita pedida). A variante B3b da rodada 11 (TP1 no topo DA
  CAIXA, stop dinâmico único) continua existindo no código como uma análise **separada e
  condicional**, rotulada "não-negociável" (ver rodada 12, item 4a) — nunca comparada aqui para
  decidir qual "venceu".

## Riscos e viés documentados (nunca escondidos)

- **Motivada por dados já vistos** (ver seção acima) — o retrospectivo da Parte 2 sobre estes MESMOS
  dados nunca pode ser lido como confirmação de que a regra "funciona"; é, na melhor das hipóteses,
  uma segunda medição descritiva sobre a mesma amostra que a motivou.
- **Dentro da amostra**: toda a Parte 2 usa candles/pools já disponíveis — só sinais FUTUROS da
  sombra ao vivo (Parte 3), nunca recalculados retroativamente, poderiam um dia contar como evidência
  formal (e mesmo assim precisariam de um pré-registro próprio, novo, antes de julgar).
- **Viés de sobrevivência**: mesmo universo das rodadas anteriores (`pr_pools`/coorte retro/replay) —
  só alcança tokens que o bot/GeckoTerminal ainda indexam.

## Status

**PRÉ-REGISTRADO em 2026-11-06, antes de qualquer execução do retrospectivo (Parte 2) ou da sombra
ao vivo (Parte 3) sobre este algoritmo exato.** Qualquer mudança no algoritmo acima, depois de ver
resultado da Parte 2/3, abre uma nova emenda datada — nunca reescreve este texto em silêncio
(`garantir_saida_fiel_registrada` recusa com `PreregistroAlteradoError` se o arquivo mudar depois do
primeiro registro).
