# Emenda 2026-11-05 — item 3: proposta de avaliação por horizonte fixo (NÃO IMPLEMENTADA)

PAPER/READ-ONLY. **Proposta em texto apenas** — nenhum código foi escrito para esta seção. Emenda de
**ANÁLISE** (`analise/condicional.py`), nunca de parâmetros/detector/execução. Hashes `ParamsV1`/
`ParamsV2`/`ParamsV3` (`279b79ffa3f0`/`d57b4331d51d`/`56762db29cd6`) não são tocados por esta proposta.

## Problema que motiva a emenda (censura)

`carregar_sinais_e_excluidos` (ver item 1 na resposta final) só inclui sinais com `dif_pareada` já
**resolvida** — exige `signal["status"] == "fechado"` (`live.py: _atualizar_baseline`) E todos os
controles pareados resolvidos. `simulate_v1`/`simular_controle` não têm horizonte máximo (`while j <
len(bars) and remaining > 1e-12`): um trade fica `em_aberto` indefinidamente até estourar o stop, bater
o alvo, ou os candles acabarem. Resultado: H1, a regra de futilidade e todas as exploratórias de
`condicional.py` enxergam só os trades que JÁ fecharam — os que ainda estão correndo (tipicamente os
candidatos a maior vencedor, que só fecham quando a tendência se esgota) ficam de fora até fecharem.
Viés sistemático: perdedores fecham rápido (stop bate cedo) e entram logo na amostra; vencedores
demoram e são excluídos enquanto estão abertos — a amostra de qualquer corte no tempo é
desproporcionalmente perdedora, inflando a chance de FUTIL/INCONCLUSIVO cedo demais.

## Proposta

Adicionar, ao lado do R de saída por regra (inalterado, continua sendo o único usado por H1/futilidade
hoje), um **R marcado a mercado em horizontes FIXOS pré-registrados**: 72h e 7 dias após `t_entrada`,
para TODOS os sinais (fechados e em_aberto), reusando a mesma lógica já construída em `exit_lab.py:
_marcar_a_mercado` (último candle não-corrompido antes do horizonte, nunca inventa preço) — nenhuma
lógica nova de valorização, só aplicada a um corte de TEMPO fixo em vez de "até resolver". 72h casa com
a janela já coletada em `pr_trajetoria` (zero coleta nova); 7d é um segundo corte, mais generoso, para
ver se o sinal do 72h se sustenta. Sinal/candle corrompido no instante do corte → `None` explícito,
nunca estimado.

Nunca substitui o R de saída por regra — os dois ficam lado a lado, sempre rotulados (`r_regra` vs.
`r_horizonte_72h`/`r_horizonte_7d`), igual ao padrão de visão dupla já adotado no item 1.

## Efeito em N=30 / H1 / regra de futilidade

- **N (tokens distintos)**: hoje só conta quando `dif_pareada` resolve (pode levar dias para o universo
  "fechado" crescer). Com horizonte fixo, um token entra na contagem 72h depois da entrada, estourando
  stop ou não — N chega a 30 mais rápido e sem o viés de excluir os que ainda correm.
- **Regra de futilidade** (`MIN_TOKENS_FUTILIDADE=15`, `LIMITE_FUTILIDADE_R=-0.5`): mesmos limiares,
  aplicados ao R de horizonte em vez de `dif_pareada` resolvido — julga a MESMA safra de tokens, não só
  os que já fecharam, reduzindo a chance de disparar FUTIL só porque a amostra madura é
  desproporcionalmente de perdedores rápidos.
- **H1** (bootstrap, critérios a-d): método idêntico, só troca o valor de entrada (R de horizonte em vez
  de `dif_pareada`); `MIN_TOKENS_H1=30` e os 4 critérios continuam exatamente como estão.

## Riscos

1. R de horizonte **não é o mesmo objeto econômico** que R de saída por regra — um trade que o stop
   real teria fechado a -1R na hora 10 pode mostrar +3R aos 72h se o preço recuperou depois (caminho que
   a regra real nunca percorreria). Nunca pode substituir o R de saída por regra em H1/futilidade "de
   verdade" — só acompanha, rotulado, até uma decisão formal do operador.
2. Exige registro formal ANTES de qualquer coleta (este documento É a pré-registração, datada) — rodar
   sem isso violaria a disciplina do registro de hipóteses (`docs/research-hypothesis-registry-v1-2026-10-04.md`).
3. Candle corrompido/ausente exatamente no instante do corte (72h/7d) precisa ficar `None` — nunca
   interpolado, sob pena de reintroduzir viés pela porta dos fundos.
4. Dois horizontes = mais testes = mais ajuste multiplicidade se usados para decidir algo — continuariam
   sob a disciplina de Holm-Bonferroni se algum dia promovidos a exploratória, nunca confirmatórios por
   si só.

**Esta proposta não foi implementada.** Requer autorização explícita do operador + linha no registro de
hipóteses antes de qualquer código/coleta.
