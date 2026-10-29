# Plano de análise pré-registrado — baseline pareada V1/V2 (PEDIDO PARTE 1 de 2)

Status: **PRE-REGISTRADO** antes de qualquer análise sobre `pr_baseline`/`pr_trajetoria`. O hash deste
arquivo (texto completo, `short_hash`) é registrado em `meta` (`plano_analise_hash`) por
`signals_mvp.analise.condicional` na primeira execução — depois disso este documento **não pode ser
editado** sem abrir uma nova versão (novo arquivo ou seção, nunca reescrever o texto já julgado).
`/analise` (Telegram) e `python -m signals_mvp.analise.condicional` recusam rodar se o hash do arquivo
em disco não bater com o hash registrado (ver `condicional.verificar_hash_plano`).

Esta análise NÃO é sobre se a V1/V2 "funciona" isoladamente (isso é `PROTOCOLO_VALIDACAO.md`, métrica
R por trade fechado). É sobre se o sinal real bate uma **linha de base pareada** do mesmo token —
`dif_pareada = R_sinal − R_controle_médio` (`pr_baseline`, FASE 2a). R aqui é sempre o mesmo R-múltiplo
usado em `ANALISE_MONTE_CARLO.md`/`PROTOCOLO_VALIDACAO.md` (`lucro_líquido_% / risco_%`).

## Métrica e amostra

- Unidade de análise: 1 ENTRADA real fechada **com `dif_pareada` já calculado** (controles E sinal
  resolvidos — `pr_baseline_resolvidas_com_dif`). Linhas com algum controle pendente nunca entram.
- `n` conta **tokens distintos** (mint), não sinais — mesma convenção de `_stats_r_de_fechados`.
- V1 e V2 **nunca se misturam** na mesma análise (coluna `versao`); rodar as duas separadamente.
- **Sensibilidade de saída por stop (2026-10-27, item 4 pós-auditoria)**: `R_sinal`/`dif_pareada`
  (H1–H8, R oficial) sempre usam o preenchimento OFICIAL do stop (`min(open, stop)` — sem gap/
  slippage, convenção de `simulate_v1.py` inalterada). `pr1_signals.r_exit_open_seguinte`/
  `pr2_signals.r_exit_open_seguinte` (nullable; só preenchida quando o trade fechou por "stop" e
  havia candle seguinte) guarda o R alternativo usando o OPEN do candle seguinte ao candle que
  violou o stop — mais realista para ordens que só executam depois do candle fechar. É uma análise
  de SENSIBILIDADE à parte (comparar a magnitude de H1 com R oficial vs. R com esta convenção
  alternativa), nunca substitui `dif_pareada`/R oficial em H1–H8.

## Exclusão pré-declarada por candle/preço absurdo (DIAGNÓSTICO 2026-10-27)

Adicionada **antes de qualquer coleta/análise ter rodado sobre dados reais** (nenhuma linha de
`meta.plano_analise_hash` ainda registrada neste checkout) — por isso é uma adição a este mesmo
documento pré-registrado, não uma nova seção/versão. Motivo: dois alertas reais (McRib ENTRADA
27/10 ~10:05, ヤギ TP1 27/10 12:07) mostraram inconsistência entre o preço mostrado no alerta e o
preço gravado/o desfecho — ver `docs/pos-runner-v1/INTERPRETACOES.md` §13 para o diagnóstico
completo. Esta regra impede que um candle/preço absurdo **confirmado** contamine H1–H8; ela NÃO
corrige a V1/V2 (hash intacto) e NÃO interpola nada — um trade excluído simplesmente não entra em
nenhuma contagem/bootstrap.

**Atualização 2026-10-27 (patch `qualidade_candle.py` + `_confirmar_entrada`)**: adicionado um
terceiro critério, pelo mesmo motivo (seção abaixo) — `risco_irrealista` (item 3 do pedido de
patch). Mesma regra: adição a este documento, nunca reescrita do texto já em vigor; nenhuma coleta
real rodou sobre este checkout antes desta adição.

**Atualização 2026-10-27 (pós-auditoria na VM)**: a auditoria (`scripts/auditar_trades.py`) confirmou
candle com volume 0 e salto ~100x vs. os vizinhos em McRib V1#6/V2#2 e ヤギ V2#1 — fora do candle do
gatilho/preço de entrada (não cobertos pelos critérios 1–2) e sem relação com risco baixo (critério
3). Adicionado o 4º critério — `contaminado_candle`, marcação RETROATIVA e EXPLÍCITA do operador
(`scripts/marcar_contaminados.py`, nunca auto-detectada), para cobrir contaminação em qualquer ponto
do ciclo de vida do trade.

Um trade (`entry_id`/`versao`) é excluído de H1–H8 quando **qualquer um** dos quatro é confirmado:

1. **`preco_entrada_divergente`** — o preço PROVISÓRIO mostrado no alerta ENTRADA
   (`pr1_signals.entry_price_alerta`/`pr2_signals.entry_price_alerta`, gravado 1x e nunca
   sobrescrito) diverge do preço gravado/corrigido (`entry_price`, atualizado quando o fill real é
   conhecido) em mais de 1% relativo — mesma ordem de grandeza da tolerância padrão da conferência
   cruzada DexPaprika (`dexpaprika_v1.DexPaprikaProvider.tolerancia_pct = 1.0`). Sinal sem
   `entry_price_alerta` (coluna nova, sinais antigos ficam `NULL`) nunca é excluído por falta de
   dado — dado ausente nunca conta como divergência.
2. **`candle_divergente`** — existe pelo menos uma linha em `pr1_dexpaprika_divergencias` para o
   mesmo `pool` e o mesmo candle do GATILHO (`ts_fechamento`) do sinal (só V1 tem conferência
   cruzada própria; V2 nunca é excluído por este critério). Qualquer linha ali logada já passou da
   tolerância configurada — não há limiar novo a aplicar.
3. **`risco_irrealista`** (2026-10-27) — o sinal está tagueado `risco_irrealista` em `tags`
   (gravado por `PosRunnerLive._confirmar_entrada`, `risco real = (fill − stop) / fill < 3%`,
   `RISCO_IRREALISTA_MIN_PCT`). A tag nunca bloqueia/cancela o sinal no paper — ele continua
   negociando normalmente; só fica fora da amostra confiável de H1–H8, já que um risco real colado
   no stop distorce o R-múltiplo sem representar o setup pretendido pela regra.
4. **`contaminado_candle`** (2026-10-27) — o sinal está tagueado `contaminado_candle` em `tags`
   (gravado por `scripts/marcar_contaminados.py`, SÓ depois do operador confirmar na auditoria —
   nunca auto-detectado em tempo real). Mesmo tratamento do critério 3: nunca bloqueia/cancela o
   sinal, só fica fora da amostra confiável.

A lista de excluídos (entry_id, mint, símbolo, motivo) é reportada em
`signals_mvp/analise/condicional.py` (`RelatorioCondicional.excluidos`, impressa em
`formatar_markdown`; `formatar_telegram` reporta só a contagem). Implementação:
`carregar_sinais_e_excluidos` (mesmo módulo).

Limitação conhecida: a conferência cruzada DexPaprika só roda quando `dexpaprika.deve_conferir()`
permite (orçamento/limiter compartilhado — PEDIDO CONSOLIDADO FASE 1 item 3b) e só a partir de
quando o provedor foi ligado; um candle defeituoso SEM uma linha correspondente em
`pr1_dexpaprika_divergencias` (fora da janela orçada, ou anterior à ativação do provedor) não é
pego por este critério — fica só o critério 1 (preço de entrada) como rede de segurança para esses
casos. Isto é uma lacuna conhecida, não uma correção da V1/V2.

## H1 — primária, única confirmatória

**Hipótese:** a média de `dif_pareada` é > 0 (o sinal real supera, em média, a linha de base pareada
do mesmo token no mesmo período).

**Decisão (fixa, nesta ordem — mesmo molde de `PROTOCOLO_VALIDACAO.md`):**

1. **Futilidade antecipada** (reusa a regra de futilidade já existente para a métrica R da V1 —
   `PROTOCOLO_VALIDACAO.md` §"Regras de decisão", item 1 — aplicada aqui a `dif_pareada`): com
   **n = 15** sinais (tokens distintos) resolvidos, se a média de `dif_pareada` estiver **< −0,5 R**,
   H1 para aqui — `FUTIL`. Não espera os 30 completos.
2. **Decisão em n = 30**: com **n = 30** sinais (tokens distintos) resolvidos (e sem ter parado por
   futilidade), bootstrap em blocos (10.000 réplicas, seed fixa `20_261_026`) calculado **duas vezes**
   — uma vez com blocos por **dia** (`dia_utc` da entrada) e uma vez com blocos por **token** (mesmo
   método de `simulacao_bloco.expectancia_r_limite_inferior`, adaptado para blocar por token em vez
   de só por dia). Escala (`PASS` nesta rodada) **só** se o limite inferior unilateral de 90% for
   **> 0 nos DOIS bootstraps** (dia e token) — a interseção, não qualquer um dos dois; é a leitura
   mais conservadora de "bootstrap em blocos por dia e por token" e evita que uma correlação forte só
   num dos dois eixos (ex.: vários sinais do mesmo token no mesmo dia) infle o resultado.
3. Esta validação por si só não promove nada a `VALIDADA` — isso continua exigindo os 3 passos do
   registro de hipóteses do repositório (PASS pré-registrado, PASS numa replicação fresca, líquido de
   custos positivo no Gate 2), conforme `/home/user/crypto-copy-trader/CLAUDE.md`.

## H2–H8 — exploratórias (Holm sobre as testadas)

Cada sub-hipótese abaixo testa, **dentro do grupo nomeado** (nunca comparando grupo A contra grupo B
diretamente — é a mesma pergunta de H1, "o sinal bate a baseline", restrita a um subconjunto), se a
média de `dif_pareada` é > 0, usando o MESMO bootstrap por dia (10.000 réplicas, mesma seed) e o
p-valor bootstrap de uma ponta `p = P(média_bootstrap <= 0)`. **Grupo com n < 10 (tokens distintos)
nunca é reportado** (nem conta p-valor, nem entra no Holm).

- **H2** — tipo de gatilho: 3 grupos, `reacao_suporte` / `power_candle_rompimento` /
  `rompimento_volume` (campo `gatilho`, JSON-lista — um sinal pode estar em mais de um grupo se
  disparou mais de um gatilho; grupos não são mutuamente exclusivos, é a mesma convenção do
  relatório semanal existente);
- **H3** — risco: `risco_pct < 25%` vs `>= 25%` (campo `risco_pct` do sinal real);
- **H4** — liquidez: acima vs abaixo da **mediana observada na amostra testada** (campo
  `liquidez_usd` do sinal; mediana recalculada a cada execução, nunca um valor fixo);
- **H5** — holder concentrado: `holders_tag == "HOLDER_CONCENTRADO"` vs `holders_tag is None` (sinais
  com `holders_indisponivel` **não entram em nenhum dos 2 grupos** — dado ausente nunca conta como
  "não concentrado");
- **H6** — `base_ge_2d` presente vs ausente na lista `tags` do sinal;
- **H7** — janela de ouro: `janela_ouro == "janela_ouro"` vs `"fora_da_janela"`.

**Correção Holm:** os p-valores de **todos** os grupos acima que tiverem n >= 10 (até 3 de H2 + 2 de
H3 + 2 de H4 + 2 de H5 + 2 de H6 + 2 de H7 = até 13 testes) formam UMA família; aplica-se Holm-Bonferroni
step-down (ordena p-valores crescente, compara o i-ésimo menor contra α/(m−i+1), α = 0,05) sobre essa
família completa — nunca por "H" isolado. Um grupo que passa o Holm é **candidato**, nunca validado
(discovery, não confirmatório — nunca é promovido sem um novo pré-registro específico, replicação
fresca e Gate 2, igual a qualquer hipótese derivada).

- **H8** — `carteiras_pro_presentes >= 1` (>= 1 carteira "pro" entre os top-20 holders no momento da
  ENTRADA) **vs `== 0`**. **Atualização 2026-10-27 (item 2 pós-auditoria)**: a COLETA já existe —
  `PosRunnerLive._registrar_snapshot_carteiras`/`pr_carteiras_snapshot` (RPC `getTokenLargestAccounts`
  + `getAccountInfo`, reusando a MESMA chamada que `holders_tag`/`HOLDER_CONCENTRADO` já fazem na
  ENTRADA — zero custo extra; a coleta HORÁRIA, só para pools com posição aberta, é uma chamada NOVA,
  orçada por `CARTEIRAS_MAX_CHAMADAS_DIA`). `pr1_signals.carteiras_pro_presentes`/`n_pessoas_pro`
  (nullable — `NULL` quando `holders_indisponivel`, nunca um 0 fabricado) ficam preenchidos a partir
  de agora; sinais anteriores a este patch continuam `NULL`. **H8 segue fora do Holm até n >= 10 por
  grupo com dado não-nulo** (ainda não atingido — nenhuma coleta real rodou até este commit).

- **H9 (PROPOSTA, pendente de confirmação do operador antes da 1ª coleta real)** —
  `n_pessoas_pro >= 2` (múltiplas pessoas "pro" distintas presentes, não só uma) **vs `<= 1`**. Mesmo
  método de H8 (bootstrap por dia, p-valor unilateral, Holm sobre a família H2–H9). Justificativa:
  H8 testa presença (>=1 carteira), H9 testa CONCENTRAÇÃO de interesse "pro" (múltiplas pessoas, não
  só uma carteira isolada de uma mesma pessoa) — pergunta distinta, mesma lista/coleta. **Fica
  marcada "não testada" e fora do Holm até (a) o operador confirmar o corte `>=2` (ou pedir outro) e
  (b) n >= 10 por grupo** — exatamente a mesma trava do H8 original antes da lista existir
  (`docs/research-hypothesis-registry-v1-2026-10-04.md`: toda hipótese econômica precisa de
  pré-registro explícito antes da coleta que a julga; esta seção serve de pré-registro PROVISÓRIO,
  mas o corte `>=2` ainda não foi confirmado pelo operador).

H8 e H9 reportam **`n_pessoas_pro`** (grupos distintos, `carteiras_pro.pessoas_presentes`) **e**
`n_carteiras_pro` (endereços distintos) nos dois — 121 carteiras são só 79 pessoas; nunca reportar só
a contagem de endereços.

## EMENDA 1 (2026-10-29) — robustez de H1, H10–H12, limitações

Pré-registrada **antes de qualquer análise sobre dados novos** (nenhuma coleta real rodou ainda sobre
o hash anterior deste checkout) — nova seção, nunca reescreve o texto das seções acima. A data e o novo
`sha256` deste arquivo são registrados em `meta` via `python -m signals_mvp.analise.condicional
--registrar-emenda` (histórico append-only em `meta['plano_analise_emendas']`), **antes** da próxima
`/analise`/coleta rodar — `garantir_plano_registrado` recusa com `PlanoAlteradoError` até isso ser feito.

### 1) Robustez de H1 (cauda pesada) — 3 desfechos, nunca mais PASS/FAIL

H1 (n>=30, sem ter parado por futilidade) agora tem **3 desfechos possíveis**: `EDGE_PROVISORIO`
(critérios (a)–(d) abaixo **todos** verdadeiros), `FUTIL` (regra já existente, inalterada) ou
`INCONCLUSIVO` (qualquer outro caso — falhar (b) ou (c) é **sempre** `INCONCLUSIVO`, nunca "refutado").

- **(a)** limite inferior de 90% do bootstrap em blocos > 0, **nos dois eixos** (dia E token) — regra
  já existente, inalterada.
- **(b)** estimativa **pontual** (sem exigir limite inferior aqui) da média de `dif_pareada` > 0 após
  remover o **único maior ganho individual** (leave-one-out do melhor trade) — um outlier isolado
  nunca pode sustentar "edge" sozinho.
- **(c)** teste de permutação por **inversão de sinais** (exato nas diferenças pareadas até n=20;
  Monte Carlo determinístico, seed fixa, acima disso) sobre a **média** das diferenças pareadas, com
  **p < 0,10**. A mediana das diferenças **não** entra como critério.
- **(d)** sobrevive ao cenário de custo conservador pré-declarado: `dif_pareada` recomputada com **3%
  de custo adicional por perna** (entrada+saída), **além** do que já está em `result_net`
  (`CostModel` oficial, intocado) — estimativa pontual > 0.

Também reportados (nunca decidem o status): **média aparada (10%)**; **nº de diferenças positivas /
total**.

**Escalar a mão** (aumentar o tamanho da posição) só é liberado com **n >= 100 tokens distintos
fechados OU p < 0,01 no teste de permutação** — mais uma vez, nunca decide `EDGE_PROVISORIO` por si
só, é uma trava adicional antes de qualquer ação operacional.

### 2) H10–H12 (família de Holm, geração de hipóteses, **não confirmatórias**)

- **H10** — velocidade da queda: correlação de **Spearman** (contínua, sem Pearson) entre o tempo
  (segundos) do PICO acumulado conhecido até o INÍCIO da caixa/zona e o **R REALIZADO** do sinal
  (não `dif_pareada` — pergunta distinta de H1–H9: aqui é sobre o resultado absoluto do trade, não o
  quanto ele bate a baseline).
- **H11** — ticket médio no gatilho: **Mann-Whitney U** comparando `dif_pareada` de abaixo vs acima
  da **mediana exata** de `ticket_medio_usd` (recalculada a cada execução).
- **H12** — ordem do sinal no token (`token_signal_seq`): 1º sinal vs 2º ou posterior, bootstrap em
  blocos **por token** (não por dia) — um token hiperativo que gera vários sinais seq>=2 correlacionados
  não pode inflar a significância desse lado.

Cada um entra na MESMA família de Holm que H2–H9 (um p-valor por teste/lado); `n < 10` tokens
distintos (por lado) não é reportado, mesma convenção de H2–H9.

**Colunas novas:** nenhuma foi necessária. `peak_ts`/`box_start_ts` (H10) já são gravados em
`event_json.data` pelo detector (`detector_v1.py: EventV1`, único ponto de construção, mesma classe
usada por V1 e V2) desde antes desta emenda; `ticket_medio_usd` e `token_signal_seq` (H11/H12) já são
colunas existentes em `pr1_signals`/`pr2_signals`.

### 3) Limitações registradas

- a baseline pareada mede o **timing do gatilho dentro de tokens já selecionados** pela V1/V2 (nunca
  contra uma amostra aleatória de tokens não selecionados) — H1–H12 respondem "o sinal bate a baseline
  do MESMO token", não "a V1/V2 escolhe tokens melhores que o acaso";
- MEV/sandwich **não está modelado** em nenhum lugar desta análise (nem no custo conservador do item
  (d), que é só um modelo de taxa/slippage adicional).

### 4) Implementação

`signals_mvp/analise/condicional.py`: critérios (a)–(d) (`rodar_h1`, `media_sem_maior_ganho`,
`teste_permutacao_sinais`, `media_custo_conservador`, `media_aparada`), H10–H12
(`h10_velocidade_queda`/`h11_ticket_medio`/`h12_ordem_sinal_token`, Spearman/Mann-Whitney implementados
sem scipy — não é dependência do projeto). `/analise` (`formatar_markdown`/`formatar_telegram`)
mostra os 4 critérios, a média aparada, as diferenças positivas/total e `escalar_liberado`. Testes
sintéticos em `tests/test_analise_condicional.py` (outlier de +50R não gera edge; edge plantado
distribuído é detectado) e verificação/teste anti-lookahead do mecanismo de controles
(`candidatos_elegiveis`, `evidencia.py`) em `tests/test_evidencia.py` — o `peak` usado para decidir
elegibilidade de um candle só acumula o máximo dos candles ANTERIORES a ele, nunca um valor que só é
conhecido depois.

## O que NÃO pode acontecer depois deste documento estar committado

- editar os limiares/grupos acima (nova interpretação = nova seção/versão, nunca reescrever o texto
  já em vigor quando a 1ª coleta/análise rodou);
- testar uma H9 (ou qualquer corte novo) depois de já ter visto o resultado das H1–H8 na mesma
  amostra — isso é uma hipótese NOVA, com pré-registro próprio;
- misturar `versao='v1'` com `versao='v2'` na mesma contagem/bootstrap;
- contar um grupo com n < 10 tokens distintos;
- rodar a análise antes do hash deste arquivo estar registrado em `meta` (`condicional.py` recusa).

## Como consultar

```bash
python -m signals_mvp.analise.condicional --versao v1
python -m signals_mvp.analise.condicional --versao v2
```

(recusa automaticamente abaixo de 30 sinais resolvidos para H1; H2–H8 reportam só os grupos com
n >= 10). Mesma recusa no Telegram via `/analise v1` ou `/analise v2`.
