# Emenda 2026-11-10 — opção A: futilidade antecipada e critério (b) para a estratégia de cauda (V3)

PEDIDO 2026-11-10 (rodada 14, autorizado). **TEXTO E HASH APENAS — nenhum código, detector,
parâmetro ou hash de `ParamsV1`/`ParamsV2`/`ParamsV3` (`279b79ffa3f0`/`d57b4331d51d`/`56762db29cd6`)
é tocado.** Esta emenda formaliza a "opção A" de gestão de futilidade/critério (b) para a H1 da V3
("segunda corrida pós-queda", a estratégia de cauda — registro formal em
`docs/research-hypothesis-registry-v1-2026-10-04.md`), cuja robustez (EDGE_PROVISORIO/FUTIL/
INCONCLUSIVO, critérios a-d) já é citada como **"mesma robustez da Emenda 1 de
`PLANO_ANALISE_PREREGISTRADO.md`"** — por isso esta emenda vive aqui, no mesmo documento vivo que
`EMENDA 1` já amenda, e é registrada pela MESMA disciplina (`garantir_plano_registrado`/
`registrar_emenda`, hash em `meta['plano_analise_emendas']`).

## Escopo — NUNCA altera V1/V2

Esta emenda é **exclusiva da H1 da V3** (a estratégia de cauda). A regra de futilidade de V1/V2
(`PLANO_ANALISE_PREREGISTRADO.md`, seção "H1 — primária", item 1: n=15, média de `dif_pareada`
< −0,5R) e o critério (b) da `EMENDA 1` **continuam em vigor, inalterados, para V1 e V2**. Nenhuma
seção anterior deste documento é reescrita — esta é uma seção nova, que se aplica só à H1 da V3.

## Declaração explícita (pedido do operador): NÃO é uma emenda "a frio"

Esta emenda é **motivada diretamente** pelos achados já vistos nas rodadas anteriores:

- `docs/pos-runner-v3/EMENDA_2026-11-05_FUTILIDADE_ESTRATEGIA_CAUDA.md` (05/11): disclosure de que a
  regra atual de futilidade (n=15, −0,5R) mata até 46,3% das réplicas genuinamente lucrativas de uma
  estratégia de cauda, e que o critério (b) (leave-one-out de 1 trade) falha em 41-81% das réplicas
  lucrativas em n=30.
- `docs/pos-runner-v1/PROPOSTA_EMENDA_2026-11-06_FUTILIDADE_CRITERIO_B_CAUDA.md` (06/11): proposta
  (texto, não implementada) de futilidade por teste binomial contra taxa de acerto mínima e critério
  (b) por teto de contribuição por token.
- Retrospectivo não-condicionado da "saída fiel" (10/11, rodada 12/13) e a grade de saídas parciais
  (rodada 13) — ambos já viram os sinais reais `ao_vivo`/`retro_lote1`/`replay_v3` sob múltiplas
  variantes de gestão de saída.

Isto é dito aqui **explicitamente, nunca escondido**: por isso, **os 10 sinais vencidos já vistos ao
vivo e todo o universo `retro_lote1`/`replay_v3` já replayado nas rodadas 11-13 NUNCA podem julgar
esta regra** — qualquer olhada formal (N=30/N=60, abaixo) só conta a partir de sinais/replay **ainda
não vistos sob este hash** (ou seja, coletados/replayados **depois** do registro desta emenda em
`meta`). Reusar o que já foi olhado seria o próprio problema que o registro de hipóteses existe para
evitar (`docs/research-hypothesis-registry-v1-2026-10-04.md`: "o que já foi visto nunca pode julgar
a si mesmo").

## 1) Futilidade antecipada SUSPENSA (nunca substituída por corte de 5%)

A regra de futilidade antecipada herdada (n=15, média de `dif_pareada` < −0,5R) fica **SUSPENSA**
para a H1 da V3 — não dispara mais em n=15, nem em nenhum ponto intermediário. **Isto não é
substituído por um corte de taxa de acerto fixa de 5%** (a proposta do item 1 de
`PROPOSTA_EMENDA_2026-11-06_FUTILIDADE_CRITERIO_B_CAUDA.md` fica só proposta — nunca adotada aqui,
por decisão explícita do operador nesta rodada). Em vez disso, a decisão de futilidade passa a
acontecer só nos pontos de olhada fixos abaixo (item 6).

## 2) Pontos de olhada FIXOS: N=30 e N=60 tokens distintos

A H1 da V3 só é avaliada formalmente em exatamente **2 pontos**: **N=30** e **N=60** tokens
distintos resolvidos (primeira tentativa por token como unidade — `token_signal_seq==1`, mesma
convenção já usada em `varredura_v3.calcular_token_signal_seq`, rodada 10 item 2; reentradas
`token_signal_seq>=2` ficam de fora da contagem de N e só entram como uma análise SEPARADA,
diagnóstica, nunca somada à primária). **Nenhuma olhada intermediária decide** — entre N=30 e N=60,
e depois de N=60, o resultado pode ser reportado como acompanhamento, mas nunca gera um desfecho
formal (`EDGE_PROVISORIO`/`FUTIL`/`INCONCLUSIVO`) fora desses 2 pontos.

## 3) Desfecho primário INALTERADO

`dif_pareada` média (R@72h marcado a mercado — `horizonte_fixo.calcular_r_horizonte`, mesma
convenção do resto do projeto; sinal **pendente nunca excluído**, fica fora da contagem de N até
resolver) continua o desfecho primário, com IC bootstrap por token (10k reamostras, semente fixa) e a
correção **Bonferroni α/2 entre V1 e V3** já pré-registrada (`PREREGISTRO_V3_2026-11-02.md`,
`EMENDA_2026-11-05_PODER_ESTATISTICO_N30.md`) — nada disso muda.

## 4) Secundário (diagnóstico, nunca decide sozinho)

`P(+NR antes de −1R)` por token, reportado para `N ∈ {5, 10, 15, 20}` (subconjunto dos alvos já
estendidos em `varredura_v3.ALVOS_R`, rodada 12 Parte 4b), comparado contra (i) o equilíbrio TEÓRICO
`100/(1+N)%` e (ii) o equilíbrio EMPÍRICO dos controles pareados e das entradas aleatórias (K=20,
MESMA mecânica de `varredura_v3.calcular_equilibrio_empirico`) — nunca decide `EDGE_PROVISORIO`/
`FUTIL` por si só (mesma hierarquia já estabelecida em B6/rodada 9: "terceiro, apenas diagnóstico").

## 5) Critério (b) da EMENDA 1 vira DIAGNÓSTICO NÃO-BLOQUEANTE

O critério (b) ("estimativa pontual da média de `dif_pareada` > 0 após remover o único maior ganho
individual") **deixa de bloquear `EDGE_PROVISORIO`** para a H1 da V3. Em vez de decidir, (b) passa a
ser **reportado como diagnóstico**: (i) leave-one-token-out (pior caso — média recalculada removendo,
um por vez, TODOS os valores de cada token, reportando o mínimo; MESMA mecânica de
`grade_saidas_parciais._leave_one_token_out_pior_caso`, rodada 13), e (ii) concentração por token (%
da soma positiva de `dif_pareada` que vem do token que mais contribui). Os critérios **(a), (c) e
(d) permanecem EXATAMENTE como já pré-registrados** (limite inferior do IC nos dois eixos; permutação
por inversão de sinais, p<0,10; custo conservador +3%/perna) — só (b) deixa de bloquear.

## 6) FUTIL só em N=60; N=30 com poder já calculado

- **Em N=30**: `EDGE_PROVISORIO` se os critérios (a)/(c)/(d) (nunca mais (b), item 5) passarem — mas
  **o resultado esperado em muitos cenários realistas é `INCONCLUSIVO`**, nunca `FUTIL` (a suspensão
  do item 1 garante isso). Isto é dito aqui em texto, **com o poder já calculado**: MDE (diferença
  mínima detectável, 80% de poder) ≈ **1,21R sem correção / 1,37R com Bonferroni α/2** —
  exatamente o número já publicado em `docs/pos-runner-v3/EMENDA_2026-11-05_PODER_ESTATISTICO_N30.md`
  (reusado aqui, nunca recalculado com um número novo). Um efeito real, mas modesto (< ~1,2-1,4R),
  **não deveria** ser detectável com confiança em N=30 — `INCONCLUSIVO` nesse cenário é o
  comportamento ESPERADO e correto, não uma falha do método.
- **Em N=60**: `FUTIL` dispara **só** se o limite **SUPERIOR** do IC bootstrap por token da
  `dif_pareada` (no mesmo nível de confiança já corrigido por Bonferroni α/2 — IC95% de 2 caudas,
  não IC90%, dando o one-sided 97,5% usado pelo critério (a) corrigido) for **< 0**. Isto é o
  complemento natural do critério (a) (que exige o limite INFERIOR > 0 pra `EDGE_PROVISORIO`): só
  quando até o cenário mais favorável do bootstrap já é negativo é que a estratégia é declarada
  genuinamente fútil — nunca por falta de sorte cedo (o próprio disclosure de 05/11 já mostrou que
  isso mata até 46% das réplicas lucrativas). Entre N=30 e N=60 sem atingir nenhum dos dois limites:
  `INCONCLUSIVO`, nunca promovido nem descartado.

## 7) Portão de dinheiro real — INALTERADO

Nenhuma mudança no portão de escalar a mão/liberar capital: continua exigindo **n >= 100 tokens
distintos fechados OU p < 0,01 no teste de permutação**, mais todos os demais critérios já
pré-registrados (incluindo (a)/(c)/(d), agora sem (b) como bloqueante — item 5). Nenhum capital real
é liberado antes disso, independente do desfecho em N=30/N=60.

## 8) Trade-off explícito (nunca escondido): o custo é tempo, não dinheiro

Suspender a futilidade antecipada e mover a 1ª decisão formal de n=15 para N=30 (e a única decisão
de `FUTIL` para N=60) significa que a estratégia roda em paper por **mais tempo** antes de poder ser
formalmente declarada fútil — mais sinais precisam resolver (até 72h/7d cada) antes de qualquer
decisão. Como esta é uma estratégia 100% PAPER (zero capital, zero execução real), **o custo dessa
espera é só tempo de coleta/observação, nunca dinheiro** — é exatamente a troca que o disclosure de
05/11 já quantificou como necessária pra não matar por acaso uma estratégia de cauda genuinamente
lucrativa.

## O que esta emenda NÃO faz

- Não altera V1/V2 — a regra de futilidade (n=15, −0,5R) e o critério (b) da `EMENDA 1` continuam
  em vigor, inalterados, pra essas duas versões.
- Não altera detector, simulador, parâmetros (`ParamsV1`/`ParamsV2`/`ParamsV3`) nem seus hashes.
- Não substitui a futilidade suspensa por um corte de taxa de acerto fixo (a proposta de 06/11 fica
  só proposta, nunca adotada nesta emenda).
- Não promove nenhum resultado a `EDGE_PROVISORIO`/`VALIDADA` — ainda exige os 3 passos do registro
  de hipóteses (PASS pré-registrado, PASS numa replicação fresca, líquido de custos positivo no
  Gate 2) antes de qualquer promoção formal.
- Não julga esta regra pelos 10 vencidos ao vivo nem pelo `retro_lote1`/`replay_v3` já vistos nas
  rodadas 11-13 — só coleta/replay posterior ao registro do hash desta emenda conta pra N=30/N=60.
- Não implementa código nesta rodada — é texto e hash apenas; a implementação de N=30/N=60/critério
  (b) diagnóstico/FUTIL-em-N=60 para a H1 da V3 fica para uma rodada futura, explicitamente pedida.

## Status

**EMENDA registrada em 2026-11-10**, antes de qualquer coleta/replay nova contar pra N=30/N=60 da
H1 da V3. A data e o novo `sha256` de `PLANO_ANALISE_PREREGISTRADO.md` (que ganha a seção "EMENDA 4"
referenciando este documento) são registrados em `meta['plano_analise_emendas']` via
`python -m signals_mvp.analise.condicional --registrar-emenda`, **antes** de qualquer nova
coleta/análise rodar — `garantir_plano_registrado` recusa com `PlanoAlteradoError` até isso ser
feito. Qualquer mudança nesta conta, depois de ver mais resultados, abre uma NOVA emenda datada —
nunca reescreve este texto em silêncio.
