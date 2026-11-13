# Pré-registro 2026-11-10 — carteiras "pro" forward na V3 (H8/H9-estilo, EXPLORATÓRIO)

PAPER/READ-ONLY. `ParamsV1=279b79ffa3f0`/`ParamsV2=d57b4331d51d`/`ParamsV3=56762db29cd6` ficam
INTOCADOS — este documento e o módulo `pos_runner/carteiras_forward.py` NUNCA alteram
detector/simulate/parâmetros/H1/critério de sinal da V3. É um pré-registro de **análise**, sobre
dados que a Parte 3 da rodada 15 passou a GRAVAR (`pr3_carteiras_sinal`, só gravação, write-only) —
nenhum dado anterior a este documento existe nessa tabela (ela é nova nesta rodada), então esta
condição "o que já foi visto nunca pode julgar a si mesmo" vale aqui de forma trivial: **toda** linha
em `pr3_carteiras_sinal` só existe a partir do registro deste hash, nunca antes.

## 1) O que esta hipótese é, e o que ela NÃO é

**É**: uma hipótese EXPLORATÓRIA, nova e própria, sobre se o sinal real da V3 (ENTRADA) tende a
performar melhor (R@72h marcado a mercado) quando >=1 carteira da lista "pro" (operador,
`carteiras_pro_papodefi.json`, H8/H9 — `docs/research-hypothesis-registry-v1-2026-10-04.md`) está
entre os top holders do token NO MOMENTO do sinal, comparado a quando nenhuma está.

**NÃO é**: uma reabertura do "Native Participant Quality Holdout V1" (`KILL_NATIVE_PARTICIPANT_
QUALITY_SELECTION_EDGE_CANDIDATE`, `docs/native-participant-quality-holdout-v1-result-2026-09-24.md`,
CLOSED/KILL). PQ-V1 usa uma métrica **on-chain calculada** (`native_participant_prior_900_route_
quote_return_median_of_wallet_medians_pct`) sobre **qualquer** participante da rota — fonte de dado,
seletor e cutoff completamente diferentes. A hipótese aqui usa uma lista **curada manualmente pelo
operador** (endereços específicos, nunca uma métrica derivada on-chain), cruzada só contra os top
holders resolvidos via `getTokenLargestAccounts`. Nenhum seletor/cutoff/direção do PQ-V1 é reusado,
retunado ou invertido aqui — são dois experimentos sobre fontes de dado diferentes. A **lição**
levada do PQ-V1 (citada pelo operador como "lição RED-COHORT") é só **metodológica**: aquele
experimento mostrou separação descritiva forte na direção esperada que, ainda assim, **falhou** o
teste formal de profit factor — ou seja, "parece promissor visualmente" não é evidência. Essa lição
vira, abaixo (seção 4), uma exigência explícita de comparação contra placebo: se o placebo (pools sem
sinal, pareados por fase/tf) mostrar o MESMO lift ou maior, a hipótese é descartada por confundimento
— nunca só "parece que tem edge".

## 2) Unidade, amostra e desenho

- **Unidade = token**, primeira tentativa (`token_signal_seq == 1`, mesma convenção de
  `varredura_v3.calcular_token_signal_seq`, rodada 10 item 2). Reentradas (`token_signal_seq >= 2`)
  só entram como análise SEPARADA, diagnóstica, nunca somada à amostra primária.
- **Braço do sinal**: todo sinal V3 real (`pr3_signals`, evento ENTRADA) com linha `tipo='sinal'` em
  `pr3_carteiras_sinal` e `cobertura_valida=1` (holders resolvidos com sucesso NO MOMENTO do sinal —
  `cobertura_valida=0`/linha ausente fica fora da amostra, nunca tratado como "0 carteiras pro").
  Dividido em dois grupos: **>=1 carteira pro** (`n_carteiras_pro >= 1`) vs **0** (`n_carteiras_pro
  == 0`).
- **Braço placebo**: para cada sinal real com cobertura válida, as linhas `tipo='placebo'` do MESMO
  `signal_id` (os K pools de controle gravados no mesmo ciclo pela Parte 3 — mesma fase V1/tf do
  pool-gatilho, sem posição aberta em nenhuma versão, nunca o próprio pool-gatilho; seleção
  determinística, documentada em `PosRunnerLive._carteiras_pools_controle`). O placebo roda a MESMA
  divisão (>=1 pro vs 0) e a MESMA leitura de desfecho (abaixo) — mas sobre pools que **nunca**
  geraram um sinal V3 real.
- **Desfecho primário**: `R@72h` marcado a mercado (mesma convenção `horizonte_fixo.calcular_r_
  horizonte` usada em todo o resto do projeto — V1/V2/V3/retrospectivos). Para o braço placebo (que
  não tem `entry_price`/`stop` de um sinal real), o R é calculado sobre o preço de referência do
  pool-controle no instante da captura (`pr3_carteiras_sinal.ts`) como "entrada" hipotética, usando os
  MESMOS `stop`/custo do sinal real pareado (nunca um stop/risco novo, nunca lookahead — o preço de
  referência do placebo é sempre o fechamento/ts já disponível no instante da captura, igual ao sinal
  real). Sinal **pendente nunca é excluído** — fica fora da contagem de N até resolver (72h), nunca
  descartado silenciosamente.

## 3) Sem lookahead (explícito)

`pr3_carteiras_sinal.ts` é sempre o instante da captura (mesmo ciclo do sinal real) — holders de
qualquer data posterior ao sinal/placebo NUNCA entram nesta análise. O desfecho (R@72h) sempre usa
candles que **começam depois** de `ts`, mesma disciplina causal do resto do projeto
(`signals_mvp/CLAUDE.md`: "a signal is decided on the pool snapshot at decision_ts; outcomes only use
1-min candles that *start after* it").

## 4) Teste formal e a exigência de placebo (lição RED-COHORT)

Para cada ponto de olhada (seção 5):

1. **Delta do sinal** = média de R@72h (braço sinal, >=1 pro) − média de R@72h (braço sinal, 0 pro),
   não pareado por token (grupos distintos de tokens), com IC bootstrap por TOKEN (10k reamostras,
   semente fixa, reamostra tokens com reposição dentro de cada grupo — nunca por linha/sinal).
2. **Delta do placebo** = EXATAMENTE o mesmo cálculo, trocando o braço sinal pelo braço placebo
   (mesmos tokens-gatilho, pools de controle no lugar do pool real).
3. **Regra de descarte por confundimento (RED-COHORT)**: se o delta do placebo for `>=` o delta do
   sinal (ou se o IC do placebo também excluir 0 na MESMA direção do sinal), a hipótese é
   classificada `DESCARTADA_CONFUNDIMENTO` — o efeito observado no sinal real não distingue "tem
   carteira pro" de "é o tipo de pool que our seleção de controle também captaria", e não é tratado
   como edge, independente do que o braço do sinal sozinho mostrar.
4. Só quando o delta do placebo **não** replica o delta do sinal é que o resultado do sinal é lido
   como candidato (nunca validado — ver seção 7).

## 5) Pontos de olhada e amostra mínima (poder honesto)

Esta hipótese é nova — não há nenhuma coleta anterior sob este hash. A primeira olhada formal só
acontece quando **ambos os grupos do braço sinal** (>=1 pro E 0 pro) tiverem, cada um, **>= 20
tokens com cobertura válida** (mínimo declarado aqui, antes de ver qualquer dado). Abaixo de 20/20,
qualquer leitura é só acompanhamento — nunca um desfecho formal.

**Poder honesto (MDE, aproximação normal, 2 amostras independentes, poder 80%)**: reusando a MESMA
única fonte de dispersão já publicada para R na V3 (`docs/pos-runner-v3/EMENDA_2026-11-05_PODER_
ESTATISTICO_N30.md`: DP ≈ 2,68R por token, proxy do bootstrap do `retro_lote1`, n=25 — nunca um valor
novo inventado para este documento), a MDE de um teste de 2 amostras com `n` tokens por braço é:

```
MDE = (z_(1-α) + z_(poder)) × DP × sqrt(2/n)
```

| n por braço | MDE sem correção (α=0,05) | MDE com Bonferroni α/2 (α=0,025) |
|---|---|---|
| 10 | ≈2,98R | ≈3,36R |
| 15 | ≈2,43R | ≈2,74R |
| 20 (mínimo declarado) | ≈2,11R | ≈2,37R |
| 30 | ≈1,72R | ≈1,94R |
| 50 | ≈1,33R | ≈1,50R |

**Leitura honesta**: estes MDEs são GRANDES comparados à magnitude típica de R por trade (~1R). Com
n=20/braço (o mínimo declarado), só um efeito enorme (>~2,1-2,4R de diferença média entre grupos)
seria detectável com 80% de poder — a expectativa realista é `INCONCLUSIVO` por bastante tempo,
mesmo que um efeito real e modesto exista. Isto é dito aqui, antes de ver qualquer dado, exatamente
pela mesma disciplina do item 6 da `EMENDA_2026-11-10_FUTILIDADE_CAUDA_OPCAO_A.md`: `INCONCLUSIVO`
sob poder baixo é o resultado ESPERADO e correto, nunca uma falha do método. Como a V3 é
silenciosa/rara (1 sinal real por vez, mais K placebos), a amostra deve crescer LENTAMENTE — esta
hipótese não tem prazo esperado de resolução nesta rodada.

**Correção de múltiplas comparações**: cada olhada formal roda 2 testes (delta do sinal, delta do
placebo) sobre o MESMO desfecho — tratados como uma família, correção Bonferroni α/2 (mesma
convenção já usada entre V1×V3 no resto do projeto). O secundário (diagnóstico, abaixo) nunca entra
na família de correção porque nunca decide por si só.

## 6) Secundário (diagnóstico, nunca decide sozinho)

- `n_pessoas_pro` (grupos distintos, nunca só `n_carteiras_pro`) como variante do corte >=1/0 acima —
  reportado, nunca substitui a divisão primária por carteira.
- `pct_supply` (soma do % de supply das carteiras pro presentes) em quartis, cruzado com R@72h —
  só descritivo.
- Cobertura (`cobertura_valida`, fração de sinais/placebos com holders resolvidos) reportada em toda
  olhada — uma cobertura muito baixa (ex. <50%) é motivo para suspeitar de viés de seleção (RPC
  RateLimited correlacionado com algum tipo de pool) e deve ser citado explicitamente no relatório,
  nunca escondido.

## 7) Esta hipótese NUNCA é validada por si só

Mesmo que o braço sinal passe (seção 4) e a olhada formal (seção 5) confirme um delta com IC
excluindo 0 na direção esperada: isto é, no máximo, `EDGE_PROVISORIO` — **nunca** `VALIDADA`. Seguindo
`docs/research-hypothesis-registry-v1-2026-10-04.md`, `VALIDADA` exige 3 passos em ordem (PASS
pré-registrado, PASS numa replicação fresca sob o MESMO hash congelado, líquido de custos positivo no
Gate 2) — nenhum deles acontece aqui nesta rodada. Esta hipótese **nunca** entra em N=30/N=60 nem na
H1 da V3 (que são exclusivos do desenho já pré-registrado em `PREREGISTRO_V3_2026-11-02.md` +
emendas) — é uma linha de pesquisa PARALELA e SEPARADA, sobre um dado novo (carteiras pro), nunca uma
alteração da H1 existente.

## O que este pré-registro NÃO faz

- Não altera detector, simulador, parâmetros (`ParamsV1`/`ParamsV2`/`ParamsV3`) nem seus hashes.
- Não reabre, retuna, inverte ou reusa o seletor/cutoff do PQ-V1 (CLOSED/KILL) — fonte de dado
  diferente, experimento novo e próprio.
- Não altera a H1 da V3 nem seus pontos de olhada N=30/N=60 — é uma hipótese paralela, sobre um dado
  (carteiras pro) que a H1 nunca usou.
- Não promove nenhum resultado a `EDGE_PROVISORIO`/`VALIDADA` fora da disciplina de 3 passos do
  registro de hipóteses.
- Não implementa o script de análise nesta entrega — só a captura (Parte 3, já implementada) e este
  pré-registro (Parte 4); o script que lê `pr3_carteiras_sinal` e calcula os deltas/IC/placebo fica
  para quando a amostra mínima (seção 5) for atingida, pedido explícito futuro.

## Status

**PRÉ-REGISTRADO em 2026-11-10**, antes de qualquer linha existir em `pr3_carteiras_sinal` sob este
hash (a tabela é nova nesta rodada — zero dado coletado antes deste registro). O hash deste documento
é congelado em `meta` via `garantir_carteiras_forward_registrada` (`pos_runner/carteiras_forward.py`),
chamado 1x no startup de `PosRunnerLive` (mesma disciplina de `garantir_saida_fiel_registrada`) —
qualquer mudança neste texto depois do 1o registro abre uma emenda datada nova, nunca reescreve este
em silêncio.
