# Handoff 2026-11-13 — resultados exploratórios de `simular_v3_carteira` (item 3 da revisão)

PAPER/READ-ONLY. Este documento só **registra** números já produzidos pelo operador rodando
`simular_v3_carteira.py` (script EXPLORATÓRIO — ver aviso no topo do próprio script e em
`relatorio()`: `AVISO`/`AVISO_R_MEDIO`). Nenhum valor aqui foi recalculado ou verificado nesta
sessão (a sessão cloud não tem acesso ao `estado.sqlite` real da VM); são os números que o operador
colou no handoff de 12/11/2026, registrados verbatim para constar no histórico do projeto.

**Isto NÃO é um resultado de hipótese pré-registrada.** `simular_v3_carteira` não testa H1 nem
nenhuma hipótese da `docs/research-hypothesis-registry-v1-2026-10-04.md` — ele mede
execução/custo/tamanho de posição sobre sinais V3 já gerados, nunca se o sinal "funciona". Hashes
congelados citados pelo operador no momento da corrida: V1 `279b79ffa3f0`, V2 `d57b4331d51d`, V3
`56762db29cd6`, plano `2bc8e32a0663` — os 4 foram recomputados nesta sessão
(`load_params_v1().version`/`load_params_v2().version`/`load_params_v3().version`/
`analise.condicional.hash_do_plano()`) e batem exatamente com o checkout atual da branch
`signals-mvp`.

## Cenário da corrida

`simular_v3_carteira`, cenário base (slippage "base", custo fixo `US$0.05` — ver
`docs/pos-runner-v3/` e o item (e) desta mesma handoff para a ressalva sobre o que `custo_fixo`
representa), bancas US$250/US$500/US$1000, mãos (tamanho de posição) V10/V25/V50.

## replay_v3 (22 trades, 20 tokens)

- R médio: **-0,35**
- IC90%: **[-0,92; +0,21]**
- R médio sem os top3: **-0,94**

Drawdown/ruína por cenário de banca:

| banca | mão | retorno | drawdown máx | ruína |
|---|---|---|---|---|
| US$1000 | V25 | -5,3% | 11,5% | — |
| US$1000 | V50 | -10% | 23% | — |
| US$500 | V25 | -10,6% | 23% | — |
| US$500 | V50 | -20% | 46% | ~39% |
| US$250 | V10 | — | 18,5% | 0% |
| US$250 | V25 | — | — | 39,8% |
| US$250 | V50 | — | — | 99% |

Nota: banca US$250 só "aguenta" (no sentido de ruína baixa) a mão V10; V25 e V50 já mostram ruína
alta nesta amostra.

## ao_vivo (6 trades, 5 tokens)

- R médio: **-0,99**

## retro_lote1 (14 trades, 13 tokens)

- R médio: **+0,60**
- R mediano: **-1,08**
- R médio sem os top3: **-0,56** (positivo só por causa dos 3 maiores resultados)

## Conclusão (do operador, registrada verbatim)

> sem edge; a simulação só mede ruína/drawdown. Nenhuma conclusão de edge a partir disso.

Esta conclusão é consistente com o propósito declarado do script (`AVISO` em
`simular_v3_carteira.py`): ele mede execução/custo/tamanho de posição, nunca evidência de edge. A
mediana negativa de `retro_lote1` com média positiva só pelos top3, e o IC90% de `replay_v3`
cruzando zero, reforçam que nenhuma leitura de edge deveria ser extraída destes números — qualquer
afirmação de edge exige pré-registro formal e validação fora da amostra
(`docs/research-hypothesis-registry-v1-2026-10-04.md`), que este script não faz e não substitui.

## Rastreabilidade

- Hashes congelados: V1 `279b79ffa3f0`, V2 `d57b4331d51d`, V3 `56762db29cd6`, plano `2bc8e32a0663`
  (recomputados e confirmados nesta sessão contra o checkout atual — ver relatório final da
  handoff).
- Script: `signals_mvp/scripts/simular_v3_carteira.py` (SOMENTE LEITURA, zero chamada de rede, zero
  escrita em qualquer tabela).
- Amostras: `ao_vivo` (sinais V3 reais do bot), `retro_lote1` (HIPOTÉTICO — amostra dentro da
  amostra), `replay_v3` (EXPLORATÓRIO, HIPOTÉTICO — amostra dentro da amostra). As três têm bancas
  independentes, nunca somadas.
- Estes números não foram recalculados nesta sessão; qualquer divergência entre uma nova corrida
  (pós git pull, ver relatório final) e os valores aqui é esperada caso novos sinais/trades tenham
  sido gravados entre 12/11 e a corrida seguinte — isto não invalida o registro, é só uma amostra
  maior/mais recente.
