# Pré-registro 2026-11-12 — sombra FORWARD "entrada no suporte" (EXPLORATÓRIA, causal, sem lookahead)

PAPER/READ-ONLY. V3 roda com regras CONGELADAS (`ParamsV3=56762db29cd6`) — este documento e o módulo
`pos_runner/entrada_suporte.py` (função `garantir_suporte_forward_registrada`) NUNCA alteram
detector/simulate/parâmetros/H1/critério de sinal. Esta é uma coleta **FORWARD** (dados AINDA NÃO
VISTOS, gravados ao vivo a partir de agora) — **DIFERENTE e SEPARADA** do retrospectivo dentro-da-
amostra já entregue na rodada 18 (`PREREGISTRO_ENTRADA_SUPORTE_2026-11-12.md`,
`scripts/avaliar_entrada_suporte.py`), que continua valendo só como motivação/descrição, nunca como
evidência confirmatória desta coleta nova.

## Por que este documento existe, e por que NÃO é um pré-registro "a frio"

Motivado por achados já vistos: (1) o retrospectivo dentro-da-amostra (rodada 18) e (2) o pareamento
por TOQUE da rodada 11 (B4, toque pareado médio −0,14R). Isto é dito aqui **explicitamente**: o
algoritmo abaixo não é cego em relação aos dados já vistos — por isso é **EXPLORATÓRIO** (nunca
confirmatório), **NUNCA entra no N=30 nem na H1** (`docs/research-hypothesis-registry-v1-2026-10-04.md`
continua a única autoridade formal para isso), e qualquer promoção a hipótese formal exigirá um
pré-registro **novo e próprio**, julgado sobre uma coleta **ainda mais nova** que esta.

## Algoritmo exato (congelado por hash — `garantir_suporte_forward_registrada`, nunca editado em
silêncio depois de registrado; qualquer mudança abre uma emenda datada nova)

**Universo**: TODO pool V3 ATIVO (qualquer `(pool, tf)` com um `DetectorV1` da V3 vivo em `live.py`),
gravado ao vivo a partir do momento em que este pré-registro for aceito — nunca recalculado sobre
histórico já fechado (isso seria o retrospectivo da rodada 18, não esta coleta).

1. **Caixa formada**: evento `WATCHLIST` da zona (MESMA definição oficial — `zone_min_candles`/
   `wicks_min`/`wicks_max` já congelados em `ParamsV3`).
2. **1ª revisita ao suporte S (= fundo da caixa)**: candle, estritamente depois do `WATCHLIST` e antes
   do gatilho real (se e quando ele existir), cujo `low <= S × (1 + test_zone)` — MESMA definição do
   retrospectivo (`entrada_suporte.localizar_revisitas_suporte`, reusada sem duplicar lógica; aqui
   chamada ao vivo, candle a candle, sem um `gatilho_idx` futuro conhecido — scaneia só o que já
   existe no momento). Candles consecutivos dentro da banda contam como UMA revisita só.
3. **Stop** = `S × (1 - stop_below_wick_pct)` — MESMA fórmula oficial, aplicada ao S no momento da
   revisita.
4. **Entrada hipotética**: decidida no FECHAMENTO do candle da revisita, preço = ABERTURA do candle
   SEGUINTE (MESMA convenção causal de todo o projeto). Descartada (nunca gravada) se
   `entry_price <= 0` ou `entry_price <= stop` ou `entry_price >= TOPO` (TOPO = `P_peak` da onda no
   momento, `det.peak`).
5. **Candle corrompido**: veto AMPLO (padrão desta coleta — `qualidade_candle.candle_confiavel_cb`,
   mesma função já em produção desde a rodada 17) decide a correção de entrada.
6. **Gravação** (`pr3_suporte_sombra`, 1 linha por `(pool, tf, zona)` — nunca mais de 1 revisita
   gravada por zona, mesma invariante "uma decisão por zona" do detector oficial): instante da
   revisita, preço de entrada hipotético, stop, distância do stop em %, volume do candle da revisita,
   idade do pool (dias desde a criação on-chain). **NUNCA gera alerta nem sinal** — zero linha em
   `pr3_signals`, zero mensagem Telegram, zero efeito em banca/capital.
7. **Acompanhamento** (`pr3_suporte_sombra_saida`, recomputado TODO ciclo, idempotente — MESMA
   disciplina de `pr3_saidas_sombra`): para cada horizonte fixo (72h/7d), a MESMA saída A oficial
   (`horizonte_fixo.calcular_r_horizonte`) marcada a mercado se o horizonte ainda não decorreu
   (`pendente`, NUNCA excluído/contado como perda) e o toque causal +2R/+5R antes de −1R
   (`varredura_v3._toque_causal`, mesma mecânica).
8. **Controle**: K=20 entradas aleatórias do MESMO pool/fase (reusa `pos_runner/evidencia.py`:
   `candidatos_elegiveis`/`sortear_controles`/`evento_controle`, MESMA mecânica usada pela baseline
   pareada de V1/V2/V3 — zero lógica nova), MESMO risco_pct da entrada no suporte, MESMA saída A,
   gravadas junto (`controles_json`, lista de R por horizonte).

## Hipótese primária e unidade de análise

- **Unidade = TOKEN** (1ª revisita gravada por token — MESMA convenção de "1ª tentativa por token" já
  usada pela H1 desde a rodada 10; revisitas seguintes do MESMO token, se houver, ficam fora da
  amostra primária, só diagnóstico).
- **Desfecho (a)**: `P(+2R antes de −1R) >= 33,3%` (equilíbrio teórico `1/(1+2)`), toque causal, por
  token.
- **Desfecho (b)**: R@72h pareado contra a média dos K=20 controles aleatórios do MESMO token
  (`dif_pareada = R_suporte - R_controle_medio`), bootstrap por token (10k reamostras, semente fixa —
  `analise.condicional.N_BOOTSTRAP_PADRAO`/`SEED_PADRAO`, reusado sem duplicar).
- Nenhum dos dois desfechos decide nada por si nesta coleta — são descritivos/exploratórios até uma
  futura validação formal, pré-registrada separadamente.

## N mínimo e poder honesto

Teste de proporção de 1 amostra, 1 cauda, α=0,05, poder 80% (MESMA convenção/z-scores da emenda do
N=30, `EMENDA_2026-11-05_PODER_ESTATISTICO_N30.md`: `z_0,95=1,6449`, `z_0,80=0,8416`), `p0=33,3%`,
detectando um deslocamento até `p1=45%` (`Δ=11,7pp`, referência citada no pedido):

```
n = ((z_0,95 x sqrt(p0x(1-p0)) + z_0,80 x sqrt(p1x(1-p1))) / Δ)^2
  = ((1,6449 x 0,4714 + 0,8416 x 0,4975) / 0,1167)^2
  ≈ 105 tokens (revisitas elegíveis, unidade=token)
```

Arredondado para **n≈110** com margem de segurança (o próprio pedido já cita esse número — a conta
acima é uma verificação independente, dentro do mesmo pedaço de ordem de grandeza; a pequena
diferença vem da convenção de variância usada — "pooled" vs "não-pooled" — nunca de um erro de
método). **N mínimo declarado desta coleta: 110 revisitas elegíveis, unidade=token.**

## Tempo estimado até esse N — e quando a coleta fica INVIÁVEL

`dias_para_n_min = n_min / (taxa_elegibilidade × caixas_armadas_por_dia)`. Duas taxas de
elegibilidade já observadas (citadas no pedido):

- **Replay** (retrospectivo rodada 18, dentro da amostra): **43%** dos sinais V3 tinham uma revisita
  elegível.
- **Ao vivo** (produção real, mesma rodada 18): **0 de 16** sinais V3 ao vivo tinham revisita
  elegível — **0,0%** observado. Com n=16 e 0 sucessos, o limite superior do IC95% pela regra de três
  é `3/16 ≈ 18,75%` — ou seja, mesmo no cenário mais favorável compatível com essa observação, a taxa
  real ao vivo pode estar bem abaixo do 43% do replay.

**Limitação desta sessão (igual a todas as rodadas anteriores)**: esta sessão cloud isolada não tem
acesso ao banco SQLite real da VM, logo não tem a taxa de CAIXAS ARMADAS (`WATCHLIST`) por dia na
produção real — sem esse número, `dias_para_n_min` não pode ser calculado aqui como um número de
calendário. O operador pode calcular com `saude.py`/`funil_diario.py` (taxa de `WATCHLIST`/dia já
medida por `pr_pools`/eventos do detector) substituindo na fórmula acima.

**Regra de inviabilidade (proposta, nunca automática)**: se, depois de observar as próximas ~50
revisões de pool V3 ativo (WATCHLIST) ao vivo, a taxa de elegibilidade observada permanecer **abaixo
de 10%** (vs 43% do replay) — compatível com a observação atual de 0/16 — esta coleta forward deve
ser declarada **INVIÁVEL no ritmo atual de produção** (nunca "FAIL" da hipótese em si — é uma
declaração de viabilidade de coleta, distinta do mérito da hipótese) e a decisão de continuar
rodando, ampliar o universo (mais pools/tf) ou encerrar fica com o operador, documentada numa emenda
datada — nunca um encerramento silencioso.

## O que esta coleta NÃO faz

- Não altera a entrada, o detector, os parâmetros congelados ou o critério de sinal da V3.
- Não decide nada por si — zero capital, zero vagas, zero alertas reais, zero escrita em
  `pr3_signals`/alertas/trajetória.
- **NUNCA entra no N=30 nem na H1.**
- Não usa o retrospectivo da rodada 18 como parte desta amostra — são coleções SEPARADAS (uma
  dentro-da-amostra/motivadora, outra forward/nova).

## Riscos e viés documentados (nunca escondidos)

- Motivada por achados já vistos (ver seção acima).
- Viés de sobrevivência: só pools que o bot/GeckoTerminal ainda indexam.
- Taxa de elegibilidade observada ao vivo (0/16) é muito menor que a do replay (43%) — a coleta pode
  ser lenta ou inviável; declarado explicitamente, nunca escondido atrás de um N pequeno sem
  contexto.

## Status

**PRÉ-REGISTRADO em 2026-11-12, antes de qualquer linha gravada em `pr3_suporte_sombra`/
`pr3_suporte_sombra_saida`.** Qualquer mudança no algoritmo acima, depois de ver resultado, abre uma
nova emenda datada — nunca reescreve este texto em silêncio (`garantir_suporte_forward_registrada`
recusa com `PreregistroAlteradoError` se o arquivo mudar depois do primeiro registro).
