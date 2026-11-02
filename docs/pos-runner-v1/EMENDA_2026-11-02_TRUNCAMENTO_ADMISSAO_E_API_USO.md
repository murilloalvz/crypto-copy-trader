# Emenda de AMOSTRAGEM/MEDICAO — coorte x admissao, cobertura de pr_api_uso, queda do pico (2026-11-02, 3a rodada)

PEDIDO 2026-11-02 (3a rodada). **Nao altera detector, regra de sinal, nem hashes V1
(`279b79ffa3f0`) / V2 (`d57b4331d51d`)** — tudo aqui e amostragem (como processar um candidato ja
congelado, quando contar uma chamada de rede) ou medicao pura.

## 1) Coorte retrospectiva x ao vivo: truncamento em `added_ts`

Candidatos do lote congelado (`pr_retro_candidatos`) que ganham vaga de verdade DEPOIS do
congelamento (ex.: PAWCAT/CATBOT admitidos em 02/11 21:43Z) tinham o replay retroativo rodando
sobre TODO o historico em cache, inclusive candles de DEPOIS da admissao — territorio do funil
FORWARD (`pr1_signals`/`pr2_signals`), contando o mesmo sinal 2x. Fix (`scripts/
avaliar_candidatos_retro.py: processar_candidato`): quando `pr_pools.added_ts` existe, o replay usa
`pr_bars` (tabela do bot ao vivo, SO LEITURA) TRUNCADO em `bar.ts + step < added_ts` (MESMA
comparacao de `decision_ts < added_ts` ja usada em `live.py`) — nenhum candle igual ou posterior a
admissao chega ao detector, pela construcao da lista, nunca por um filtro a posteriori. Zero
chamada de rede nesse caso (candle ja existe em `pr_bars`). Relatorio ganha a tag
`admitido_apos_congelamento`. A lista/hash congelados (`lista_hash`/`congelado_em`) NUNCA mudam — so
a FORMA de processar um candidato que ja esta na lista. Um resultado "ok" persistido ANTES da
admissao e invalidado e reprocessado (1 unica vez, sem rede) quando `added_ts` passa a existir
(`executar()`: compara `admitido_apos_congelamento` cacheado contra o estado atual de `added_ts`).
Teste de reproducao: `TruncamentoPosAdmissaoTests` (`tests/test_avaliar_candidatos_retro.py`) — um
candidato cujo rompimento real so aconteceria DEPOIS do corte fica com zero sinal retro e
`admitido_apos_congelamento=True`, enquanto um RUNNER ANTES do corte continua contando.

## 2) `pr_api_uso`: finalidades que faltavam

So `poll_pool` (GT/DexPaprika) era instrumentado. Cobertura nesta rodada:

- `carteiras` (RPC, `adapter.holders`): `live.py: _holders_instrumentado` — helper unico usado nos
  3 pontos de chamada (ENTRADA V1, ENTRADA V2, snapshot horario), conta via `SolanaRpc.calls`
  antes/depois (MESMA convencao de `poll_pool`, so chamada de rede DE VERDADE).
- `verificacao_candidato` (RPC, `LineageVerifier.step`): mesma convencao, via `self.rpc.calls`.
- `descoberta` (GT, `_discover`): mesma convencao, via `BudgetedHttp.used`.
- `coorte_retro`: UNICA finalidade gravada por um processo FORA do bot ao vivo —
  `avaliar_candidatos_retro.py` grava direto em `pr_api_uso` (tabela/DDL replicada no proprio
  script, idempotente) quando o fetch de rede (GT ou fallback DexPaprika) de verdade ocorre.
- `baseline`/`trajetoria`/`sombra`/`radar`: confirmados **arquiteturalmente zero-rede** — todos
  reusam os MESMOS candles ja buscados por `poll_pool` no mesmo ciclo (`pr_bars`/replay em memoria),
  nunca pedem rede propria. Documentado em `live.py: _refresh_core` (comentario) e na docstring de
  `avaliar_candidatos_retro.py`; sempre mostrarao 0 no relatorio, por construcao, nao por falta de
  instrumentacao.

`funil_diario.py: uso_api_24h` agora devolve `rate_limited_h_por_finalidade` (alem do agregado
`rate_limited_h` de sempre) — "429/h" no relatorio ganha o detalhe por finalidade entre parenteses
quando houver mais de uma. Testes: `ApiUsoInstrumentacaoTests` (`tests/test_pos_runner_live.py`,
`carteiras`/`verificacao_candidato`) e `test_uso_api_24h_breaks_down_rate_limited_by_finalidade_*`
(`tests/test_funil_diario.py`).

## 3) `saude.py`: queda do pico para pools "mc_ok"

Pools classificados "mc_ok" (MC atual acima do piso, mas sem evidencia MC-isolada de incapacidade)
mostravam so o rotulo "queda nao avaliada aqui" — o calculo precisa de replay causal, considerado
caro demais para rodar em TODO pool ativo a cada heartbeat. Fix (`_queda_do_pico_mc_ok`): replay
leve, SO para quem ja cai neste bucket (nunca para todo pool ativo), reusando o MESMO
`DetectorV1.drop_pct()`/`_replay_historico` de `diagnostico_vagas.py: secao_a` — motivo passa a
`mc_ok (queda=XX.X%)` quando o replay consegue calcular, mantendo o rotulo antigo so quando o
replay falha ou nao ha candle suficiente. Anexado na MESMA linha de rotacao (nunca uma linha nova —
o relatorio ja estava no teto de 60 linhas). Teste:
`test_fila_section_shows_queda_do_pico_for_an_mc_ok_pool` (`tests/test_saude.py`).

## Testes e hashes

Suite completa + os testes novos desta rodada: ver resposta final do operador. Hashes congelados
intactos durante toda a rodada: `ParamsV1=279b79ffa3f0`, `ParamsV2=d57b4331d51d`.

## Comandos na VM

```
git pull origin signals-mvp
# RESTART necessario (instrumentacao pr_api_uso em live.py roda dentro do processo do bot ao vivo)
python -m signals_mvp.scripts.saude --db dados/estado.sqlite
python -m signals_mvp.scripts.funil_diario --db dados/estado.sqlite
tmux new -s retro   # ou reusar a sessao existente -- idempotente/retomavel
python -m signals_mvp.scripts.avaliar_candidatos_retro --db dados/estado.sqlite
```
