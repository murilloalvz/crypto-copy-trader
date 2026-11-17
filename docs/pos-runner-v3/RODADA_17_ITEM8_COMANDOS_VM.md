# Rodada 17, item 8 — comandos de VM (verificação + re-execução com o veto) e tempo estimado

PEDIDO 2026-11-10 (autorizado, Rodada 17, item 8). PAPER/READ-ONLY, zero chamada de rede, zero
escrita fora de `meta` (hashes de pré-registro). **Limitação desta sessão (sem rodeio, mesma lógica
já declarada nos itens 0 e 6)**: esta sessão cloud isolada não tem acesso ao banco SQLite real da VM
— os tempos abaixo são **estimativas por complexidade algorítmica**, nunca uma medição. Depois da
1ª execução real na VM, cole o tempo observado (`time <comando>`) neste documento — é exatamente o
tipo de número que o achado P1 da Rodada 16 (`PARTE_A_VERIFICACAO_NUMEROS.md`) pede para parar de
só circular em conversa sem trilha de auditoria.

## Ordem recomendada

Rode `verificar_numeros_chave` PRIMEIRO (barato, dá o baseline real antes de qualquer replay pesado).
Os 4 scripts pesados reusam os MESMOS loaders (`varredura_v3.carregar_universo_admitido`/
`carregar_retro_lote1`, `retrospectivo_saida_fiel.carregar_ao_vivo`) — cada processo paga o replay de
novo (são invocações de CLI independentes, nunca compartilham memória entre si), então o custo total
é aproximadamente a SOMA dos 5, não o máximo.

## (a) `verificar_numeros_chave.py` — read-only, barato

```bash
nice -n 19 python -m signals_mvp.scripts.verificar_numeros_chave \
    --db signals_mvp/dados/estado.sqlite \
    2>&1 | tee verificar_numeros_chave.log
```

**Tempo estimado**: segundos a poucos minutos. Carrega as mesmas 3 origens que os scripts abaixo
(mesmo custo de replay de base), mas as métricas em si (contagens, médias, curva de toque) são
O(sinais) — sem bootstrap de 10k reamostras. Se `ao_vivo`/`retro_lote1`/`replay_v3` já estiverem
nos tamanhos citados no pedido (15/38/88 sinais), o replay de base é pequeno; o grosso do tempo (se
houver) vem do `replay_v3` (`universo_admitido`), que percorre TODOS os pools já admitidos, não só
os que geraram sinal.

## (b) Re-execução com o veto de candle corrompido (Rodada 17, item 1)

Todos os 5 comandos abaixo já aplicam o veto automaticamente — `horizonte_fixo.calcular_r_horizonte`
(usado por `retrospectivo_saida_fiel`/`grade_saidas_parciais`/`verificar_numeros_chave`, e agora
também usado por `varredura_v3`/`auditoria_fidelidade_v3` apenas de forma INDIRETA, via os MESMOS
sinais carregados — ver nota abaixo) já tem `candle_confiavel_cb` (Rodada 17 item 1, parte 1/2)
embutido. Não existe uma flag `--com-veto` separada: a correção já está no código, sempre ativa.

**Nota sobre `varredura_v3.py`/`auditoria_fidelidade_v3.py` especificamente**: esses 2 scripts usam
`candle_corrompido_provavel` (veto SIMPLES) na varredura de toque/TP1/stop em si (`_toque_causal`,
nunca alterado nesta rodada — é a lógica congelada que decide a grade de 24 variantes). O veto AMPLO
só foi adicionado em `horizonte_fixo.py` (consumido por `retrospectivo_saida_fiel`/
`verificar_numeros_chave`/`grade_saidas_parciais`) e no script NOVO `auditar_candles_corrompidos_
sinais.py` (que mede o GAP entre os dois vetos, nunca re-decide a grade). Rodar os 5 comandos abaixo
não muda o resultado de `varredura_v3`/`auditoria_fidelidade_v3` em si — eles continuam no veto
simples, por desenho (ver docstring do item 1, parte 2/2). O que muda de verdade com o veto amplo é
`retrospectivo_saida_fiel`/`verificar_numeros_chave`/`grade_saidas_parciais` (via `horizonte_fixo.py`)
e o relatório de gap do `auditar_candles_corrompidos_sinais.py`.

### 1) `varredura_v3.py` (base — replay completo de `universo_admitido`)

```bash
nice -n 19 tmux new-session -d -s varredura_v3 \
    'python -m signals_mvp.scripts.varredura_v3 --db signals_mvp/dados/estado.sqlite --min-ram-mb 400 \
     2>&1 | tee varredura_v3.log'
```

**Tempo estimado**: o MAIS caro dos 5 — replay completo de TODOS os pools já admitidos (não só os
~88 com sinal citados), candle a candle, reconstruindo `DetectorV1` do zero por pool/tf. Sem medição
real, só o volume total de pools×candles na VM decide — pode ir de poucos minutos (banco pequeno,
VM nova) a mais de 1h (banco maduro, meses de histórico, muitos pools nunca admitidos também
varridos por `universo_nunca_admitido`). Rodar com `tmux`/`nice` (como o próprio script já recomenda)
é obrigatório — nunca interativo numa sessão que pode cair.

### 2) `auditoria_fidelidade_v3.py`

```bash
nice -n 19 tmux new-session -d -s auditoria_fidelidade_v3 \
    'python -m signals_mvp.scripts.auditoria_fidelidade_v3 --db signals_mvp/dados/estado.sqlite \
     2>&1 | tee auditoria_fidelidade_v3.log'
```

**Tempo estimado**: mesma ordem de grandeza do replay de base de `varredura_v3` (reusa
`carregar_universo_admitido`/`carregar_retro_lote1`, paga o mesmo custo de novo) + overhead pequeno
das estatísticas B1-B9 (O(sinais), sem bootstrap pesado) — espere próximo do tempo do item 1, talvez
10-20% mais.

### 3) `retrospectivo_saida_fiel.py`

```bash
nice -n 19 tmux new-session -d -s retrospectivo_saida_fiel \
    'python -m signals_mvp.scripts.retrospectivo_saida_fiel --db signals_mvp/dados/estado.sqlite \
     2>&1 | tee retrospectivo_saida_fiel.log'
```

**Tempo estimado**: replay de base (ao_vivo tem loader próprio, mais leve; retro_lote1/replay_v3
reusam `varredura_v3`) + bootstrap 10k reamostras por horizonte(2)×origem(3)×4 grupos
(fiel/atual/controles/aleatório) — bootstrap em si é rápido (amostras pequenas, puro Python/numpy),
não deve dominar o tempo total. Ordem de grandeza semelhante ao item 1/2.

### 4) `grade_saidas_parciais.py`

```bash
nice -n 19 tmux new-session -d -s grade_saidas_parciais \
    'python -m signals_mvp.scripts.grade_saidas_parciais --db signals_mvp/dados/estado.sqlite \
     2>&1 | tee grade_saidas_parciais.log'
```

**Tempo estimado**: o 2º mais caro — 24 variantes × 2 horizontes × 3 origens × bootstrap 10k, mais
Holm-Bonferroni e a checagem de sanidade contra B3b. Multiplica o overhead de bootstrap do item 3 por
~24x (nunca o replay de base, que é pago 1x só). Espere o maior tempo depois do item 1 — possivelmente
o dobro ou mais, dependendo de quão cara é a parte de bootstrap vs. o replay de base nesta VM
específica (só a 1ª medição real responde isso).

### 5) `auditar_candles_corrompidos_sinais.py` (NOVO, Rodada 17 item 1 parte 2/2)

```bash
nice -n 19 python -m signals_mvp.scripts.auditar_candles_corrompidos_sinais \
    --db signals_mvp/dados/estado.sqlite --csv auditoria_candles_corrompidos.csv \
    2>&1 | tee auditar_candles_corrompidos_sinais.log
```

**Tempo estimado**: replay de base (mesmo custo do item 1) + O(sinais × candles_por_sinal × 2
horizontes × 5 alvos de toque) — tudo float puro, sem bootstrap. Deve ficar perto do tempo do item 1
(a parte NOVA deste script é barata comparada ao replay).

## Resumo da tabela (preencher com o tempo REAL após a 1ª execução na VM)

| # | comando                              | tempo estimado (sem medição)      | tempo real medido |
|---|---------------------------------------|------------------------------------|--------------------|
| a | `verificar_numeros_chave`             | segundos a poucos minutos          | _(preencher)_      |
| 1 | `varredura_v3`                        | minutos a >1h (o mais caro)        | _(preencher)_      |
| 2 | `auditoria_fidelidade_v3`             | ~ordem do item 1, +10-20%          | _(preencher)_      |
| 3 | `retrospectivo_saida_fiel`            | ~ordem do item 1                   | _(preencher)_      |
| 4 | `grade_saidas_parciais`               | o 2º mais caro (bootstrap × 24)    | _(preencher)_      |
| 5 | `auditar_candles_corrompidos_sinais`  | ~ordem do item 1                   | _(preencher)_      |

**Nunca rodar em paralelo com o bot ao vivo** sem checar `saude.py`/RSS disponível primeiro.
`varredura_v3`/`retrospectivo_saida_fiel`/`grade_saidas_parciais`/`auditar_candles_corrompidos_
sinais` já têm o guard de RAM (`checar_ram_ou_abortar`, default 150MB, `--min-ram-mb` próprio) que
aborta sozinho se a RAM cair abaixo do piso — **mas `auditoria_fidelidade_v3.py` NÃO tem esse guard**
(achado desta rodada, confirmado por leitura direta: seu `main()` não chama `checar_ram_ou_abortar`
nem expõe `--min-ram-mb`). Até isso ser corrigido (fora do escopo deste item 8 — é uma correção de
código, não um comando a rodar), monitore a RAM manualmente ao rodar o item 2 (`free -m`/`saude.py`
numa 2ª sessão), nunca confiando em auto-abort.
