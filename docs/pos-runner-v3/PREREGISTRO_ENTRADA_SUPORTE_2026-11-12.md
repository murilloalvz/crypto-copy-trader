# Pré-registro 2026-11-12 — "entrada no suporte" (variante de ENTRADA, EXPLORATÓRIA, causal, sem lookahead)

PAPER/READ-ONLY. V3 roda com regras CONGELADAS (`ParamsV3=56762db29cd6`) — este documento e o módulo
`pos_runner/entrada_suporte.py` NUNCA alteram detector/simulate/parâmetros/H1/critério de sinal da
V3. Diferente da "saída fiel" (rodada 12), esta é uma variante de **QUANDO ENTRAR**, nunca de gestão
pós-entrada — a saída usada para julgá-la é a **MESMA saída A oficial** (`horizonte_fixo.
calcular_r_horizonte`), já usada em todo o resto do projeto, nunca uma saída nova.

## Por que este documento existe, e por que NÃO é um pré-registro "a frio"

Pedido explícito (rodada 18, item 3): esta hipótese é **motivada por achados já vistos** — o
pareamento por TOQUE da rodada 11 (B4, toque pareado médio **−0,14R**) sugeriu que a entrada oficial
da V3 (no gatilho/confirmação) pode entrar tarde demais relativamente a controles pareados na mesma
fase. Isto é dito aqui **explicitamente, nunca escondido**: o algoritmo abaixo **não é cego** em
relação aos dados já coletados — por isso é **EXPLORATÓRIO** (nunca confirmatório), **NUNCA entra no
N=30 nem na H1** (`docs/research-hypothesis-registry-v1-2026-10-04.md` continua sendo a única
autoridade para isso), e qualquer promoção a hipótese formal exigirá um pré-registro **novo e
próprio**, julgado sobre coleta **ainda não vista**.

## Algoritmo exato (congelado por hash — `garantir_entrada_suporte_registrada`, nunca editado em
silêncio depois de registrado; qualquer mudança abre uma emenda datada nova)

**Universo**: os MESMOS pools/janelas dos sinais V3 já carregados por `ao_vivo`/`retro_lote1`/
`replay_v3` (`scripts/retrospectivo_saida_fiel.carregar_ao_vivo`/`scripts/varredura_v3.
carregar_retro_lote1`/`carregar_universo_admitido`) — SEPARADOS, nunca somados, mesma disciplina do
resto do projeto.

1. **Reconstrução causal da caixa**: para cada sinal V3 real `s` (já decidido pelo detector oficial,
   gatilho em `s.ev.idx`, zona `s.ev.data["zona"]`), *reexecuta* `DetectorV1` (MESMA classe, MESMOS
   `ParamsV3` congelados, MESMOS `bars`/`l_bc`/`created_ts` do sinal real — `grad_ts=None`, campo que
   só afeta `idade_grad_dias`/atributo, nunca a mecânica de zona/gatilho) candle a candle, 0..
   `s.ev.idx - 1`. Isto reproduz, determinística e byte-a-byte, a MESMA sequência causal de eventos
   (`RUNNER`/`FASE2`/`TESTE`/`WATCHLIST`/`ENTRADA`) que gerou o sinal real — nenhuma informação nova,
   zero chamada de rede, zero mudança no detector.
2. **"Caixa formada"** = o candle do evento `WATCHLIST` da MESMA zona (`zona == s.ev.data["zona"]`) —
   primeira vez que a zona atinge `zone_min_candles` candles E o nº de testes (pavios) está entre
   `wicks_min` e `wicks_max`. Índice `i_watchlist`.
3. **"Revisita ao suporte S" (ou fundo da caixa — NESTE detector, S já É, por construção, a mínima
   observada na zona, i.e. o fundo da caixa — não são 2 conceitos diferentes)**: candil `i` com
   `i_watchlist < i < s.ev.idx` cujo `low <= S(i) × (1 + test_zone)` — MESMA banda de tolerância já
   usada pelo detector oficial para reconhecer um teste de suporte (`test_zone`, `ParamsV3`), onde
   `S(i)` é o valor de `zone.S` *no momento* (replay incremental, candle a candle — nunca o valor
   final/futuro de S). Candles consecutivos que permanecem dentro da banda contam como **UMA** única
   revisita (decidida no PRIMEIRO candle que entra na banda); a revisita termina quando um candle
   fecha a banda (`low >` banda) — a próxima vez que `low` voltar a tocar a banda é uma NOVA revisita.
   A **primeira** revisita nessas condições é o ponto de entrada desta hipótese; revisitas
   seguintes (se houver, ainda antes do gatilho real) alimentam a comparação (c) abaixo.
4. **Stop** = `S(i) × (1 - stop_below_wick_pct)` — MESMA fórmula oficial do stop da V3
   (`min_wick_low × (1 - stop_below_wick_pct)`), aplicada aqui a `S(i)` (que já é, por definição, a
   mínima observada na zona até e incluindo o candle da revisita — "o menor pavio" até este ponto).
   Nunca um valor de stop novo/inventado.
5. **Entrada**: decidida no FECHAMENTO do candle da revisita, executada no ABERTURA do candle
   seguinte (MESMA convenção causal do resto do projeto — `_montar_sinal`/`simulate_v1`). `TOPO` =
   `s.ev.data["TOPO"]` (o MESMO topo/P_peak do sinal real — mesma onda, nunca recalculado). Entrada
   descartada (nunca um trade) se `entry_price <= 0` ou `entry_price <= stop` ou `entry_price >=
   TOPO` — MESMA regra de descarte de `_montar_sinal`, reusada sem duplicação.
6. **Candle corrompido**: MESMO veto configurável da rodada 18 item 2 (`simples`/`amplo`, aplicado
   via `varredura_v3._montar_sinal(..., veto=veto)` reusado sem duplicação) decide a correção de
   entrada; nunca uma lógica de veto nova.
7. **Saída**: EXATAMENTE a saída A oficial (`horizonte_fixo.calcular_r_horizonte`, MESMOS custos
   `CostModel`, MESMO horizonte fixo 72h/7d) — zero saída nova criada para esta hipótese.
8. **Elegibilidade**: um sinal sem evento `WATCHLIST` reconstituído para sua própria zona, ou sem
   NENHUMA revisita nas condições do passo 3, é **NÃO ELEGÍVEL** para esta hipótese — fica de fora da
   amostra, explicitamente contado como tal, NUNCA inventado/aproximado.

## Comparações (pedido explícito, mesmos dados, mesma saída A)

- **(a) o sinal V3 do mesmo pool**: `calcular_r_horizonte` aplicado à entrada OFICIAL (`s.ev`,
  `s.entry_price`/`s.stop`) do MESMO sinal — nenhuma mudança, é o número já reportado em todo o resto
  do projeto.
- **(b) entradas aleatórias no mesmo pool/fase**: reusa, SEM duplicar, o comparador K=20 já existente
  (`varredura_v3._aleatorios_indices`/`_evento_controle_sinal` — MESMA elegibilidade de fase/MESMA
  distância relativa de stop do sinal real), com a MESMA saída A.
- **(c) a mesma regra em outros instantes**: as revisitas SEGUINTES à primeira (passo 3), dentro da
  MESMA caixa, ainda antes do gatilho real — MESMA regra de entrada/stop/saída, só o instante muda.
  Quando não houver revisita seguinte, a comparação (c) fica vazia para aquele sinal (nunca
  inventada).

## Métricas reportadas

R@72h/R@7d a mercado (saída A), toque causal +2R/+5R antes de -1R (reusa
`varredura_v3._toque_causal`/`_primeiro_toque`, MESMA mecânica), distância do stop em % (`risk_frac`
da entrada no suporte), nº de sinais elegíveis e nº de tokens distintos, bootstrap por token (10k
reamostras, semente fixa — `analise.condicional.N_BOOTSTRAP_PADRAO`/`SEED_PADRAO`, reusado sem
duplicar), e o poder estatístico honesto da amostra elegível (MESMA fórmula MDE normal-aproximada já
usada em `docs/pos-runner-v3/EMENDA_2026-11-05_PODER_ESTATISTICO_N30.md`, reaplicada ao desvio-padrão
observado AQUI — nunca ao N=30 da H1).

## O que esta hipótese NÃO faz

- Não altera o detector, os parâmetros congelados, o critério de sinal ou a saída oficial da V3.
- Não decide nada por si — zero capital, zero vagas, zero alertas reais, zero escrita em
  `pr3_signals`/alertas/trajetória.
- **NUNCA entra no N=30 nem na H1** (`docs/research-hypothesis-registry-v1-2026-10-04.md` continua
  sendo a única autoridade formal) — é motivada por achados já vistos (toque pareado −0,14R, B4),
  logo é, na melhor das hipóteses, uma segunda medição descritiva sobre a mesma amostra/achado que a
  motivou, nunca uma confirmação independente.
- Não compara com a "saída fiel" (rodada 12) nem com a grade de 24 variantes (rodada 13) — é uma
  hipótese de ENTRADA isolada, julgada com a saída A oficial, para separar o efeito da entrada do
  efeito da gestão/saída (mesmo racional de desenho de `retrospectivo_saida_fiel.py`, invertido: lá
  a entrada é fixa e a saída varia; aqui a saída é fixa e a entrada varia).

## Riscos e viés documentados (nunca escondidos)

- **Motivada por dados já vistos** (ver seção acima).
- **Dentro da amostra**: usa os mesmos candles/pools já disponíveis.
- **Viés de sobrevivência**: mesmo universo das rodadas anteriores — só alcança tokens que o
  bot/GeckoTerminal ainda indexam.
- **Elegibilidade reduz N**: sinais sem revisita pós-formação-da-caixa (muito comum se os únicos
  pavios que maturaram a caixa já ocorreram ANTES do `WATCHLIST`) são excluídos — o N elegível desta
  hipótese é esperado ser MENOR que o universo total de sinais V3, nunca inflado para compensar.
- **Poder estatístico**: dado o N tipicamente pequeno e já reduzido por elegibilidade, o poder para
  detectar diferenças reais é provavelmente baixo — reportado explicitamente, nunca escondido atrás
  de um "sem diferença significativa" sem contexto.

## Status

**PRÉ-REGISTRADO em 2026-11-12, antes de qualquer execução do módulo
`pos_runner/entrada_suporte.py` ou do script `scripts/avaliar_entrada_suporte.py` sobre este
algoritmo exato.** Qualquer mudança no algoritmo acima, depois de ver resultado, abre uma nova
emenda datada — nunca reescreve este texto em silêncio (`garantir_entrada_suporte_registrada` recusa
com `PreregistroAlteradoError` se o arquivo mudar depois do primeiro registro).
