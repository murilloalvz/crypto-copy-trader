# Emenda 2026-11-06 — Parte 3: sombra ao vivo da saída fiel + entry_price_alerta no instante do envio

PEDIDO 2026-11-06 (rodada 12, Parte 3, autorizado). PAPER/READ-ONLY. **Não altera detector, simulate,
parâmetros, H1, sinais, alertas ou critério de sinal** (`ParamsV1=279b79ffa3f0`,
`ParamsV2=d57b4331d51d`, `ParamsV3=56762db29cd6` intactos). As duas mudanças desta emenda são SÓ
medição/instrumentação ao lado da V3 — nenhuma delas decide, filtra ou altera uma entrada/saída real.

## O que muda no código ao vivo (`pos_runner/live.py`, `storage.py`)

### 1) `pr3_saidas_sombra` (tabela nova, read-only)

Para cada sinal V3 real (`pr3_signals`, `evento='ENTRADA'`) com trajetória confirmada
(`pr_trajetoria`), o bot agora calcula incrementalmente, a cada ciclo do pool/tf, a "saída fiel"
(algoritmo exato pré-registrado e congelado por hash em
`docs/pos-runner-v3/PREREGISTRO_SAIDA_FIEL_2026-11-06.md` — ver Parte 1 desta rodada) em 72h e 7d,
gravando o resultado (`status`/`r_mult`/`tp1_realizado`) em `pr3_saidas_sombra` —
`_sombra_saida_fiel_v3` (nova), chamada via `_sombra_safe` (mesma disciplina das outras sombras:
qualquer exceção aqui é só um aviso no log, nunca derruba o ciclo). `garantir_saida_fiel_registrada`
é chamado 1x no `__init__` do bot (fail-closed: se o texto do pré-registro mudou depois do 1º
registro, o bot recusa subir com `PreregistroAlteradoError`) — é por isso que esta mudança **exige
restart** (congela o hash ANTES do 1º ciclo que for calcular a sombra).

Nunca escreve em `pr3_signals`/alertas/`pr_trajetoria`/H1 — é uma tabela paralela, só leitura dos
dados já existentes (`det.bars`, zero chamada de rede nova).

### 2) `entry_price_alerta` capturado no instante REAL do envio (não mais cópia do preço modelado)

Antes: `entry_price_alerta` era gravado no INSERT com o MESMO valor de `ev.data["close"]` (o preço
modelado no candle de decisão) — ou seja, nunca era um dado observado separadamente, era uma cópia
exata do que `entry_price` já guardava até a 1ª atualização. Agora: no momento em que o alerta
Telegram É REALMENTE ENVIADO (`mid is not None`, depois dos checks de atraso/rate-limit/idempotência
já existentes), `entry_price_alerta` é sobrescrito com o fechamento do ÚLTIMO candle que o detector
já tem naquele instante (`det.bars[-1].close`) — **zero chamada de rede nova** (decisão do operador:
reusar dados já buscados pelo ciclo, nunca uma cotação em tempo real separada). Na maioria dos casos
isso ainda vai coincidir com o preço modelado (envio na mesma passada da detecção); só diverge
quando o envio acontece DEPOIS da detecção com um candle mais novo já ingerido (alerta atrasado, ou
reenviado num restart que repete candles já persistidos) — nesses casos o valor passa a ser
genuinamente observado, separado do modelado, honesto com o que o pedido descreveu.

O INSERT continua gravando o valor provisório (`ev.data["close"]`) como antes — a mudança só afeta
sinais cujo alerta é efetivamente enviado (`v3_alertas=True` e nada bloqueia o envio).

## Testes

12 testes novos: `signals_mvp/tests/test_pos_runner_v3_live.py` (5 — entry_price_alerta no envio
real vs. provisório sem alerta; sombra grava 1 linha por horizonte com status/tp1, horizonte não
decorrido fica pendente, sem trajetória confirmada nunca calcula nada) + 20 de
`test_saida_fiel.py`/6 de `test_retrospectivo_saida_fiel.py` (Partes 1/2 desta mesma rodada,
reusados pela sombra sem duplicar lógica). Suíte completa (ver resposta final) OK, incluindo os 97
testes pré-existentes de `test_pos_runner_live.py`/`test_pos_runner_v1_live.py` sem nenhuma quebra.

## Comandos na VM (restart NECESSÁRIO — mudança de código ao vivo em `live.py`/`storage.py`)

**Pré-condição do pedido**: só reiniciar com **POSIÇÕES ABERTAS V1=0 e V2=0** (confirmar com
`python -m signals_mvp.scripts.saude --db signals_mvp/dados/estado.sqlite` antes) — V3 nunca teve
banca própria nesta entrega, então posição aberta de V3 não bloqueia o restart.

```
git pull origin signals-mvp

# confirmar V1/V2 sem posicao aberta antes de reiniciar:
python -m signals_mvp.scripts.saude --db signals_mvp/dados/estado.sqlite

# repetir a capacidade ja em vigor (emenda 2026-11-05, item 3) -- nunca mudar aqui:
grep POS_RUNNER_MAX_POOLS .env   # confirmar =45 (ja deve estar, so repetir se faltando)

# RESTART NECESSARIO (mudanca de codigo ao vivo: __init__/garantir_saida_fiel_registrada,
# _entry_v3/entry_price_alerta, _sombra_saida_fiel_v3/pr3_saidas_sombra).
sudo systemctl restart <nome-do-servico-systemd-do-bot>

# depois do restart, confirmar que a sombra esta sendo gravada (1a linha deve aparecer no 1o
# sinal V3 com trajetoria confirmada, dentro de ~1 ciclo):
sqlite3 signals_mvp/dados/estado.sqlite "SELECT COUNT(*) FROM pr3_saidas_sombra;"
```

## Status

**IMPLEMENTADO em 2026-11-06.** Zero execução/restart feito por este commit — a execução real na VM
fica para o operador, pelos comandos acima.
