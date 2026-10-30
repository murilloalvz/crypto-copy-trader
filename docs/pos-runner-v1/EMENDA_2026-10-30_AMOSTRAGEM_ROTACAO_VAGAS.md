# Emenda de AMOSTRAGEM — rotação de vagas por incapacidade estrutural (2026-10-30)

PEDIDO 2026-10-30 (FASE 2). **Não altera regra de gatilho/entrada/stop/saída da V1 (hash
`279b79ffa3f0`) nem da V2 (hash `d57b4331d51d`)** — a rotação decide QUEM fica sob observação
(`max_pools`), nunca QUAL decisão o detector toma sobre um candle. Segue a FASE 1 (guarda de
atraso na ENTRADA, `EMENDA_2026-10-30_EXECUCAO_ATRASO_ENTRADA.md`), já comitada e verde.

## Por que isso é AMOSTRAGEM, não só operação

Rotacionar pools muda **quais tokens** o bot observa ao longo do tempo — isso pode introduzir uma
diferença sistemática entre sinais decididos antes e depois da rotação existir (ex.: se a rotação
troca pools estagnados por pools mais novos, a distribuição de idade/MC na entrada pode mudar). Por
isso todo sinal carrega a tag `regime_amostragem` (`pre_rotacao`/`pos_rotacao`), e o `/analise`
reporta a homogeneidade entre os dois grupos antes de juntá-los no mesmo teste.

## 1) Dados do momento em `pr_vaga_descartes`

Candidato bloqueado por falta de vaga (`_promote`) agora grava MC/idade/liquidez do MOMENTO do
descarte (congelados na descoberta — `pico`/`queda_pct` ficam `None`, nunca inventados: um
candidato `'verificado'` ainda não tem candle algum em cache).

## 2) Funil diário + ETA

`scripts/funil_diario.py` (novo, só leitura): conta pool distinto por dia UTC em cada etapa
(descobertos, admitidos, runner, caixa, sinal, fechado — as duas do meio, "runner"/"caixa", nunca
tinham tabela própria antes desta entrega, `pr_funil_marcos`) + ETA em dias até 30 tokens distintos
fechados (projeção linear pela taxa média). Inclui os contadores da FASE 1
(`entradas_atrasadas`/`eventos_pre_admissao`) por dia, para contexto.

## 3) Rotação por incapacidade ESTRUTURAL (`_rotacionar_vagas`)

Libera vaga de `max_pools` só quando **todas** as condições valem:

- sem_fase em V1 **e** V2 (nunca runner/pullback — `_persistir_fases` rastreia `sem_fase_desde`,
  `NULL` sempre que qualquer um dos dois está ativo);
- sem_fase_desde há mais de `POS_RUNNER_ROTACAO_HORAS` (72h);
- MC atual < piso (`min_mc_usd`) **ou** queda do pico > `QUEDA_ROTACAO_PCT` (96% — a faixa MAIS
  LARGA que existe, a de V2; nenhuma versão congelada jamais aceitaria mais um sinal desta onda);
- sem posição aberta (V1 ou V2) nem evidência pendente (`_evidencia_pendente` — trajetória/baseline
  ainda em coleta protege a ciência, nunca uma regra de V1/V2);
- só se houver candidato esperando vaga.

Máximo `rotacao_max_por_hora` (padrão 2, pacing em memória — nunca um invariante científico).
`SEM_ROTACAO=1` desliga por completo. Pool rotacionado vai para `'dormente'` (nunca `'encerrado'`
como `_retire_estagnado`) e entra em `pr_dormentes`.

## 4) Lista dormente + readmissão

`_recheck_dormentes`: 1 chamada de GT por ciclo (orçamento próprio, nunca soma ao ciclo principal),
no pool dormente há mais tempo sem recheck (pelo menos ~1x/dia por pool, sem rajada — usa 1 página
direta do GT, nunca a caminhada completa de `OhlcvStore.history`, que custaria várias chamadas só
para confirmar "não há mais candle"). MC ≥ piso → readmitido (`'verificado'`,
`info.readmitido_dormente=True`), com prioridade sobre candidatos novos em `_promote`
(`_prioridade_espera` — único caso de priorização fora de `mc_found`, pedido explícito; nunca uma
priorização de "qualidade" nos candidatos normais).

## 5) Tag `regime_amostragem` + homogeneidade

Todo sinal novo grava `regime_amostragem` (`pre_rotacao` se decidido antes da 1ª rotação de verdade
— `pr_rotacao_ativacao_ts`, fixada só quando `_rotacionar_vagas` de fato remove um pool — senão
`pos_rotacao`). `/analise` roda Mann-Whitney U (mesmo método de H11/H14) em idade/MC/tempo
pico-caixa entre os dois regimes (`rodar_homogeneidade_regimes`, `n>=10` em cada lado) — nunca
bloqueia H1, só disclosure antes de juntar as amostras.

## Heartbeat/`saude.py`

Nova linha: aposentados por rotação (24h), readmitidos (24h), dormentes agora, candidatos esperando
vaga agora.

## Comandos na VM

```
git pull origin signals-mvp
python -m signals_mvp.scripts.funil_diario --db dados/estado.sqlite
# restart do bot pra rotacao/dormente entrarem em vigor nos ciclos seguintes
# SEM_ROTACAO=1 desliga a rotacao por completo, se precisar
```
