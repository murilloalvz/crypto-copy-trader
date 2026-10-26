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

- **H8** — `carteiras_pro_presentes` (>= 1 vs 0): a coluna existe (nullable, sempre `NULL` nesta
  entrega — a coleta da lista de carteiras "pro" ainda não existe). **H8 fica "não testada" e fora do
  Holm** até ter n >= 10 por grupo com dado não-nulo; a lista de carteiras será fixa e versionada
  (hash do arquivo) antes de qualquer coleta, num pedido futuro.

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
