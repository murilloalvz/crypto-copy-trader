# Pré-registro 2026-11-10 — grade fechada de saídas PARCIAIS antecipadas (EXPLORATÓRIA)

PAPER/READ-ONLY. V3 roda com regras CONGELADAS (`ParamsV3=56762db29cd6`) — este documento e o módulo
`pos_runner/saidas_parciais.py` NUNCA alteram detector/simulate/parâmetros/H1/critério de sinal. É
uma variante de **gestão da posição depois da entrada** (quando/quanto vender), nunca uma mudança em
quando ENTRAR.

## Por que este documento existe, e por que NÃO é um pré-registro "a frio"

Motivado diretamente pelo resultado já medido de B3b (a) sobre TODOS os sinais (rodada 12, Parte 4a):
**−0,15R** quando a média é recalculada sem condicionar a TP1 realizar. Isso é dito aqui
**explicitamente, nunca escondido**: a pergunta que esta grade investiga — "será que vender uma
fração MENOR/MAIOR, com um gatilho de TP1 diferente, melhora esse número?" — só existe porque o
−0,15R já foi visto. Por isso esta rodada continua **EXPLORATÓRIA** (nunca confirmatória), nunca
entra no N=30 nem na H1, e qualquer promoção a hipótese formal exige um pré-registro **novo e
próprio**, julgado sobre coleta **ainda não vista** (mesma disciplina de sempre).

## Grade fechada — 24 variantes exatas (nunca mais, nunca menos sem uma emenda nova)

**Eixo 1 — gatilho do TP1** (preço-alvo, decidido no FECHAMENTO — `high >= alvo` —, executado no
OPEN do candle seguinte; nunca exige "power candle", ao contrário de `saida_fiel.py`):

| código | definição |
|---|---|
| `+1R` | `entry + 1,0 × (entry − stop)` |
| `+2R` | `entry + 2,0 × (entry − stop)` |
| `+3R` | `entry + 3,0 × (entry − stop)` |
| `topo_caixa` | `R` (resistência/topo da PRÓPRIA caixa, `event.data["R"]`) — **nunca** o TOPO anterior |
| `meio_topo_anterior` | `entry + 0,5 × (TOPO − entry)` (TOPO anterior = `P_peak`, `event.data["TOPO"]`) |

Sinal sem o dado necessário pro gatilho (ex.: `R` ausente para `topo_caixa`, ou `TOPO <= entry` para
`meio_topo_anterior`) fica `sem_dado` — nunca inventa um alvo.

**Eixo 2 — fração vendida no TP1**: 30% (`tp1_frac` já existente em `ParamsV1/V2/V3`, nunca um
número novo) ou 50%.

**Eixo 3 — gestão do restante** (sempre testado via `low`, prioridade sobre fechamento no mesmo
candle — mesma convenção causal do resto do projeto):

- `segurar`: o stop do restante nunca se move (fica no stop ORIGINAL) até o stop bater ou o
  horizonte vencer — é o controle natural (equivalente à regra B3 "nenhum ajuste").
- `breakeven`: o stop do restante move para o preço de ENTRADA, imediatamente após o TP1.
- `trailing`: o stop do restante **nunca se move do stop ORIGINAL** (mesma proteção mínima de
  `segurar` — simplificação explícita: esta variante nunca combina com breakeven), mas ganha uma
  saída ADICIONAL por fechamento: no primeiro fechamento de 1h, em candle VERMELHO
  (`close < open`), abaixo do **último fundo horário ascendente** — pivô = mínima menor que as 2
  vizinhas de CADA lado (MESMA definição de `saida_fiel._pivo_confirmado`, confirmado causalmente só
  2 candles depois), "ascendente" = o pivô mais recente confirmado é MAIOR que o pivô confirmado
  imediatamente anterior. **Antes de existirem 2 pivôs confirmados, ou enquanto o par mais recente
  não for ascendente, a saída por fechamento fica inativa** (nunca inventa um nível) — só a proteção
  mínima do stop original (via `low`) continua valendo nesse período.

### Poda de 30 para 24 (5 gatilhos × 2 frações × 3 restantes = 30, pedido exige ≤24)

**Critério de poda, decidido ANTES de ver qualquer resultado**: a fração de 50% só é testada para os
3 gatilhos **MAIS DISTANTES** do que já foi medido em rodadas anteriores — `+1R`, `+3R` e
`meio_topo_anterior` — porque `topo_caixa` já é essencialmente o gatilho de B3b (a) (medido a 30%,
rodada 11/12) e `+2R` já é o alvo padrão de pareamento do projeto (`ALVO_PAREAMENTO_TOQUE`,
`varredura_v3.py`, extensivamente medido em B2). Dobrar a fração justamente onde o gatilho já é bem
conhecido adiciona menos informação nova que dobrar onde o gatilho é inédito. Resultado:

- **30% de fração** × todos os 5 gatilhos × todos os 3 restantes = **15 variantes**.
- **50% de fração** × só `{+1R, +3R, meio_topo_anterior}` × todos os 3 restantes = **9 variantes**.
- **Total = 24 variantes**, lista exata gerada por `saidas_parciais.GRADE_24` (nunca escrita 2x —
  o código é a fonte única da lista, este documento descreve a REGRA que a gera).

## Horizontes, origens, custos (reuso, nunca um número novo)

- Horizontes fixos 72h e 7d (`horizonte_fixo.HORIZONTES_S`), MESMA convenção: resolvido pela regra
  se fechar antes do corte, senão marcado a mercado no corte; pendente (horizonte não decorrido)
  nunca excluído nem contado como perda.
- Origens `ao_vivo`/`retro_lote1`/`replay_v3` SEMPRE separadas, nunca somadas.
- Custos/slippage: `CostModel.leg_pct` (mesma fórmula de `simulate_v1`/`saida_fiel`). Sensibilidade
  pedida (2x/3x) multiplica **só o componente de slippage** (`CostModel.slippage_pct`) das pernas de
  **SAÍDA** (TP1 e saída do restante) — nunca a entrada, nunca o fee do pool/terminal/rede (que não
  são "slippage").

## Estatísticas e atribuição

Por variante × horizonte × origem: `P(TP1)`, R médio da perna 1 (dado TP1, pré-custo isolado), R
médio da perna do restante (dado que chegou à fase 2, pré-custo isolado), R médio de quem NUNCA
realiza TP1 (posição inteira, pré-custo = pós-custo já que é 1 perna só); média/mediana/sem-top-3/
leave-one-token-out/IC90% bootstrap (10k reamostras, semente fixa `20_261_026`, MESMOS defaults de
`analise.condicional`) sobre TODOS os sinais com horizonte vencido (nunca só quem realiza TP1).
Atribuição: a MESMA variante aplicada aos 10 controles pareados e às K=20 entradas aleatórias do
sinal (MESMA fase/distância de stop — `varredura_v3._evento_controle_sinal`), pra separar efeito da
entrada do efeito da saída. Holm-Bonferroni (`analise.condicional.holm_bonferroni`, α=0,05) sobre as
24 variantes, **por origem separadamente** (3 famílias independentes, nunca uma família combinada),
no horizonte 72h (primário); 7d é diagnóstico, fora do Holm. p-valor por variante = bootstrap
unilateral `P(média_bootstrap da diferença pareada <= 0)`, blocos por token, mesmos defaults. O nº
BRUTO de variantes testadas (24, por origem) é sempre reportado ao lado do resultado do Holm —
nenhuma variante é descartada silenciosamente antes da correção.

## O que esta grade NÃO faz

- Não altera a entrada, o detector, os parâmetros congelados ou o critério de sinal da V3.
- Não decide nada por si — zero capital, zero vagas, zero alertas reais, zero escrita em
  `pr3_signals`/alertas/trajetória/H1.
- Não escolhe uma variante "vencedora" — a grade é FECHADA e reportada por completo; qualquer
  promoção de uma variante específica a hipótese formal exige um pré-registro novo e próprio.
- Não reexecuta `saida_fiel.py` nem `auditoria_fidelidade_v3.py` — a correspondência com B3b (a) é
  só uma checagem de sanidade (comparação qualitativa de números já medidos em rodadas anteriores
  contra a variante mais parecida desta grade), nunca uma validação formal (os gatilhos/restantes não
  são idênticos byte a byte).

## Riscos e viés documentados (nunca escondidos)

- **Motivada por dados já vistos** (B3b (a) = −0,15R) — qualquer resultado desta grade sobre os
  MESMOS dados nunca pode ser lido como confirmação; é, na melhor das hipóteses, uma terceira
  medição descritiva sobre a mesma amostra que a motivou.
- **Dentro da amostra**: toda a grade usa candles/pools já disponíveis — só sinais FUTUROS da sombra
  ao vivo poderiam um dia contar como evidência formal, e mesmo assim precisariam de um pré-registro
  próprio antes de julgar.
- **Viés de sobrevivência**: mesmo universo das rodadas anteriores (só tokens que o
  bot/GeckoTerminal ainda indexam).
- **Múltiplas comparações**: 24 variantes × 2 horizontes × 3 origens × (variante real + controles +
  aleatório) é uma busca ampla — o Holm-Bonferroni corrige a família de 24 por origem/horizonte
  primário, mas não corrige entre horizontes nem entre origens (decisão deliberada: origens nunca se
  somam, 7d é diagnóstico).

## Status

**PRÉ-REGISTRADO em 2026-11-10, antes de qualquer execução da grade sobre dados reais.** Qualquer
mudança no algoritmo/grade acima, depois de ver resultado, abre uma nova emenda datada — nunca
reescreve este texto em silêncio (`garantir_saidas_parciais_registrada` recusa com
`PreregistroAlteradoError` se o arquivo mudar depois do primeiro registro).
