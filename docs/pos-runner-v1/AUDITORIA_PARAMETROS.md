# Auditoria de parâmetros — POS-RUNNER-V1/V2 (2026-10-29)

PEDIDO ÚNICO, item 1 (somente leitura). Lista **todas** as constantes/limiares que afetam gatilho,
entrada, stop e saída da V1 (congelada, hash `279b79ffa3f0`) e da V2 (congelada, hash `d57b4331d51d`).
**Nenhum valor foi alterado para produzir este documento** — é um levantamento, sem juízo de valor.
V1 e V2 compartilham o MESMO código (`detector_v1.py`/`simulate_v1.py`/`qualidade_v1.py`); diferem
só no CONTEÚDO de `pos_runner_v1.yaml` vs `pos_runner_v2.yaml` (2 linhas: `drop_max`,
`age_window_days` — ver `docs/pos-runner-v2/CHANGELOG_V2.md`). Toda linha sem essa nota tem o MESMO
valor nas duas versões.

Legenda da coluna **origem**: "confirmado pelo operador" (INTERPRETACOES.md diz explicitamente que o
operador validou o número), "literal do prompt" (o prompt original já trazia o número, sem
interpretação), "herdado do V0" (mesma constante/mecânica do detector V0, reaproveitada), "**código
escolheu**" (o Claude traduziu um conceito visual/qualitativo em número, sem confirmação do
operador — marcado em negrito para destaque), "origem não documentada" (nenhum documento do projeto
explica o valor).

## Zona / caixa / consolidação (Setup 1)

| parâmetro | valor | arquivo:linha | origem |
|---|---|---|---|
| `zone_min_candles` (mínimo de candles da caixa) | 12 | `params_v1.py:38` (uso: `detector_v1.py:281`) | literal do prompt — INTERPRETACOES.md linha 14-15 ("consolidação ≥ 12 candles") |
| `wicks_min` / `wicks_max` (nº de wicks de rejeição) | 1 / 3 | `params_v1.py:39-40` (uso: `detector_v1.py:282`) | literal do prompt — INTERPRETACOES.md linha 14-15 ("1 a 3 wicks de rejeição") |
| `test_zone` (proximidade do suporte p/ contar wick/`reacao_suporte`) | 0.05 (±5%) | `params_v1.py:41` (uso: `detector_v1.py:134,161,261,269`) | confirmado pelo operador em 2026-10-22 — INTERPRETACOES.md §1a, linhas 22-28. **Nota**: o V0 usa uma janela mais larga (±10%, `S×1,10`) para a definição genérica de "wick de rejeição" (`detector.py` linha 17/291) — a V1 usa um campo com o MESMO nome (`test_zone`) mas valor próprio (5%), mais estreito, só para o gatilho `reacao_suporte`. |
| `recover_mult` ("recuperou" a zona) | 1.25 | `params_v1.py:42` (uso: `detector_v1.py:133`, `_recovered`) | herdado do V0 (`detector.py:163`, `Zone._recovered` — mesma mecânica) |
| `drop_min` (início da fase pullback/zona) | 0.80 (80%) | `params_v1.py:36` (uso: `detector_v1.py:236`) | literal do prompt — INTERPRETACOES.md linha 14 ("queda 80–90%") |
| `drop_max` (onda invalidada acima disso) | V1: 0.90 (90%) / V2: 0.96 (96%) | `params_v1.py:37` (uso: `detector_v1.py:129,242`) | V1: literal do prompt (INTERPRETACOES.md linha 14); V2: decisão do operador documentada em `docs/pos-runner-v2/CHANGELOG_V2.md` |
| `runner_min_mc` (pico mínimo, filtro da fase RUNNER) | 300 000 USD | `params_v1.py:34` (uso: `detector_v1.py:227`) | literal do prompt — INTERPRETACOES.md linha 14 ("pico ≥ 300k") |
| `peak_attr_mc` (pico "atributo", nunca filtro) | 500 000 USD | `params_v1.py:35` (uso: `detector_v1.py:212,229`) | literal do prompt — comentário `params_v1.py:35` |

## Gatilhos (item 2.6)

| parâmetro | valor | arquivo:linha | origem |
|---|---|---|---|
| `atr_period` (período do ATR) | 20 candles | `params_v1.py:44` (uso: `detector_v1.py:93-97`) | herdado do V0 — INTERPRETACOES.md §1b ("ATR(20), mesmo limiar do V0") |
| `power_atr_mult` (multiplicador do ATR p/ `power_candle_rompimento` **e** p/ exaustão) | 3.0× | `params_v1.py:45` (uso: `detector_v1.py:166` [gatilho]; `simulate_v1.py:77` [exaustão]) | literal do prompt / herdado do V0 — INTERPRETACOES.md §1b e §2. Um único parâmetro faz 2 papéis (gatilho de entrada E critério de saída) |
| `vol_mult` (multiplicador de volume p/ `rompimento_volume`) | 2.0× a média da caixa | `params_v1.py:46` (uso: `detector_v1.py:170`) | literal do prompt — INTERPRETACOES.md §1c |

## Stop e risco (item 2.8)

| parâmetro | valor | arquivo:linha | origem |
|---|---|---|---|
| `stop_below_wick_pct` (% do stop abaixo do menor wick) | 0.02 (2%) | `params_v1.py:52` (uso: `detector_v1.py:196`) | confirmado pelo operador em 2026-10-22 — INTERPRETACOES.md §3 |
| `risk_min` / `risk_max` (faixa de risco esperado, atributo `risco_fora_da_faixa`) | 0.15 / 0.22 (15%–22%) | `params_v1.py:53-54` (uso: `detector_v1.py:208`) | literal do prompt — INTERPRETACOES.md §3, linha 71 (nunca descarta, só tag) |

## Saída — TP1 / exaustão / EXIT FULL (item 2.9)

| parâmetro | valor | arquivo:linha | origem |
|---|---|---|---|
| `tp1_frac` (% vendida no TOPO) | 0.30 (30%) | `params_v1.py:48` (uso: `simulate_v1.py:176`) | confirmado pelo operador em 2026-10-22 — INTERPRETACOES.md §2 |
| `exhaustion_wick_mult` (pavio superior / corpo = exaustão) | 2.0× | `params_v1.py:49` (uso: `simulate_v1.py:81`) | confirmado pelo operador em 2026-10-22 — INTERPRETACOES.md §2 |
| `exhaustion_doji_frac` (candle doji: pavio / amplitude = exaustão) | 0.60 (60%) | `params_v1.py:50` (uso: `simulate_v1.py:83`) | confirmado pelo operador em 2026-10-22 — INTERPRETACOES.md §2 |
| EXIT FULL (fechamento abaixo de `S`) | sem parâmetro numérico próprio — usa o `S` já calculado pela zona | `simulate_v1.py` (lógica, não um limiar isolado) | literal do prompt — INTERPRETACOES.md §2, linha 56-57 |

## Idade / MC / anti-lixo (filtros, itens 2.2/2.4)

| parâmetro | valor | arquivo:linha | origem |
|---|---|---|---|
| `age_window_days` (filtro de idade) | V1: [2.0, 7.0] dias / V2: [2.0, 36500.0] dias (sem teto) | `params_v1.py:27` (uso: `detector_v1.py:109-111`) | V1: confirmado pelo operador em 2026-10-22 — INTERPRETACOES.md §10a; V2: decisão do operador, `docs/pos-runner-v2/CHANGELOG_V2.md` |
| `min_mc_usd` (MC atual mínimo, anti-lixo) | 100 000 USD | `params_v1.py:31` (uso: `live.py:1405,1442`) | literal do prompt — INTERPRETACOES.md §8 |

## `dado_invalido` / qualidade de `L_bc` (item 3.6)

| parâmetro | valor | arquivo:linha | origem |
|---|---|---|---|
| `candle_wick_ratio_max` (1º candle: `high/close` ≥ isto → `dado_invalido`) | 3.0× | `params_v1.py:57` (uso: `qualidade_v1.py:61`) | documentado — INTERPRETACOES.md §6, linha 115 |
| `l_bc_floor_usd` (piso duro, abaixo disso → `dado_invalido`) | 5 000 USD | `params_v1.py:62` (uso: `qualidade_v1.py:63`) | documentado no código (`params_v1.py:58-61`, revisão FASE 1.1, evidência do operador: menor graduação legítima medida ~28k, N=8). **Nota**: INTERPRETACOES.md §6 ainda cita o valor ANTERIOR (US$100, linha 117) — o valor atual (5 000) não foi retroatualizado nesse documento, só no comentário do código e em `STATUS_FASE1.md`. |
| `l_bc_suspeito_baixo_usd` / `l_bc_suspeito_alto_usd` (faixa suspeita, tag `l_bc_suspeito`, nunca bloqueia) | 20 000 USD / 500 000 USD | `params_v1.py:66-67` (uso: `qualidade_v1.py:67`) | documentado no código (`params_v1.py:63-65`, `qualidade_v1.py` docstring, revisão FASE 1.1) — **ausente de INTERPRETACOES.md** (criado depois do documento) |
| `l_bc_ceiling_usd` (teto de sanidade, acima disso → `dado_invalido`) | 10 000 000 USD | `params_v1.py:74` (uso: `qualidade_v1.py:65`) | documentado — INTERPRETACOES.md §6, linha 128 |
| `razao_pico_max` (close do candle do gatilho > isto × pico → veta o gatilho) | 3.0× | `qualidade_candle.py:33` (uso: `detector_v1.py:189`, via `motivo_suspeito`) | documentado — INTERPRETACOES.md §13b, linha 386 ("close_vs_pico... close > 3× o pico") |
| `razao_vizinho_max` (salto vs. candle anterior > isto × → suspeito) | 10.0× | `qualidade_candle.py:32` (uso: `detector_v1.py:189`) | documentado — INTERPRETACOES.md §13b, linha 386-387 ("salto > 10× vs. o candle anterior") |
| `LIMIAR_CORROMPIDO_PROVAVEL_PCT` (divergência DexPaprika > isto → `candle_corrompido_provavel`, mesmo veto) | 50.0% | `qualidade_candle.py:56` | documentado no código (comentário + commit `36a4af0`, EMENDA 2026-10-29) — **não está em INTERPRETACOES.md** |

## Holder concentrado / VAMP (item 2.7) — **sem confirmação do operador**

| parâmetro | valor | arquivo:linha | origem |
|---|---|---|---|
| `HOLDER_CONCENTRADO_PCT` (holder individual ≥ isto % do supply) | 1.5% | `chain_adapter.py:43` (uso: `chain_adapter.py:235`) | **código escolheu** — INTERPRETACOES.md §5 diz explicitamente "ainda sem confirmação do operador" (linha 89). O número 1,5% é heurística do Claude, nunca validada |
| `VAMP_RISK` (outro token com mesmo ticker, mais antigo, MC maior) | sem número único — comparação exata (`mc_usd_candidato > mc_usd_atual`), sem margem de tolerância | `chain_adapter.py:127-141` | **código escolheu** a definição inteira — INTERPRETACOES.md §4 diz "ainda sem confirmação do operador" (linha 76) |

## Limitação conhecida encontrada nesta auditoria (não é um parâmetro, é um comportamento)

`detector_v1.py: _update_wave` continua atualizando o pico (`P_peak`)/a onda mesmo em candles que o
veto de qualidade (`qualidade_candle.motivo_suspeito`) classificou como suspeitos para fins de
GATILHO — só o gatilho em si é vetado (`_check_zone`), nunca o rastreamento de onda/pico. Um candle
com `high` corrompido ainda pode, em tese, resetar `P_peak` para um valor falso. Isso já está
documentado como limitação deliberada em INTERPRETACOES.md §13b (linhas 397-401, "limitação conhecida
e deliberada") — reconfirmado aqui, não corrigido (fora do escopo deste pedido, que é só auditoria).

## Fora do escopo deste levantamento (não é gatilho/entrada/stop/saída)

Parâmetros de banca/posição (`banca_inicial_usd`, `mao_fixa_usd`, `banca_fixa_limite_usd`,
`posicao_frac`, `max_posicoes_abertas`, `stop_diario_frac`, `stop_diario_perdas_seguidas`,
`stop_semanal_frac`, todos em `params_v1.py:76-83`) e `RISCO_IRREALISTA_MIN_PCT = 3.0` (`live.py`,
tag pós-hoc de exclusão estatística, não decide o trade) não entraram nesta tabela — afetam
dimensionamento/relatório, não a decisão de gatilho/entrada/stop/saída em si. Citados aqui só para
registro de que foram vistos e deliberadamente excluídos.
