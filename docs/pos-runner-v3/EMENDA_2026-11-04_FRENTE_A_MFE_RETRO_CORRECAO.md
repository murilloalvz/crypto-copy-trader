# Emenda 2026-11-04 — FRENTE A: MFE/MAE por 3 fontes, correção crítica do replay retro, R por token

PEDIDO 2026-11-04 (FRENTE A, primeira de 3 — B e C aguardam autorização). **Não altera V1/V2/V3 nem
hashes** (`ParamsV1=279b79ffa3f0`, `ParamsV2=d57b4331d51d`, `ParamsV3=56762db29cd6`) — leitura/relatório
sobre o núcleo já commitado (PR #9 mergeada em `main` em 2026-11-03; branch `signals-mvp` restartada a
partir de `origin/main` + fast-forward dos commits de limpeza que também já estavam mergeados).

## Correção crítica encontrada (afeta código já commitado)

`exit_lab.py: linhas_retro_admitido` (e a cópia em `avaliar_mfe.py` que eu estava escrevendo agora)
construíam o `DetectorV1` da coorte retro com `criado_ts=None`. Sem `criado_ts`,
`DetectorV1.in_age_window()` **sempre** falha e toda zona emite `FORA_DA_IDADE` em vez de `ENTRADA` —
ou seja, a seção retro de `exit_lab.py` nunca achou nenhum sinal desde que foi escrita, mesmo quando
`avaliar_candidatos_retro.py` (que sempre passa `criado_ts` da própria linha congelada) acharia um
real. Corrigido nos dois lugares: `criado_ts`/`grad_ts` agora vêm de `pr_retro_candidatos`, nunca
`None`. Testado com fixture real (`textbook_v1`, já usado em `test_avaliar_v3_retro.py`): a seção
retro de `exit_lab.py` agora encontra a ENTRADA esperada (antes: sempre vazia, silenciosamente).

## `scripts/auditar_mfe.py`: 3 fontes + resumo agregado

Estendido para cobrir as TRÊS fontes de sinais fechados limpos: (A) ao vivo V1/V2/V3, (B) coorte
retro lote 1 admitida após o congelamento (mesmo replay de `exit_lab.linhas_retro_admitido`, já
corrigido), (C) replay completo de V3 sobre pools admitidos hoje (reusa `eventos_raw` de
`avaliar_v3_retro.parte_a_pools_admitidos`). Para B/C, que nunca persistem `closed_ts` próprio
(são simulados, não sinais reais), a saída é ressimulada com `simulate_v1` (mesmos parâmetros
congelados) — `durante_posicao`/`pos_saida` seguem a MESMA partição já validada.

Novo `resumo()`: quantos sinais fechados limpos tiveram MFE>0 em algum momento durante a posição
(lucraram antes da saída), MFE típico em R (mediana, só risco>=3%), e **R por TOKEN** (nunca por
sinal) — R oficial: `100*result_net/risco_pct` para a fonte ao vivo, `simulate_v1.r_mult` para B/C
(mesma fórmula de `live.py`/`avaliar_candidatos_retro.py`).

Item 2 (perdido_offline) e a confirmação de retomada **já existiam** (`passo0e_topo_e_fechamento.py:
listar_perdido_offline`, emenda 2026-11-03) — reconfirmado, nenhuma mudança nova necessária aqui.

## Testes e hashes

12 testes novos/atualizados (`test_auditar_mfe.py`: +4 novos de cobertura de fonte B/C e resumo;
`test_exit_lab.py`: +1 regressão do bug corrigido). Suíte completa: 1020 passed. Hashes
`ParamsV1=279b79ffa3f0`/`ParamsV2=d57b4331d51d`/`ParamsV3=56762db29cd6` intactos.

## Comandos na VM

```
git pull origin signals-mvp
# RESTART NAO necessario (nenhuma mudanca de codigo ao vivo -- so scripts offline/relatorio).
python -m signals_mvp.scripts.auditar_mfe --db dados/estado.sqlite
python -m signals_mvp.scripts.passo0e_topo_e_fechamento --db dados/estado.sqlite   # perdido_offline
```
