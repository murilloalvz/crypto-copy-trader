# Emenda de AMOSTRAGEM — FASE 1: nunca perder sinal, gastar API só em quem pode sinalizar (2026-11-02)

PEDIDO 2026-11-02 (FASE 1 de 2; FASE 2 fica atrás de `POS_RUNNER_TIERS=1`, default DESLIGADO, só
depois de aprovados os números desta FASE 1). **Não altera detector, regra de sinal, nem hashes V1
(`279b79ffa3f0`) / V2 (`d57b4331d51d`)** — tudo aqui é amostragem (quando observar, quando repetir a
busca) ou medição pura.

## 1a) Relógio de rotação corrigido periodicamente (não só no 1º preenchimento)

Segue `EMENDA_2026-11-02_AMOSTRAGEM_RELOGIO_REPLAY.md` (que só cobria o preenchimento inicial de um
`sem_fase_desde` vazio). Os relógios *já gravados* no restart de 02/11 16:11Z (antes do fix existir)
ficaram com `now` daquele instante, não o histórico real. `_corrigir_relogios_por_replay` roda no
`_startup` e a cada 6h (`_corrigir_relogios_periodico`): recalcula por replay causal e grava o MENOR
entre o valor gravado e o do replay — nunca pior, nunca para pool em runner/pullback/posição aberta
(fica `None` por definição). Contador `pr_sem_fase_desde_corrigido`; `saude.py` mostra "relógios
corrigidos (24h)=N" + horas/UTC por pool ativo na mesma linha de rotação (sem furar o teto de 60
linhas).

## 1b) Limiar de rotação 72h → 24h quando idade ≥ 2 dias

`_rotacao_limiar_horas(idade_dias)`: token com ≥2 dias de idade (desde a criação, não a graduação)
usa limiar de 24h em vez de 72h — menos tempo pra liberar a vaga de um token que já teve chance de
formar caixa e não formou. Idade desconhecida usa o limiar padrão (conservador). Limiares em
`POS_RUNNER_ROTACAO_HORAS`/`_REDUZIDO`/`POS_RUNNER_ROTACAO_IDADE_MIN_DIAS` (env-overridable, mesma
convenção de `rotacao_max_por_hora`/`QUEDA_ROTACAO_PCT` — **fora** do hash de `ParamsV1`/`ParamsV2`
de propósito, porque são amostragem, nunca regra de detecção; tocar o hash violaria a instrução
explícita de não alterá-lo). Conta: com `rotacao_max_por_hora=2`, limiar 72h ≈ 48 vagas/dia possíveis
teóricas, na prática ~5/dia observadas (gargalo é candidato qualificado, não o teto); limiar 24h para
tokens ≥2d triplica a frequência com que cada pool elegível é reavaliado, sem mudar QUEM é elegível.

## 1c) Instrumentação de uso de API e latência do candle

`pr_api_uso` (ts, fonte, finalidade, pool, http_status, rate_limited) — só conta chamada de rede DE
VERDADE (confere o contador do `BudgetedHttp`/`DexPaprikaProvider` antes/depois; uma janela já
cobert. pelo cache do `OhlcvStore` nunca é uma "chamada"). Instrumentado: `poll_pool` (GT e
DexPaprika, via `_refresh_core`). **Não instrumentado nesta rodada** (ver "próximos passos" no
`ESTADO_2026-11-02.md`): `baseline`/`trajetoria`/`carteiras`/`verificacao_candidato`/`coorte_retro`.
`pr_candle_latencia` (segundos entre o fechamento do candle 1h e o processamento pelo detector V1).
Relatório em `funil_diario.py` (`saude.py` já estava no teto de 60 linhas): "Uso de API (24h)"
(chamadas/h por finalidade, 429/h) e "Latência do candle (24h)" (p50/p95/max + quantas ficaram perto,
≥80%, do limiar de `_late()` — destacado se o p95 estiver perto).

## 1d) Capacidade: RSS por pool

Amostra periódica (15min) de RSS atual do processo (`/proc/self/status`) + pools ativos naquele
instante → `pr_rss_amostra`. `funil_diario.py`: RSS/pool médio e pior caso (24h) e quantos pools A
MAIS cabem com 200MB de folga ALÉM do uso atual — aproximação honesta (RSS/pool aqui inclui memória
FIXA do processo, supervaloriza o custo marginal real; documentado, não corrigido). **Nunca sugere ou
altera `max_pools`.**

## 1e) Funil diário: aposentados/readmitidos, % runner (7d), alertas N=15/N=30

`funil_diario.py` ganha colunas `aposentados`/`readmitidos` por dia e "% runner (admitidos nos
últimos 7d)" (janela móvel — só mede pools com tempo real de formar runner). `live.py:
checar_e_alertar_marcos_funil` (chamado na cadência do resumo diário) manda 1 alerta ÚNICO
(`pr_alert_once`, idempotente) quando tokens distintos fechados cruza 15 (checagem de futilidade,
SEM p-valor de decisão ainda) e 30 (roda `/analise`).

## 1f) Retentativa curta para pool quente/morno sem candle novo ainda

Pool com `_heat` 0 ou 1 (runner/pullback/caixa em formação — já coberto por pullback/posição aberta)
cujo candle da hora não chegou: `_schedule_ou_retentativa_curta` tenta de novo em +2/+5/+10min (desde
o fechamento da hora) antes de cair no agendamento normal (~1h). Fallback DexPaprika por pendência
também reduzido (`_fallback_dexpaprika_min_pendente`, 5min em vez de 20min) para esses mesmos pools.
Nunca muda detector/regra — só a cadência de busca, para nunca perder um sinal real só por falta de
captura.

## Testes e hashes

918 passed (suite completa). Hashes congelados intactos durante toda a FASE 1:
`ParamsV1=279b79ffa3f0`, `ParamsV2=d57b4331d51d`.

## Comandos na VM

```
git pull origin signals-mvp
# RESTART necessário (sweep de relógios, amostra de RSS, retentativa curta e instrumentação rodam
# dentro do processo do bot ao vivo)
python -m signals_mvp.scripts.saude --db dados/estado.sqlite
python -m signals_mvp.scripts.funil_diario --db dados/estado.sqlite
```

FASE 2 (`POS_RUNNER_TIERS=1`, triagem diária + polling frio em lote + fila de prioridade do
orçamento do GT) fica para depois da aprovação dos números desta FASE 1 — ver
`ESTADO_2026-11-02.md`.
