# Emenda 2026-11-03 — correção do Passo 0e, exit_lab.py, V3 offline sobre pr_bars + coorte lote 1

PEDIDO 2026-11-03. **Não altera V1/V2/V3 nem hashes** (`ParamsV1=279b79ffa3f0`,
`ParamsV2=d57b4331d51d`, `ParamsV3=56762db29cd6`, os 3 intactos) — tudo aqui é correção de
relatório/novo relatório exploratório sobre o núcleo já commitado.

## 1) Correção do bug relatado (MFE +1.378.027 R)

Causa raiz: `pr_trajetoria.mfe_r`/`mae_r` são R-múltiplos (`movimento_% / risco_%`); com risco real
colado perto de 0% (mesma classe do -561R/-564R do McRib), a divisão explode. A 1ª versão do script
nunca aplicava a exclusão que `/analise` já aplica. Corrigido reusando `analise.condicional.
_risco_irrealista`/`_contaminado_candle`/`RISCO_IRREALISTA_MIN_PCT` (nenhuma regra nova):

- `contaminado_candle` → fora do relatório (nem % nem R);
- risco<3% → reportado À PARTE (`linhas_risco_baixo`), MFE/MAE sempre em **% do preço de entrada**
  (`mfe_r * risco_pct`, desfaz a divisão — numericamente estável mesmo com risco minúsculo), nunca em R;
- amostra limpa (contaminado fora, risco>=3%) → % **e** R, igual a antes;
- nova contagem por status/exclusão (`contagem_status`, `n_contaminados`, `n_risco_baixo`, `n_limpos`)
  explica por que `n_entradas` > `n_fechados` (ver item 2).

Testado com sinal sintético risco=0,1%/mfe_r=1200 (a mesma classe do bug): agora cai em
`linhas_risco_baixo` com `mfe_pct=+120%` e `mfe_r=None` — nunca mais um "R" de 6 dígitos.

## 2) Por que ENTRADA > fechados (V1 7/4, V2 3/1)

Sem o banco real da VM este checkout não pode calcular os números exatos — mas a resposta agora é
rastreável: rode `passo0e_topo_e_fechamento.py` corrigido e leia `contagem_status`/
`n_contaminados`/`n_risco_baixo` por versão. As categorias possíveis: `aberto` (ainda não fechou),
`cancelado` (abriu fora do plano), `descontinuado` (troca de versão de config), `perdido_offline`
(pool saiu de acompanhamento) — nenhuma dessas é "fechado"; e, mesmo entre os fechados,
`contaminado_candle` (marcação manual) e risco<3% (`risco_irrealista`, automático) saem da amostra
limpa sem deixar de contar como fechado. A diferença 7→4 (V1) e 3→1 (V2) está nessas categorias —
o relatório corrigido mostra exatamente quantos caem em cada uma para os dados reais.

## 3) `scripts/exit_lab.py` (novo, SOMENTE LEITURA)

4 saídas alternativas definidas agora, sem otimização, sobre `pr_bars` já cacheado, para os sinais
limpos de V1/V2/V3 e para o subconjunto `admitido_apos_congelamento` da coorte retro lote 1 (único
com candles cacheados sem rede — candidatos nunca admitidos ficam fora, limitação documentada):

- **A** (atual): reexecuta `simulate_v1` com o mesmo `stop`/`TOPO`/`S` do sinal;
- **B**: stop no breakeven depois que a máxima desde a entrada sobe >= 1x a altura da caixa (R−S);
- **C**: sai 100% no 1º fechamento de 1h abaixo do teto da caixa (R) após a entrada — decidido no
  fechamento, executado no open seguinte; o stop original continua com prioridade intracandle;
- **D**: 30% no 1º toque do topo anterior (TOPO, sem exigir exaustão — deliberadamente mais simples
  que o TP1 oficial) + trailing nos 70% restantes, stop subindo (nunca descendo) para logo abaixo de
  cada fundo de mini-caixa confirmado causalmente 2 candles depois.

R-múltiplo sempre com o risco ORIGINAL do sinal (comparável entre as 4 variantes); risco<3% exclui o
R das 4, nunca o %. Custo: `CostModel()` padrão, sem cotação SOL/USD cacheada (mesmo fallback
conservador do script retro) — pode divergir em custo fino do `result_net` oficial; a variante A
serve para comparar as 4 entre si, nunca substitui o resultado oficial. Rótulo explícito em todo o
relatório: "exploratório, não escolhe saída; N pequeno; sem seleção do melhor". Nunca altera
`pr1_signals`/`pr2_signals`/`pr3_signals`/`pr_trajetoria`/`pr_baseline`/`pr_retro_resultados`/H1.

## 4) `scripts/avaliar_v3_retro.py` (novo, SOMENTE LEITURA, lote 1 — pendente do dia anterior)

Continuação do item deixado pendente na emenda de 2026-11-02 ("script offline da V3 sobre `pr_bars`
e a coorte retrospectiva lote 1"). Duas partes, as duas offline (zero chamada de rede, banco aberto
em `mode=ro` — escrita impossível mesmo por engano):

- **A)** pools admitidos hoje (ativo/dormente/encerrado): replay causal completo de `ParamsV3` sobre
  o histórico já cacheado em `pr_bars` (mesmo padrão de `diagnostico_vagas.py: secao_a`) — "o que a
  V3 teria visto desde que o bot passou a acompanhar este pool";
- **B)** a coorte retrospectiva **lote 1 já congelada** (`pr_retro_candidatos`, mesma lista/hash de
  `avaliar_candidatos_retro.py`, nunca recalculada), restrita ao subconjunto
  `admitido_apos_congelamento` (único com candles em `pr_bars`). Reusa `processar_candidato` sem
  mudança nenhuma, só passando `params_v3` nos dois parâmetros — **nunca chama
  `_persistir_resultado`**, então o resultado V1/V2 do lote 1 já congelado continua intocado em
  `pr_retro_resultados`.

**Lote 2 (congelar novos candidatos aparecidos depois do lote 1): NÃO feito nesta entrega**, por
pedido explícito do operador ("e só depois o lote 2") — fica para a próxima rodada, agora que este
script existe.

## Testes e hashes

18 testes novos/atualizados nesta entrega (6 em `test_passo0e_topo_e_fechamento.py`, incluindo 3
novos cobrindo a correção do bug; 10 em `test_exit_lab.py`; 4 em `test_avaliar_v3_retro.py`) — ver
resposta do operador para a contagem total da suíte. Hashes: `ParamsV1=279b79ffa3f0`,
`ParamsV2=d57b4331d51d`, `ParamsV3=56762db29cd6` (os 3 intactos, reconfirmados após esta entrega).

## Comandos na VM

```
git pull origin signals-mvp
# RESTART NAO necessario (nenhuma mudanca de codigo ao vivo -- so scripts offline/relatorio novos).
python -m signals_mvp.scripts.passo0e_topo_e_fechamento --db dados/estado.sqlite
python -m signals_mvp.scripts.exit_lab --db dados/estado.sqlite
python -m signals_mvp.scripts.avaliar_v3_retro --db dados/estado.sqlite
```
