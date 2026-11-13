# Rodada 18, item 2 — comandos de VM (flag `--veto`, leave-PEAK/HIGH-out) e tempo estimado

PEDIDO 2026-11-12 (autorizado, Rodada 18, item 2). PAPER/READ-ONLY, zero chamada de rede, zero
escrita fora de `meta` (hashes de pré-registro). **Mesma limitação já declarada em rodadas
anteriores**: esta sessão cloud isolada não tem acesso ao banco SQLite real da VM — os tempos abaixo
são **estimativas por complexidade algorítmica**, nunca uma medição. Cole o tempo observado
(`time <comando>`) neste documento após a 1ª execução real.

## O que mudou nesta rodada

Os 3 scripts nomeados pelo pedido (`varredura_v3.py`, `grade_saidas_parciais.py`,
`retrospectivo_saida_fiel.py`) agora aceitam `--veto simples|amplo` (padrão **amplo**) e decidem o
veto de candle corrompido em TODO o caminho (entrada corrigida nos loaders + toque/TP1/stop +
R@72h/R@7d). Cada execução também reporta uma 2ª passada **leave-token-out** (sem `PEAK`/`HIGH`,
`vv3.TOKENS_EXCLUIDOS_DIAGNOSTICO`) lado a lado com a passada completa — isso aproximadamente
**dobra** o custo de agregação de cada script (replay de base é pago 1x, mas a agregação/bootstrap
roda 2x: uma vez sobre todos os sinais, outra vez sobre o subconjunto sem PEAK/HIGH).

Antes desta rodada, `varredura_v3.py` usava SEMPRE o veto simples (`candle_corrompido_provavel`) no
toque/TP1/stop, e `retrospectivo_saida_fiel.py` usava uma mistura (saída fiel em simples, saída
atual A em amplo, herdado da rodada 17). Rodar os comandos abaixo SEM `--veto` reproduz exatamente
esse comportamento histórico (default `None` nas funções de biblioteca); `--veto amplo` (padrão do
CLI) força o mesmo veto amplo em toda a cadeia, inclusive onde antes era sempre simples.

### 1) `varredura_v3.py`

```bash
nice -n 19 tmux new-session -d -s varredura_v3 \
    'python -m signals_mvp.scripts.varredura_v3 --db signals_mvp/dados/estado.sqlite --min-ram-mb 400 \
     --veto amplo --csv varredura_v3.csv \
     2>&1 | tee varredura_v3.log'
```

**Tempo estimado**: replay de base igual ao da rodada 17 (o mais caro dos 3 — percorre TODOS os
pools já admitidos, não só os ~88 com sinal) + a agregação (`agregar_origem`, pareamento com
controles/aleatório/estratos) roda **2x** (universo_admitido/nunca_admitido/retro_lote1 completos +
as mesmas 3 origens sem PEAK/HIGH). Sem medição real: de poucos minutos (banco pequeno) a bem mais
de 1h (banco maduro) só para o replay; a 2ª passada de agregação soma um incremento bem menor que o
replay em si (não refaz o replay, só reusa as listas já filtradas). Rodar com `tmux`/`nice`
obrigatório.

### 2) `retrospectivo_saida_fiel.py`

```bash
nice -n 19 tmux new-session -d -s retrospectivo_saida_fiel \
    'python -m signals_mvp.scripts.retrospectivo_saida_fiel --db signals_mvp/dados/estado.sqlite \
     --veto amplo \
     2>&1 | tee retrospectivo_saida_fiel.log'
```

**Tempo estimado**: replay de base (ordem de grandeza do item 1) + bootstrap 10k reamostras por
horizonte(2)×origem(3)×4 grupos (fiel/atual/controles/aleatório), agora **2x** (com e sem
PEAK/HIGH) = até 8 origens-equivalentes de bootstrap em vez de 3. Bootstrap em si é rápido (amostras
pequenas, puro Python/numpy) — não deve dominar o tempo total; o replay de base continua sendo o
maior custo.

### 3) `grade_saidas_parciais.py`

```bash
nice -n 19 tmux new-session -d -s grade_saidas_parciais \
    'python -m signals_mvp.scripts.grade_saidas_parciais --db signals_mvp/dados/estado.sqlite \
     --veto amplo --csv grade_saidas_parciais.csv \
     2>&1 | tee grade_saidas_parciais.log'
```

**Tempo estimado**: já era o 2º mais caro na rodada 17 (24 variantes × 2 horizontes × 3 origens ×
bootstrap 10k). Com a 2ª passada leave-token-out isso roda sobre **6 origens-equivalentes** em vez
de 3 — **o mais caro dos 3 desta rodada**, possivelmente o dobro do tempo medido na rodada 17 para
este mesmo script. O smoke local (banco vazio, suite offline) já leva ~19s por causa do volume de
combinações mesmo com 1 único sinal de teste — é esperado que a VM com sinais reais leve
significativamente mais.

## P(+NR) para N=8,10,15,20 e contagem de toques ≥+8R sob o veto amplo

Nenhum dos 3 scripts desta rodada calcula `P(+NR)` diretamente — essa métrica vem de
`varredura_v3.resumo_toques`/`_primeiro_toque` (já existente, consumido por `funil_diario.py` e pelo
relatório de toques da própria `varredura_v3.formatar`) e do novo
`scripts/inspecionar_candles_suspeitos.py` (item 1 desta rodada), que já imprime a janela decisiva
de cada toque ±5/±8/±10/±15/±20R sob os 2 vetos lado a lado. Rodar com `--veto amplo` (ou o default
do próprio `varredura_v3.py`, que já é amplo) e ler a seção `## toques` do relatório dá o `P(+NR)`
por N; a contagem de toques ≥+8R que sobrevivem ao veto amplo exige dados reais da VM — **esta
sessão não tem acesso ao banco real**, então esse número não pode ser calculado aqui (mesma
limitação de todas as rodadas anteriores que pedem números sobre o banco de produção).

## Resumo da tabela (preencher com o tempo REAL após a 1ª execução na VM)

| # | comando                      | tempo estimado (sem medição)                    | tempo real medido |
|---|-------------------------------|---------------------------------------------------|--------------------|
| 1 | `varredura_v3 --veto amplo`           | replay (minutos a >1h) + agregação 2x     | _(preencher)_      |
| 2 | `retrospectivo_saida_fiel --veto amplo` | ~ordem do item 1 + bootstrap 2x         | _(preencher)_      |
| 3 | `grade_saidas_parciais --veto amplo`    | o mais caro dos 3 (bootstrap×24×2)      | _(preencher)_      |

**Nunca rodar em paralelo com o bot ao vivo** sem checar `saude.py`/RSS disponível primeiro. Os 3
scripts já têm o guard de RAM (`checar_ram_ou_abortar`, `--min-ram-mb` próprio) — monitore a RAM
mesmo assim (`free -m`/`saude.py` numa 2ª sessão), nunca confiando só no auto-abort.
