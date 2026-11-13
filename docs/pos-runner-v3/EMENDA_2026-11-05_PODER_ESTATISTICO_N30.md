# Emenda 2026-11-05 — poder estatístico do N=30 (tokens distintos) para a H1 da V3

PAPER/READ-ONLY. **Esta emenda SO acrescenta uma disclosure de poder estatístico ao pré-registro já
existente** (`docs/pos-runner-v3/PREREGISTRO_V3_2026-11-02.md`, registro formal em
`docs/research-hypothesis-registry-v1-2026-10-04.md`) — **NUNCA** reescreve o texto congelado, NUNCA
altera o critério de decisão (a)-(d) já pré-registrado, NUNCA altera `N=30`, o desfecho primário
(`dif_pareada` média > 0) ou a correção Bonferroni α/2 entre V1 e V3. Item 6 do pedido 2026-11-05
(rodada 9): "calcular e reportar o poder estatístico do N=30 tokens distintos para a H1 (que
diferença... é detectável com 80% de poder, alfa 0,05 e Bonferroni)".

## Por que isto é exploratório, nunca confirmatório

Esta conta usa, como ÚNICA fonte de dispersão disponível hoje, o resultado observado por
`varredura_v3.py` nesta MESMA rodada (retro_lote1, 25 pares, IC90% bootstrap `[-1,90,-0,14]`) — que é
ele próprio **exploratório, dentro-da-amostra** (ver `docs/pos-runner-v3/PREREGISTRO_VARREDURA_V3_2026-11-05.md`).
Usar esse número só para dimensionar o poder de um teste FUTURO (quantos tokens precisam de quê) não o
promove a evidência confirmatória — é dimensionamento de amostra, nunca um resultado de H1.

## Método (aproximação normal, 1 cauda — mesma convenção do critério (a) já pré-registrado)

O critério (a) já pré-registrado ("limite inferior do IC90% bootstrap > 0") é equivalente a um teste
unilateral com α=0,05 (IC90% de 2 caudas ⇒ 5% em cada cauda). Com a correção Bonferroni α/2 entre V1
e V3 já pré-registrada, o teste de V3 teria efetivamente α=0,025 unilateral (IC95% de 2 caudas). Usamos
a fórmula clássica da diferença mínima detectável (MDE) para um teste unilateral de 1 amostra, poder
80%:

```
MDE = (z_(1-α) + z_(poder)) × DP / sqrt(N)
```

com `z_0,95 = 1,6449`, `z_0,975 = 1,9600` (Bonferroni α/2), `z_0,80 = 0,8416`, `N = 30`.

## Resultado 1 — R pareado (`dif_pareada`, desfecho primário de H1)

Desvio-padrão por token (DP) estimado a partir do IC90% bootstrap observado por `varredura_v3.py`
nesta rodada (retro_lote1, n=25 pares/tokens): meia-largura do IC = `(−0,14 − (−1,90))/2 = 0,88R`;
`DP ≈ meia-largura × sqrt(n) / z_0,95 = 0,88 × 5 / 1,6449 ≈ 2,68R` (aproximação normal do bootstrap —
nunca um valor medido por um teste formal, só o melhor proxy disponível hoje).

| α (unilateral) | Cohen's d mínimo | MDE em R (com DP≈2,68) |
|---|---|---|
| 0,05 (sem correção) | 0,454 | **≈1,21R** |
| 0,025 (Bonferroni α/2, V1×V3) | 0,511 | **≈1,37R** |

**Leitura**: com N=30, H1 só teria 80% de poder pra detectar uma diferença pareada média de
**~1,2R a ~1,4R** (dependendo de qual α se aplica). Diferenças menores que isso (inclusive um efeito
real, mas modesto) tendem a `INCONCLUSIVO`, nunca `FUTIL` por si — o critério (a)-(d) já cobre isso.

## Resultado 2 — P(+2R antes de -1R) (desfecho do pareamento por toque, B6/rodada 9 item 1)

Aproximação de teste de proporção de 1 amostra contra o equilíbrio teórico `p0=33,3%`, tratando CADA
UM dos N=30 tokens como 1 observação Bernoulli (simplificação explícita — na prática cada token agrega
vários sinais/toques, o que tende a REDUZIR a variância efetiva por token abaixo do Bernoulli puro;
esta conta é portanto um **limite superior conservador do MDE real**, nunca uma garantia de que o MDE
verdadeiro seja exatamente este). `DP_p = sqrt(p0×(1−p0)) = sqrt(0,333×0,667) ≈ 0,471`.

| α (unilateral) | Δ mínimo detectável (pontos percentuais) |
|---|---|
| 0,05 (sem correção) | **≈21,4pp** (ex.: 33,3% → 54,7% ou → 11,9%) |
| 0,025 (Bonferroni α/2) | **≈24,1pp** (ex.: 33,3% → 57,4% ou → 9,2%) |

**Leitura**: N=30 está LONGE de ter poder pra detectar diferenças realistas em P(+2R antes de -1R) —
os desvios observados nesta própria rodada exploratória (universo_admitido −2,8pp, retro_lote1 +1,0pp
vs 33,3%) são **muito menores** que os ~21-24pp detectáveis. Isto não significa que o detector não
tenha edge nesse eixo — significa que N=30 tokens é um tamanho de amostra **adequado apenas pro
desfecho primário em R** (que já era o desenhado), e **inadequado, sozinho, pra qualquer alegação
sobre a taxa de toque** — esse eixo precisa de uma amostra muito maior OU fica só diagnóstico (MESMA
hierarquia já definida no B6: "terceiro, apenas diagnóstico").

## O que esta emenda NÃO faz

- Não muda `N=30`, o desfecho primário, o critério (a)-(d) ou a correção Bonferroni já pré-registrados.
- Não promove `dif_pareada` nem P(+2R antes de -1R) desta rodada exploratória a evidência de H1 —
  os números acima são SÓ dimensionamento de poder, nunca um resultado.
- Não abre uma 2ª hipótese nem recalibra a 1ª — é uma disclosure de poder estatístico, registrada
  ANTES de qualquer coleta formal atingir N=30 sinais novos e forward da V3 ao vivo.

## Status

**EMENDA registrada em 2026-11-05**, como acréscimo ao pré-registro V3 já congelado
(`docs/pos-runner-v3/PREREGISTRO_V3_2026-11-02.md`) e ao registro formal
(`docs/research-hypothesis-registry-v1-2026-10-04.md`). Qualquer mudança nesta conta de poder, depois
de ver mais resultados, abre uma NOVA emenda datada — nunca reescreve este texto em silêncio.
