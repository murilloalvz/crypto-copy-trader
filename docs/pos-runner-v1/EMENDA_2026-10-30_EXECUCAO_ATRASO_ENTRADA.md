# Emenda de EXECUÇÃO — guarda de atraso na ENTRADA (2026-10-30)

PEDIDO 2026-10-30 (FASE 1 do pedido de backfill/atraso). **Não altera regra de gatilho/entrada/
stop/saída da V1 (hash `279b79ffa3f0`) nem da V2 (hash `d57b4331d51d`)** — a mudança é de QUANDO o
bot executa a decisão já tomada pelo detector (gating de execução), nunca de QUAL decisão o
detector toma.

## O achado

Investigação em código (sem acesso ao banco real da VM) mostrou que o diagnóstico anterior ("o
detector só recebe candles desde a admissão") estava **incompleto**:

- `live.py: _refresh_core` já chama `self.ohlcv.history(pool, tf, grad_ts, now, ...)` em TODA
  atualização — isso busca o histórico **completo** desde a graduação (não só desde a admissão),
  via `OhlcvStore` (`pos_runner/candles.py`), que pagina (`before_timestamp`, até 1000 candles por
  chamada) e retoma entre ciclos (checkpoint em disco), respeitando o orçamento/429 compartilhado.
  Pool admitido depois de esperar muito na fila **já** reconstrói pico/queda/caixa anteriores à
  admissão — isso nunca foi um backfill ausente.
- `live.py: _on_event_v1`/`_on_event_v2` já tinham uma guarda `tracked` (`ev.decision_ts >=
  added_ts`) que descarta silenciosamente qualquer evento decidido num candle anterior à promoção
  do pool a `'ativo'`.
- A guarda de atraso (`_late`) já existia, mas só protegia **WATCHLIST**/**ONDA_INVALIDA**
  (`live.py:1924`/`2186`) e o envio do **alerta Telegram** da ENTRADA (`live.py:2068`/`2277`, limiar
  `max(300s, step/2)`) — nunca a **criação do sinal/posição** (`pr1_insert_signal`/
  `pr2_insert_signal`) em si. Se o catch-up de um pool (walk de `OhlcvStore`, potencialmente em
  vários ciclos) alcançasse uma ENTRADA antiga só depois de `now` já ter avançado bastante, o bot
  abria uma posição de paper real e silenciosa (sem alerta, por já cair na guarda do Telegram) com
  preço/geometria de um candle velho.

## A correção (FASE 1a)

`_entry_v1`/`_entry_v2` agora aplicam o MESMO `_late()` (limiar `max(300s, step/2)`, idêntico ao que
já existia) **antes** de montar/inserir `row_insert` — ENTRADA atrasada nunca cria
`pr1_signals`/`pr2_signals`, nunca alerta, nunca abre posição. O descarte é registrado em
`pr_entradas_atrasadas` (pool, versão, tf, `candle_ts`, atraso em segundos) — o funil/`saude.py`
contam a partir daí (`entradas_atrasadas (24h, nunca abriram posição)`). A guarda de atraso
pré-existente no envio do Telegram (para o caso raro de retry após reinício, candle não mais tão
recente) continua intacta, sem mudança.

## Medição do que o pool perde esperando vaga (FASE 1b)

`_on_event_v1`/`_on_event_v2` agora também contam, quando `tracked` é `False` especificamente por
`ev.decision_ts < added_ts` (nunca pelo motivo de versão), 1 linha em `pr_eventos_pre_admissao` por
evento WATCHLIST/ENTRADA/ONDA_INVALIDA — mede quantos setups reais aconteceram no mercado enquanto
o pool ainda esperava vaga (item do funil de descoberta→fechamento, não um bug a corrigir aqui).

## Auditoria retroativa (FASE 1c)

`scripts/auditar_atraso_entradas.py` (só leitura de rede, escreve só tag + a coluna nova
`atraso_candles` quando ainda `NULL`) tagueia `entrada_atrasada` em ENTRADAs já existentes cujo
`alert_ts`/`ts_alerta` ficou acima do mesmo limiar. `analise/condicional.py` exclui sinais
`entrada_atrasada` de H1-H8 por padrão (mesmo padrão de `risco_irrealista`/`contaminado_candle`) e
reporta a sensibilidade do veredito de H1 com/sem essa exclusão
(`RelatorioCondicional.h1_com_entrada_atrasada`).

## Nova coluna/tabelas

- `pr1_signals.atraso_candles` / `pr2_signals.atraso_candles` (REAL, nullable): candles de atraso
  entre o fechamento do candle-gatilho e a decisão do bot. `0` no caso normal (candle atual).
- `pr_entradas_atrasadas` (ts, versao, pool, tf, candle_ts, atraso_s): ENTRADA descartada por
  atraso, nunca chegou a criar sinal.
- `pr_eventos_pre_admissao` (ts, versao, pool, tf, kind, candle_ts): WATCHLIST/ENTRADA/ONDA_INVALIDA
  decidido antes de `added_ts`.

## Comandos na VM

```
git pull origin signals-mvp
python -m signals_mvp.scripts.auditar_atraso_entradas --db dados/estado.sqlite
# restart do bot pra FASE 1a/1b entrarem em vigor nos ciclos seguintes
```
