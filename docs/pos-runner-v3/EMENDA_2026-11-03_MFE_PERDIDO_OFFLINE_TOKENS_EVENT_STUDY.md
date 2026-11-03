# Emenda 2026-11-03 (continuação) — auditoria do MFE, perdido_offline, tokens no avaliar_v3_retro, event study, exit_lab por token

PEDIDO 2026-11-03 (continuação dos pendentes). **Não altera V1/V2/V3 nem hashes**
(`ParamsV1=279b79ffa3f0`, `ParamsV2=d57b4331d51d`, `ParamsV3=56762db29cd6`) — tudo aqui é
leitura/relatório novo sobre o núcleo já commitado (`879c06a`).

## 1) `scripts/auditar_mfe.py` (novo, leitura)

Para cada sinal limpo, identifica o CANDLE exato do MFE/MAE (ts, high/low, volume, vizinhos) e cruza
com `pr1_dexpaprika_divergencias` quando a origem é V1 (V2/V3 saem `s/d` explícito). Separa MFE/MAE em
`durante_posicao` (entrada até `closed_ts`) vs `pos_saida` (`closed_ts` até 72h) — resolve a confusão
relatada (MAE -72% com stop em -40%: só é possível na janela pós-saída, nunca durante a posição,
testado explicitamente).

## 2) `perdido_offline` (passo0e_topo_e_fechamento.py + saude.py)

Nova `listar_perdido_offline()`: token/pool/tf/data/causa (`pr_pools.motivo` se o pool ainda existir,
"pool removido/não encontrado" se não). Confirmado por leitura de `live.py: _startup` (linhas
~795-859): a retomada de posição **já cobre** reinício com posição aberta enquanto o pool continuar
'ativo' (`_refresh`/`_refresh_safe` fecha a lacuna com preços reais); `perdido_offline` só ocorre
quando o PRÓPRIO pool já não está mais 'ativo'. `saude.py` ganhou o aviso pedido, anexado na linha
"POSIÇÕES ABERTAS" (nunca uma linha nova, para não furar o teto de 60 linhas do relatório).

## 3) `avaliar_v3_retro.py`: por token

`_simular_entrada` (avaliar_candidatos_retro.py) ganhou um campo aditivo `tocou_topo` (nunca muda
nenhum valor existente — V1/V2 lote 1 continuam idênticos, suíte de retro confirmada verde). Novo
`resumo_por_token()`: tokens distintos, sinais/fechados por token, R médio/mediano, quantos tocaram o
topo anterior — agregando Parte A + Parte B.

## 4) `scripts/event_study.py` (novo, leitura, exploratório)

Retorno em % (nunca R) a +1h/+6h/+24h/+72h de cada sinal limpo contra os MESMOS 10 controles pareados
que `evidencia.py`/H1 já usam (`candidatos_elegiveis`/`sortear_controles`, mesma seed, mesma janela de
idade — nunca uma amostra nova). Efeito pareado = retorno do sinal − média dos controles; incerteza
via bootstrap em blocos por TOKEN (mesmo método de `bootstrap_media_e_limite_inferior`, generalizado
sem forçar o resultado dentro do dataclass confirmatório `SinalResolvido`). Reporta N de tokens
distintos sempre. Nunca soma a H1/H2-H7.

## 5) `exit_lab.py`: V3 (replay + coorte) e por token

A coorte retro lote 1 ganhou V3 no mesmo loop de V1/V2 (mesmos candles truncados, só troca os
parâmetros). Novo `linhas_v3_replay_pools_admitidos()`: reusa o evento bruto (`eventos_raw`, campo
aditivo de `avaliar_v3_retro.parte_a_pools_admitidos`) para rodar as 4 variantes sobre o replay
completo de V3 nos pools admitidos hoje — nunca duplica o replay. Novo `resumo_por_token()` agrega
TODAS as origens (v1/v2/v3 ao vivo, retro, replay V3) por token.

## Testes e hashes

31 testes novos/atualizados nesta entrega (`test_auditar_mfe.py`: 4; `test_passo0e_topo_e_fechamento.py`:
+3; `test_avaliar_v3_retro.py`: +2; `test_exit_lab.py`: +3; `test_event_study.py`: 8; mais a
confirmação de `test_avaliar_candidatos_retro.py`/`test_saude.py` intactos). Suíte completa: 997
passed. Hashes `ParamsV1=279b79ffa3f0`/`ParamsV2=d57b4331d51d`/`ParamsV3=56762db29cd6` intactos.

## Comandos na VM

```
git pull origin signals-mvp
# RESTART NAO necessario (nenhuma mudanca de codigo ao vivo -- so scripts offline/relatorio novos).
python -m signals_mvp.scripts.auditar_mfe --db dados/estado.sqlite
python -m signals_mvp.scripts.event_study --db dados/estado.sqlite
python -m signals_mvp.scripts.avaliar_v3_retro --db dados/estado.sqlite
python -m signals_mvp.scripts.exit_lab --db dados/estado.sqlite
python -m signals_mvp.scripts.passo0e_topo_e_fechamento --db dados/estado.sqlite
```
