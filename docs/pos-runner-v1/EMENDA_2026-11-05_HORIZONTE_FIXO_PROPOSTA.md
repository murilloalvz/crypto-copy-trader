# Emenda 2026-11-05 — item 3: avaliação por horizonte fixo (AUTORIZADA, texto congelado por hash)

PAPER/READ-ONLY. Emenda de **ANÁLISE** (`analise/condicional.py`, `pos_runner/horizonte_fixo.py`),
nunca de parâmetros/detector/execução. Hashes `ParamsV1`/`ParamsV2`/`ParamsV3`
(`279b79ffa3f0`/`d57b4331d51d`/`56762db29cd6`) não são tocados.

**Motivação e cronologia**: esta emenda foi motivada pelo achado do `exit_lab` (viés de censura: A
passa de -1,11R para -0,31R no replay V3 ao valorizar a mercado os trades ainda `em_aberto`) e é
escrita e congelada **ANTES de acumular mais dados em `pr_baseline`/H1** — pré-registro no sentido
estrito: a regra abaixo é fixada agora, por hash (`pos_runner/horizonte_fixo.py:
garantir_emenda_registrada`, mesmo padrão de `analise.condicional.garantir_plano_registrado`), e não
pode ser reeditada depois de qualquer coleta real sem abrir uma nova emenda.

**Autorização 2026-11-05 (substitui a cautela do rascunho original)**: o rascunho anterior desta
emenda tratava R de horizonte e R de saída por regra como estritamente paralelos, "nunca substituindo"
um ao outro, e deixava a promoção do R de horizonte a desfecho de H1 condicionada a uma "decisão
formal do operador" (risco nº1 do rascunho). Essa decisão foi dada explicitamente nesta rodada: o R de
horizonte passa a ser o **desfecho primário** de H1/controles/futilidade; o R de saída por regra
continua reportado, mas como **secundário**, e é agora tratado explicitamente como **censurado** (o
problema que esta emenda existe para corrigir).

## Problema que motiva a emenda (censura)

`carregar_sinais_e_excluidos` (ver item 1 da resposta anterior) só inclui sinais com `dif_pareada` já
**resolvida** — exige `signal["status"] == "fechado"` (`live.py: _atualizar_baseline`) E todos os
controles pareados resolvidos. `simulate_v1`/`simular_controle` não têm horizonte máximo: um trade fica
`em_aberto` indefinidamente até estourar o stop, bater o alvo, ou os candles acabarem. Perdedores
fecham rápido (stop bate cedo) e entram logo na amostra; vencedores demoram e são excluídos enquanto
correm — a amostra de qualquer corte no tempo é desproporcionalmente perdedora.

## Desfecho primário: R valorizado a mercado em 72h

Para TODO sinal (ao vivo, retro, replay) e todo controle pareado, calculado a partir de
`t_entrada`/`idx` do controle, em `horizonte = 72h` (e, como secundário adicional, `7d`):

- **Horizonte ainda não decorrido** (`agora < t_entrada + horizonte`) → status `pendente`. Nunca
  excluído, nunca contado como perda — simplesmente fica fora de qualquer média/H1 até o horizonte
  passar.
- **A regra já havia fechado 100% da posição antes do corte** → R de horizonte = R REALIZADO da regra
  (mesmo valor, sem reinterpretação).
- **Senão** (a regra ainda estava com fração aberta no instante do corte, tivesse ela fechado depois ou
  nunca) → marca a fração ainda aberta no instante do corte no último candle LIMPO <= corte (reusa
  `scripts/exit_lab.py: _marcar_a_mercado`, mesma checagem de qualidade de candle do item 1), combinada
  com qualquer perna já realizada ANTES do corte (nunca lookahead: a série de candles é truncada no
  corte antes de simular — uma perna que a regra real só executaria depois do corte não é "conhecida"
  nesse instante).
- **Candle corrompido/ausente em toda a série até o corte** → `pendente` (nunca marcado com dado ruim,
  nunca inventado).
- **Preço de abertura fora do stop/TOPO no próprio candle de entrada** (posição nunca válida) →
  `sem_dado`, fora de qualquer amostra.

R de horizonte entra em H1/controles/futilidade SOMENTE quando resolvido ou marcado (nunca quando
`pendente`/`sem_dado`) — mesma disciplina de missingness explícito do resto do projeto.

## Secundário (censurado): R de saída por regra

Continua calculado e reportado lado a lado (nunca descartado), mas agora rotulado explicitamente como
**censurado**: só existe quando o sinal/controle JÁ fechou pela regra, e por isso não serve mais de
desfecho primário de H1 — é o objeto que motivou esta emenda.

## Efeito em N=30 / H1 / regra de futilidade

- **N (tokens distintos)**: hoje só conta quando `dif_pareada` (regra) resolve. Com horizonte fixo, um
  token entra na contagem 72h depois da entrada, estourando stop ou não — N chega a 30 mais rápido, sem
  excluir os que ainda correm.
- **Regra de futilidade** (`MIN_TOKENS_FUTILIDADE=15`, `LIMITE_FUTILIDADE_R=-0.5`): MESMOS limiares,
  agora aplicados ao `dif_pareada` de 72h (sinal de 72h − média dos controles de 72h) em vez do
  `dif_pareada` de regra — julga a MESMA safra de tokens madura em 72h, não só os que já fecharam pela
  regra.
- **H1** (bootstrap, critérios a-d): `rodar_h1` (função) fica byte a byte intocada — só recebe uma lista
  de sinais com `dif_pareada` calculada no horizonte em vez de na regra, atrás de uma flag nova em
  `carregar_sinais_e_excluidos(..., horizonte="72h")`; o padrão (`horizonte=None`) continua idêntico ao
  legado. `MIN_TOKENS_H1=30` e os 4 critérios continuam exatamente como estão.

## Riscos

1. R de horizonte não é o mesmo objeto econômico que R de saída por regra — um trade que o stop real
   teria fechado a -1R na hora 10 pode mostrar +3R aos 72h se o preço recuperou depois (caminho que a
   regra real nunca percorreria). Por isso o R de regra continua reportado (secundário/censurado),
   nunca removido do relatório.
2. Candle corrompido/ausente exatamente no instante do corte precisa ficar `pendente`/sem valor — nunca
   interpolado.
3. Dois horizontes (72h/7d) = duas janelas fixas pré-registradas; nenhuma delas pode ser trocada depois
   de ver resultados — se outro horizonte parecer "melhor" depois da coleta, isso é uma observação
   exploratória nova, nunca uma correção deste pré-registro.
4. `pr_horizonte_fixo` (ao vivo/retro/replay) e o `controles_json` de `pr_baseline` não têm, por
   natureza, horizonte máximo na simulação (mesma ausência de teto do `simulate_v1`/`simular_controle`
   original) — o "corte" é só o instante em que MEDIMOS o R, nunca um teto na simulação em si.

**Implementação autorizada em 2026-11-05.** Texto congelado por hash em `meta` (`pos_runner/
horizonte_fixo.py: garantir_emenda_registrada`) antes de qualquer cálculo real; uma edição deste texto
depois do registro recusa (`EmendaAlteradaError`) até uma nova emenda ser aberta.
