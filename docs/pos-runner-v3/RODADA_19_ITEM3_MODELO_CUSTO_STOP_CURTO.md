# Rodada 19, item 3 — quanto da perda em stops curtos (~12,7%) é custo modelado

PAPER/READ-ONLY. PEDIDO 2026-11-12 (rodada 19, item 3): decompor quanto da perda observada **maior
que -1R** em stops com distância curta (~12,7%, mediana observada **-1,45R**) é explicado por
**custo** (fee+rede+slippage já modelados em `pos_runner/costs.py`) vs **gap/execução** (preço
abrindo além do stop, `fill = min(open, stop)`, convenção já em vigor em `simulate_v1.py`).

## Por que -1R não é a perda máxima "limpa"

O R-múltiplo é `(fill/entry - 1) / risco_frac`. Um trade que fecha EXATAMENTE no stop, sem custo,
dá exatamente **-1,00R**. Dois efeitos empurram o R realizado abaixo disso:

1. **Custo** (sempre presente, round-trip = entrada + saída): `CostModel.leg_pct` já modela fee do
   pool (varia por faixa de MC/dex), 1% terminal, 0,2% rede, slippage de impacto AMM — aplicado nas
   DUAS pernas. Quanto MENOR o `risco_frac` (stop mais perto da entrada), MAIS esse custo pesa em R
   — é justamente o caso de "stop curto" que o pedido cita.
2. **Gap/execução** (variável, só quando o candle que bate o stop ABRE abaixo dele):
   `fill = min(bar.open, stop)` (`simulate_v1.py`, linha ~150, "sem gap/slippage" — é a convenção já
   em vigor, nunca mudada aqui). Se `bar.open < stop`, o fill é no open, pior que o stop nominal —
   isso é honesto mark-to-market do candle, não um custo "inventado".

## Decomposição analítica do custo (nova: `CostModel.custo_ida_e_volta_em_r`, zero dado novo exigido)

`custo_em_R = (2 x leg_pct) / 100 / risco_frac`. Com `risco_frac = 0,127` (distância de stop ~12,7%
citada no pedido) e 3 cenários de liquidez/MC (cobrindo o pior caso conservador até o melhor caso
realista, ambos já suportados pelo modelo existente, nenhum número novo inventado):

| cenário | fee do pool | leg_pct | round-trip | custo em R |
|---|---|---|---|---|
| pior caso (MC/sol_usd desconhecidos -- tetos conservadores do modelo) | 1,25% (teto) | 3,45% | 6,90% | **≈0,543R** |
| MC baixa, liquidez típica (L_bc no piso 5k, SOL=$150) | 1,25%* | 2,63% | 5,26% | **≈0,414R** |
| MC alta, liquidez robusta (L_bc 85 SOL de graduação, SOL=$150) | ~0,3-1,0%* | 1,95% | 3,90% | **≈0,307R** |

*fee exato depende da faixa de MC em SOL (`PUMPSWAP_TIERS`) — a tabela usa `CostModel.leg_pct` direto,
nunca um número à mão.

**Leitura**: a perda extra observada (-1,45R − (-1,00R) = **-0,45R**) cai **dentro** da faixa
0,307R–0,543R que o custo modelado, por si só, já explica — e no cenário "MC baixa, liquidez típica"
(o mais plausível para um token recém-pumpado com stop a 12,7%) o custo modelado (**0,414R**) fica
muito próximo do extra observado (**0,45R**). **Conclusão honesta**: para stops desta distância, o
custo (fee+rede+slippage) já explica a maior parte — possivelmente a quase totalidade — da perda
extra além de -1R; **sobra pouca margem para um efeito de gap/execução sistemático**, ao contrário do
que se poderia supor à primeira vista.

## O que esta conta NÃO faz (limitação declarada, igual a toda rodada)

- **Não mede o gap/execução real** — isso exige, para CADA trade de stop-out real, comparar
  `bar.open` contra `stop` no candle que decidiu (`fill = min(open, stop)` só desconta do R quando
  `open < stop`) — dado que só existe no banco real da VM. Esta sessão não tem acesso a ele.
- **Não mede o MC/L_bc real no momento do stop-out** — os 3 cenários acima são ilustrativos
  (cobrem o espectro plausível), nunca uma medição; o cenário real de cada trade pode cair fora
  desse intervalo.
- **Não decide nada** — é uma decomposição de custo, nunca uma proposta de mudança de stop/regra.

## Comando para medir com dado real (quando houver acesso à VM)

Para cada trade real resolvido por stop (`horizonte_fixo.calcular_r_horizonte`/`saida_fiel`/sombra
desta rodada, status `resolvido_regra`/`marcado` com fill no stop), calcular:

```
gap_em_R   = max(0, stop - bar_fill.open) / entry_price / risco_frac
custo_em_R = CostModel().custo_ida_e_volta_em_r(dex, mc_usd_no_stop, l_bc, sol_usd_no_stop, risco_frac)
residual   = r_observado - (-1,0) - custo_em_R - (-gap_em_R)   # deveria ficar perto de 0
```

reportando a mediana/distribuição de `gap_em_R` e `custo_em_R` separadamente, por faixa de
`risco_frac` (curto/médio/largo) — não implementado como script dedicado nesta rodada (o cálculo
analítico acima já responde à pergunta qualitativa do pedido); fica proposto para quando houver
acesso real ao banco.
