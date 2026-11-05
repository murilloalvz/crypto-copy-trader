# Emenda 2026-11-05 — CI (patch separado), correção FRENTE A (auditar_mfe) e FRENTE B (negociação)

PEDIDO 2026-11-05. **Não altera V1/V2/V3 nem hashes** (`ParamsV1=279b79ffa3f0`, `ParamsV2=d57b4331d51d`,
`ParamsV3=56762db29cd6`) — leitura/relatório/infra apenas.

## 1) Patch de CI (commit separado)

`.github/workflows/tests.yml`: a limpeza `3af52ea` (PR #8, já mergeada em `signals-mvp` antes desta
sessão) reescreveu o passo "Run unit tests" para `discover -s signals_mvp/tests -t .` e enxugou o
`requirements.txt` da raiz (streamlit/pandas/plotly do dashboard arquivado, nunca as dependências do
bot) — mas o passo "Install dependencies" nunca instalava `signals_mvp/requirements.txt` (onde
`requests`/`PyYAML`/`matplotlib`/`openpyxl` sempre viveram). Nunca foi pego porque PR #8 tinha alvo
`signals-mvp` (não `main`), e o `pull_request` do workflow só dispara contra `main` — a PR #10 foi a
primeira `signals-mvp -> main` desde a limpeza. Corrigido: `pip install -r signals_mvp/requirements.txt`
adicionado ao mesmo passo. Confirmado localmente (clone limpo + venv): o `ModuleNotFoundError`
desaparece; os erros residuais de um clone sem o arquivo local `carteiras_pro_papodefi.json`
(`signals_mvp/.gitignore`, dado pessoal de carteiras, nunca committado) são esperados fora da VM do
operador e não são causados por este patch.

## 2) Correção de `auditar_mfe.py` (FRENTE A, redelivery)

1. **Exclusão de candle corrompido do MFE/MAE**: `_candle_corrompido_provavel` — volume=0 (inclui
   lacuna preenchida por `fill_gaps`, nunca negociação real) OU `high` > 10x o `high` de AMBOS os
   vizinhos (pico isolado, provável erro de dado). Nunca concorre ao MFE/MAE; contado por janela
   (`n_candles_corrompidos_descartados`), nunca silencioso. Puramente retrospectivo — nunca o mesmo
   veto causal de `qualidade_candle.py` (V1/V2/V3 intocados).
2. **Dedup por trade real**: `_deduplicar_por_entrada`, chave `(origem, pool, entrada_ts)`, prioridade
   v1<v2<v3 (determinística). A mesma zona/entrada costuma satisfazer V1 e V2 (ou V3) ao mesmo tempo —
   sem isso, o mesmo trade contava 2-3x no resumo. `resumo()` dedup por padrão; `formatar()` separa
   `ao_vivo`/`retro_lote1`/`replay_v3` em resumos INDEPENDENTES, nunca somados — `replay_v3` rotulado
   **(EXPLORATORIO)**: replay retroativo completo, nunca uma coorte admitida de verdade.
3. **Métricas novas** (`resumo()`): tokens distintos com MFE>=+1R / >=+2R durante a posição; trades
   que chegaram a +2R e AINDA terminaram em stop (devolução — usa `reason`, mesmo campo que
   `live.py`/`simulate_v1` já gravam); tokens distintos com stop seguido de alta>=+100% nas 72h
   seguintes (janela `pos_saida`, candle limpo).

## 3) FRENTE B (leitura, `auditar_negociacao.py`)

Destaque ampliado para DESSA/NIO/MAMESUKE/FOCO/CAPY/WASTED/XD (além de ANT/CHICO). Coluna `fase`
(`pr_pools.fase_v1`/`fase_v2`, já persistida por ciclo). Nova coluna `candles filled/lacuna (24h)`
(`Bar.filled`, já gravado em `pr_bars`): quantifica quantas horas sem negociação `fill_gaps` preencheu.
Resposta à pergunta do pedido: o detector **PREENCHE** (nunca ignora) a lacuna — `fill_gaps` insere
candle "parado" (OHLC=fechamento anterior, vol=0, `filled=True`) para contar duração em candles de
verdade; isso entra sem filtro no ATR (`atr_before`, TR=0 do candle parado) e na média de volume da
caixa (`_gatilhos`/`_check_zone`, `mean_vol` inclui vol=0 — puxa a média pra baixo, o que FACILITA
`rompimento_volume`), e conta normal na contagem de candles da caixa (`Zone.length`). Nenhum limiar
novo decidido aqui — só medição. `auditar_mfe.py` ganhou `vol_entrada`/`vol_24h_antes` por sinal
fechado (candle de entrada e soma das 24h anteriores), reaproveitado pelas 3 fontes.

## Testes e hashes

18 testes em `test_auditar_mfe.py` (10 novos/reescritos: exclusão de candle, dedup, 4 métricas novas,
separação por origem), 3 novos em `test_auditar_negociacao.py` (destaque ampliado, filled vs vol=0
real, fase v1/v2). Suíte completa: ver resposta final. Hashes `ParamsV1=279b79ffa3f0`/
`ParamsV2=d57b4331d51d`/`ParamsV3=56762db29cd6` intactos.

## Comandos na VM (a partir da raiz do repo)

```
git pull origin signals-mvp
# RESTART NAO necessario (nenhuma mudanca de codigo ao vivo -- so CI/scripts offline/relatorio).
python -m signals_mvp.scripts.auditar_mfe --db signals_mvp/dados/estado.sqlite
python -m signals_mvp.scripts.auditar_negociacao --db signals_mvp/dados/estado.sqlite
python -m signals_mvp.scripts.exit_lab --db signals_mvp/dados/estado.sqlite   # criado_ts corrigido (emenda 2026-11-04)
python -m signals_mvp.scripts.passo0e_topo_e_fechamento --db signals_mvp/dados/estado.sqlite   # perdido_offline
```
