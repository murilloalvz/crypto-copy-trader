# Emenda de AMOSTRAGEM — relógio de rotação preenchido por replay (2026-11-02)

PEDIDO 2026-11-02 (segue `EMENDA_2026-10-30_AMOSTRAGEM_ROTACAO_VAGAS.md`). **Não altera regra de
gatilho/entrada/stop/saída da V1 (hash `279b79ffa3f0`) nem da V2 (hash `d57b4331d51d`)**, nem a regra
de elegibilidade da rotação (>72h sem_fase, incapaz de sinalizar, sem posição/trajetória/baseline
pendente, nunca runner/pullback, máx `rotacao_max_por_hora` (2), só com candidato esperando) — só
decide **quando** o relógio (`sem_fase_desde`) começa a contar.

## O que muda (AMOSTRAGEM, nunca regra)

`_persistir_fases` preenchia um relógio `None` com `now` (o instante do próprio tick) — correto no
sentido de "missingness nunca inventado", mas subestimava sistematicamente quanto tempo um pool já
estava sem_fase sempre que a coluna é nova ou o pool nunca tinha sido visto sem_fase antes. Agora, a
1ª vez que o relógio é preenchido, usa **replay causal de `pr_bars` já em cache** (zero chamada de
rede) — mesmo cálculo de `scripts/diagnostico_vagas.py: _horas_sem_fase_combinada`: desde o último
candle em que V1 OU V2 esteve em runner/pullback, ou desde o 1º candle em cache se nunca teve fase.
Cai de volta em `now` só quando não há candle algum pra reconstruir o passado (pool muito novo) —
nunca um número inventado.

Isso pode fazer um pool virar elegível (>72h) já no 1º tick depois do deploy, em vez de esperar mais
72h reais só porque a coluna é nova — efeito puramente de **amostragem** (muda quando a observação
de "incapacidade estrutural" começa a contar), nunca de regra (os limiares continuam os mesmos).

## Implementação

`live.py: _sem_fase_desde_por_replay(pool, now)` — constrói `DetectorV1` temporários (nunca toca
`self.dets_v1`/`self.dets_v2`, o detector ao vivo) sobre a tf da V1/V2 (`params_v1.timeframes[0]`),
replay candle a candle; `None` = pool realmente ativo agora (nunca grava um relógio nesse caso).
Contador `pr_sem_fase_desde_replay` (1 linha por preenchimento real) — `saude.py` mostra "relógios
preenchidos por replay (24h)=N" na mesma linha de rotação.

## Comandos na VM

```
git pull origin signals-mvp
# RESTART necessário -- o sweep de fases roda dentro do processo do bot ao vivo
python -m signals_mvp.scripts.saude --db dados/estado.sqlite
```
