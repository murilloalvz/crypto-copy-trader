# Emenda de amostragem/medição — POS-RUNNER-V3: integração ao vivo, análise estratificada, Passo 0e

PEDIDO 2026-11-02 (continuação do Passo 1). **Não altera detector, regra de sinal, nem hashes**
(`ParamsV1=279b79ffa3f0`, `ParamsV2=d57b4331d51d`, `ParamsV3=56762db29cd6`, todos intactos) — tudo
aqui é integração/medição/amostragem sobre o núcleo já commitado (`9e88a51`).

## 1) Integração ao vivo da V3 (`live.py`)

`_detector_v3`/`_on_event_v3`/`_entry_v3`/`_update_paper_v3`/`_update_evidencia_v3` — cópias exatas
do padrão V1→V2 (mesmo `DetectorV1`/`simulate_v1`, zero código novo de detecção), com 2
simplificações **deliberadas e documentadas** (V3 é silenciosa/medição, nunca fez essas chamadas
nesta entrega): sem holders/authority/vamp_risk/carteiras_pro (zero RPC extra) e sem banca/CSV
próprios (`posicao_pct_supply` é só covariável, nunca decide tamanho real). `pr3_signals`/
`pr3_filtrados` (tabelas novas, schema espelha `pr1_signals` + as covariáveis do Passo 1 + colunas
"sempre NULL" que o pipeline de análise lê incondicionalmente — ver item 3). `pr_trajetoria`/
`pr_baseline` são **genéricas por `(versao, entry_id)`** — zero schema novo precisou existir para a
V3 ter trajetória/baseline pareada, só `versao="v3"`.

`SEM_V3=1` desliga por completo (detector nunca criado); `V3_ALERTAS=1` liga alerta por ENTRADA
(padrão: silenciosa, só resumo diário — `daily_summary_v3`, chamado por `engine.
maybe_send_daily_summary` igual a V1/V2). WATCHLIST/ONDA_INVALIDA da V3 NUNCA alertam, mesmo com
`V3_ALERTAS=1` — só ENTRADA ("alerta por sinal", a palavra exata do pedido).

**RSS por pool**: a amostragem existente (`pr_rss_amostra`, FASE 1d) já mede RSS total do processo
÷ pools ativos — nenhuma instrumentação nova foi criada especificamente para a V3, porque um delta
"atribuível só à V3" exigiria uma comparação controlada com/sem `SEM_V3` (duas rodadas reais na VM),
não um número que se possa calcular sem rodar as duas condições. O que já existe (RSS/pool médio em
`funil_diario.py`) é o proxy a observar antes/depois deste deploy.

## 2) Análise estratificada (`analise/condicional.py`)

`/analise v3` (e `python -m signals_mvp.analise.condicional --versao v3`) rodam o MESMO pipeline de
H1 (bootstrap em blocos, 3 desfechos da Emenda 1) que V1/V2, com 2 diferenças: (a) os 8 estratos do
pré-registro (`_grupos_v3_estratos`/`rodar_exploratorias_v3`, mesma disciplina Holm de H2-H7, nunca
confirmatórios) em vez de H2-H7/H10-H12; (b) sombra/H13/H14 ficam de fora (`[]`/`None`) — são
recursos exclusivos de V1/V2 (`pr_sombra`/`pr_radar` nunca têm linha `versao='v3'`). `SinalResolvido`
ganhou campos opcionais (`caixa_candles`, `queda_pico_pct`, `mc_base`, `razao_corpo_descomunal`,
`possivel_clone`, `gatilho_v3`) — `None`/`False` para V1/V2 (nunca os calculam), preenchidos só
quando a origem é `pr3_signals`.

**Taxa de acerto, razão ganho/perda, R mediano** (pedido explícito): `resumo_r_realizado()` — SO
descritivo (reportado em `formatar_markdown`), NUNCA decide H1 (que continua usando `dif_pareada`,
a baseline pareada, não o R realizado isolado). "Bootstrap em blocos": já existia
(`bootstrap_media_e_limite_inferior`/`bootstrap_p_valor_unilateral`), reusado sem mudança.

## 3) Polling frio (hook, FASE 2 ainda não implementada)

`PosRunnerLive._zone_min_candles_minimo()` — `min(zone_min_candles)` entre V1/V2/V3 ativas (12, 12,
4 por padrão). Só um HOOK: a FASE 2 (`POS_RUNNER_TIERS`, intervalo_frio/pr_triagem/pr_gt_budget)
continua atrás da aprovação dos números da FASE 1 (`ESTADO_2026-11-02.md`) — quando for implementada,
o cálculo do intervalo PRECISA usar este mínimo (nunca só o 12 de V1/V2), para nunca arriscar perder
a caixa mais curta que a V3 consegue armar.

## 4) Passo 0e — medição empírica (`scripts/passo0e_topo_e_fechamento.py`, só leitura)

Para V1/V2/V3: tempo de entrada até o toque no topo anterior (`tp1_ts - entry_ts`, já que TP1
dispara exatamente em `bar.high >= TOPO` — literal, nenhum número novo), distribuição do MFE
(`mfe_r`/`mfe_h` de `pr_trajetoria`), % de saída por stop/EXIT FULL/TP1 (`reason` dos fechados), e
quantos nunca tocaram o topo dentro de 72h (proxy de "72h é curto demais"). **Limitação
documentada**: a coorte retrospectiva não grava `tp1_ts`/`mfe_h` por sinal — fica fora deste
relatório (estender a coorte para isso é trabalho novo, não feito aqui). Números reais exigem rodar
na VM — este checkout não tem histórico real, só os testes sintéticos confirmando que o script roda
sem exceção e lê exatamente o que já está persistido.

**Resposta à pergunta "o desfecho de H1 é o R simulado ou o retorno de 72h da trajetória?"**: é o
**R simulado** — `live.py: _atualizar_baseline`, `r_sinal = 100.0 * signal["result_net"] /
risco_pct_sinal` (`result_net` vem de `simulate_v1`: TP1/EXIT FULL/stop, nunca da janela fixa de
72h). Os campos de trajetória (`mfe_r`/`ret_r_Xh`, `evidencia.py`) são só diagnóstico/descritivo —
`_atualizar_baseline` nunca os lê.

## Pendente (próximo commit — decisão explícita, mesma disciplina do núcleo)

- **Item 2** (script offline da V3 sobre `pr_bars` + coorte retrospectiva lote 1, relatório por
  estrato "retro, exploratório"; congelamento do "lote 2" da coorte — já desbloqueado, hash da V3
  commitado) — **NÃO implementado nesta entrega**. Motivo: exige desenho cuidadoso do "lote 2"
  (schema de `pr_retro_candidatos` ganharia uma coluna `lote`, idempotente, sem tocar o lote 1 já
  congelado) e reconciliar duas fontes de candle (pr_bars direto vs. OhlcvStore da coorte) sem
  arriscar pressa — fica para o próximo commit, listado aqui para nunca ser esquecido.

Nenhum destes itens pendentes muda os hashes nem invalida os testes já commitados.

## Testes e hashes

Ver resposta do operador para a contagem exata desta entrega. Hashes: `ParamsV1=279b79ffa3f0`,
`ParamsV2=d57b4331d51d`, `ParamsV3=56762db29cd6` (os 3 intactos).

## Comandos na VM

```
git pull origin signals-mvp
# RESTART necessario (V3 agora roda dentro do processo do bot ao vivo -- detector/entry/paper/
# evidencia, silenciosa por padrao)
python -m signals_mvp.analise.condicional --versao v3
python -m signals_mvp.scripts.passo0e_topo_e_fechamento --db dados/estado.sqlite
```

`SEM_V3=1` desliga a V3 por completo; `V3_ALERTAS=1` liga alerta por ENTRADA (padrão: silenciosa).
