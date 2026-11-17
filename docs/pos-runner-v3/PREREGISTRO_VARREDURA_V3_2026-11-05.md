# Pré-registro 2026-11-05 — varredura_v3.py: definição de "boa oportunidade" (ANTES de ver resultados)

PAPER/READ-ONLY. V3 roda com regras CONGELADAS (`ParamsV3=56762db29cd6`) — este documento e o script
`scripts/varredura_v3.py` NUNCA alteram detector/simulate/parâmetros/H1/critério de sinal. Tudo aqui é
**EXPLORATÓRIO**: nunca evidência confirmatória, nunca entra no N=30 nem na H1 (`docs/
research-hypothesis-registry-v1-2026-10-04.md` continua sendo a autoridade para isso).

## Por que este documento existe

O pedido (item B6) exige registrar a definição de "boa oportunidade" **antes** de rodar a varredura —
mesma disciplina de pré-registro do resto do projeto, aplicada a um script exploratório que não decide
nada por si (zero capital, zero vagas, zero `max_pools`). Isto é texto, datado e comitado antes de
qualquer linha de resultado existir.

## Definição de "boa oportunidade" (congelada por esta rodada)

Um sinal V3 (ou um token, na agregação) é descrito como favorável quando:

1. **Desfecho primário**: P(tocar +2R antes de -1R) — onde R = distância do stop da própria V3, medida
   causalmente candle a candle a partir da entrada, parando no primeiro de dois eventos: tocar o alvo
   OU tocar o stop (prioridade do stop dentro do mesmo candle, mesma convenção de `simulate_v1`). O
   equilíbrio matemático antes de custos para alvo +2R/stop -1R é **33,3%** (1/(1+2)) — o relatório
   sempre reporta o valor observado ao lado desse referencial, nunca escondido.
2. **Secundário — pareamento**: a diferença pareada contra os 10 controles do mesmo token (mesma
   mecânica de `pos_runner/evidencia.py`, já usada pela H1) precisa ser, na direção favorável, POSITIVA
   na média — reportado com IC90% bootstrap por token, nunca um ponto isolado.
3. **Terceiro, apenas diagnóstico**: MFE em R a 72h e R marcado a mercado a 72h/7d (`pos_runner/
   horizonte_fixo.py`, reusado) — acompanham, nunca substituem os dois critérios acima.

Nenhum outro corte (ex.: "MFE médio > X") é promovido a critério de "boa oportunidade" nesta rodada.

## Estratos exploratórios (fixados ANTES de qualquer resultado)

Reusa os MESMOS 8 estratos já pré-registrados para V3 em `docs/pos-runner-v3/
PREREGISTRO_V3_2026-11-02.md` (via `analise/condicional.py: _grupos_v3_estratos`) — caixa (candles),
caixa (horas), idade, queda do pico, MC da base, gatilho, descomunal, possível clone. **Proibido** criar
um estrato novo depois de ver o resultado da varredura; qualquer recorte novo observado nos dados é
hipótese de próxima rodada, nunca promovido aqui. Correção Holm-Bonferroni sobre a família completa dos
8, exatamente como a H1 já faz.

## Riscos e viés documentados (nunca escondidos)

- **Dentro da amostra**: toda a varredura usa candles/pools já disponíveis — nunca é "fora da amostra"
  no sentido forte. Só sinais FUTUROS gerados pela V3 já congelada, ao vivo, contam como evidência de
  verdade (H1 continua sendo o único caminho formal).
- **Viés de sobrevivência**: o universo (pools em `pr_pools`, candidatos retro) só inclui tokens que o
  bot/GeckoTerminal ainda alcançam — tokens que saíram completamente do GT (sem liquidez, delistados)
  nunca entram, inflando o resultado médio pra cima (sobrevivência). Mitigação possível (não aplicada
  nesta rodada): coleta adicional e lenta de histórico mais antigo (item B1d do pedido) — documentada
  como próximo passo, nunca implementada aqui (exige chamadas de rede ao vivo, fora do escopo de um
  script somente leitura).
- **Resultado em paper é TETO de execução**: custo/slippage reais só podem ser iguais ou piores que os
  modelados aqui.
- **Multiplicidade**: 8 estratos sob Holm controlam a família exploratória; a varredura em si (universo
  inteiro, sem holdout) não é um teste confirmatório — nunca different disso.

## Status

**PRÉ-REGISTRADO em 2026-11-05, antes de qualquer execução de `varredura_v3.py` sobre dados reais.**
Qualquer mudança na definição acima, depois de ver resultados, abre uma nova emenda datada — nunca
reescreve este texto em silêncio.
