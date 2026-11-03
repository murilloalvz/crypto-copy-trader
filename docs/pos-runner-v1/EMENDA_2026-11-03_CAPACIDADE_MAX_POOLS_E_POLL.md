# Emenda 2026-11-03 — capacidade: max_pools por env, espalhamento de polls, latência corrigida, funil

PEDIDO 2026-11-03 (dados do funil_diario 03/11: RSS/pool 3,8MB, 52 pools extras de folga; poll_pool
12,3/h com 15 pools; 429/h=0,96; sinais só nos primeiros dias — vagas presas depois). **Não altera
detectores, regras de sinal, nem hashes** (`ParamsV1=279b79ffa3f0`, `ParamsV2=d57b4331d51d`,
`ParamsV3=56762db29cd6`) — tudo aqui é AMOSTRAGEM (decide só quando um poll acontece / quantos pools
ficam sob observação), nunca detecção/entrada/saída/banca.

## 1) `max_pools` por env (`POS_RUNNER_MAX_POOLS`)

`LiveSettings._max_pools_padrao()`: `POS_RUNNER_MAX_POOLS` sobrescreve o `max_pools` do config.yaml
(padrão continua 15, sem o env). **Recomendação: iniciar com 30** (RSS/pool atual de 3,8MB, folga de
52 pools extras — números do próprio funil_diario de 03/11). Admissão por `mc_found` desc e rotação
atuais continuam intocadas.

## 2) Espalhamento da hora cheia + teto suave de chamadas/min

`_schedule`: pools **frios/sem carga** (heat>=2 ou -1 — nunca fase ativa) ganham um offset
determinístico por (pool,tf) de até 5 min (`JANELA_ESPALHAMENTO_S`, `_jitter_espalhar_s`) — a MESMA
combinação sempre cai no MESMO offset. Pools em fase ativa (heat 0/1) **nunca** são espalhados —
testado explicitamente que o espalhamento em TODO tier atrasa o poll além do que o harness/produção
tolera (a retentativa curta já cobre até 10min para esses); restringir a frio/sem-carga resolve a
rajada sem esse risco, e é onde a maioria dos pools extras (15→30) está mesmo.

`tick()`: a 2ª passada (descoberta + rank>0, **nunca** posição aberta/rank==0) agora respeita um teto
suave de `POS_RUNNER_MAX_CHAMADAS_POR_MIN` (padrão 20, `_orcamento_disponivel_este_minuto`, janela
deslizante de 60s) — pacing em memória, mesma categoria de `rotacao_max_por_hora`, nunca um invariante
científico. Posição aberta nunca é afetada (testado).

## 3) Correção do bug de latência do candle + por tier/pool

`live.py: _refresh_core` gravava 1 linha de latência POR CANDLE de `seq` — incluindo os de
BACKFILL/histórico (1ª carga ou retomada após lacuna), inflando p95/max artificialmente e disparando
o falso alerta "perto do limiar". Corrigido: grava SÓ o candle MAIS RECENTE de cada poll, com o
`tier` (`_heat()` no momento) — nova coluna nullable em `pr_candle_latencia` (NULL em linhas
anteriores, nunca inventado). `funil_diario.py: latencia_candle_24h` agora quebra p50/p95/max por
tier e lista os piores 5 pools por p95.

## 4) `saude.py`: motivo do atraso + último candle

Pool atrasado (>2h) agora mostra o ts do último candle e o motivo (`pr_api_uso`, finalidade=
`poll_pool`, última tentativa): `429 (rate limit)`, `Nxx (erro do servidor)`,
`sem_negociacao_na_hora` (poll respondeu 200, GT sem candle novo — GT omite horas sem trade) ou
`sem_tentativa_registrada` (fila/orçamento — "backfill em andamento" também cairia aqui; limitação
documentada: este script só lê o SQLite, nunca o cache em disco do `OhlcvStore`). Tudo anexado na
MESMA linha (nunca uma nova, para não furar o teto de 60 linhas).

## 5) `eventos_pre_admissao` por tipo e por token (7d)

`funil_diario.py: eventos_pre_admissao_7d` — join com `pr_pools.symbol` (a tabela só guarda `pool`).
Destaca os tokens com `ENTRADA>0` perdida enquanto esperavam vaga.

## 6) Funil: ativos/admitidos + ETA de 3 dias

`contagem_ativos_admitidos` (pools 'ativo' agora / admitidos em qualquer momento) e
`eta_dias_30_fechados_recente` (mesmo alvo/fórmula do ETA acumulado, taxa só dos últimos 3 dias —
reage mais rápido a uma mudança de ritmo, ex.: depois do `max_pools` subir).

## Testes e hashes

24 testes novos/atualizados (`test_pos_runner_live.py`: +6; `test_funil_diario.py`: +5;
`test_saude.py`: +1). Suíte completa: 1015 passed. Hashes
`ParamsV1=279b79ffa3f0`/`ParamsV2=d57b4331d51d`/`ParamsV3=56762db29cd6` intactos.

## Comandos na VM

```
git pull origin signals-mvp
# RESTART NECESSARIO (mudanca de codigo ao vivo: _schedule, tick(), _refresh_core, LiveSettings).
# Para subir max_pools (recomendado: 30):
POS_RUNNER_MAX_POOLS=30 <comando de start do bot>
python -m signals_mvp.scripts.funil_diario --db dados/estado.sqlite
python -m signals_mvp.scripts.saude --db dados/estado.sqlite
```
