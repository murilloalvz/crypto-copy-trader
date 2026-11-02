# Emenda — coorte retrospectiva dos candidatos sem vaga (2026-11-02)

PEDIDO 2026-11-02 PARTE 2 (segue a PARTE 1, `scripts/diagnostico_vagas.py`/`saude.py`: "aqui estão os
motivos que travam a rotação" — esta emenda responde "o que teria acontecido aos candidatos que nunca
ganharam vaga?"). **Não altera regra de gatilho/entrada/stop/saída da V1 (hash `279b79ffa3f0`) nem da V2
(hash `d57b4331d51d`)**, não grava em `pr_pools`/`pr1_signals`/`pr2_signals`/`pr_funil_marcos` nem em
nenhuma tabela que o funil forward, H1 ou `/analise` leem. A única tabela nova é `pr_retro_candidatos`
(congelamento); nenhuma tabela já existente é alterada.

## Por que é replicação, não validação

A amostra não é sorteada nem pré-registrada antes da coleta (ao contrário do N=30 do protocolo,
`docs/pos-runner-v1/PROTOCOLO_VALIDACAO.md`) — é a população de candidatos que **o próprio bot** já
descartou por falta de vaga, com qualquer viés de seleção que isso implique (ex.: candidatos que nunca
ganharam vaga podem ser sistematicamente diferentes dos que ganharam — ver comparação barrada vs
admitida no relatório). Por isso:

- **NUNCA soma ao N=30** nem a nenhum H1/H2 confirmatório;
- é rotulada `retro_sem_vaga`, nunca entra em `pr_pools`/sinais reais/funil forward/`/analise`;
- cada sinal carrega `retroativo=True` explícito no relatório — a guarda de atraso (`_late`, FASE 1 da
  PARTE 1) nunca se aplica (é retroativo por definição, não um candle recém-fechado);
- serve só para orientar a discussão sobre o custo de oportunidade do `max_pools` atual, nunca para
  decidir um limiar.

## Congelamento (1ª execução apenas)

Candidatos = pools distintos que já apareceram em `pr_vaga_descartes` (todo o histórico, não só 48h) e
cujo `pr_pools` nunca registrou `'ativo'` — aproximação read-only (o schema não guarda histórico de
status): exclui o status atual `'ativo'/'dormente'/'encerrado'` (dormente/encerrado só existem para
quem FOI ativo) e qualquer pool com linha em `pr_dormentes` ou em `pr1_signals`/`pr2_signals`. A lista é
gravada em `pr_retro_candidatos` com o sha256 da lista ordenada de pools (`lista_hash`) e o timestamp do
congelamento (`congelado_em`); toda execução seguinte **lê de volta** esta mesma lista, nunca recalcula
— mesmo que novos pools entrem em `pr_vaga_descartes` depois.

## Histórico (orçamento próprio, nunca compete com o bot ao vivo)

`OhlcvStore.history` — MESMO módulo do bot ao vivo, cache em disco PRÓPRIO desta execução
(`dados/pos_runner_retro/ohlcv`, 100% retomável: a caminhada fica no checkpoint em disco, uma execução
interrompida continua exatamente dali). `--max-chamadas-hora` (padrão 15) é um orçamento próprio
(persistido em `retro_orcamento.json`, por hora UTC) — ao esgotar, a execução atual para de pedir candle
novo e imprime o relatório só com o que já tem; a próxima execução retoma os candidatos que faltam.
Fallback DexPaprika (`worker.make_dexpaprika_provider`, MESMO toggle `DEXPAPRIKA`/`DEXPAPRIKA_API_KEY` do
bot ao vivo) só quando o GeckoTerminal falha — orçamento próprio do DexPaprika (créditos/breaker), nunca
compartilha o `--max-chamadas-hora` do GT.

Mesma validação de candle do bot ao vivo: `qualidade_v1.avaliar_qualidade` (dado_invalido bloqueia) e o
veto de candle suspeito (`qualidade_candle.motivo_suspeito`) já embutido no próprio `DetectorV1` — nenhuma
lógica de qualidade nova. Dedupe de candle vem do cache do `OhlcvStore` (chave por `ts`).
`contaminado_candle` é tag SÓ do operador (marcação manual pós-fill real) — não existe fill real aqui,
nunca se aplica (limitação documentada, nunca simulada).

## Replay e simulação

Candle a candle, causal (`DetectorV1.update`, zero lookahead), desde o candle que contém a criação do
token. Cada `ENTRADA` é simulada com `simulate_v1` — MESMOS `ParamsV1`/`ParamsV2`/`CostModel` congelados
do bot ao vivo, SEM `candle_confiavel` (candles já fechados há muito tempo; `simulate_v1` documenta que
omitir o argumento dá a decisão IDÊNTICA à de antes do patch de candle suspeito recente) e SEM cotação
SOL/USD cacheada (`sol_usd_at` sempre `None` — `CostModel` já trata isso como o caso conservador padrão,
teto de fee PumpSwap/slippage 1%, o MESMO fallback que o bot ao vivo usaria sem cotação cacheada). Risco
real <3% exclui o R (`r_mult=None`, motivo `risco_irrealista`) — MESMA regra de
`PosRunnerLive.RISCO_IRREALISTA_MIN_PCT`, importada direto da classe, nunca duplicada.

## Relatório

Por candidato: pico MC do histórico, chegou a RUNNER?, teve ENTRADA V1/V2?, status/R de cada sinal.
Agregado: n com histórico suficiente, % que chegou a runner, nº de sinais V1/V2, R médio/mediano (só
entre os R não excluídos), taxa de acerto. Comparação barrada (este congelamento) vs admitida
(`pr_pools.status IN ('ativo','dormente','encerrado')`, leitura pura — sem replay): MC no achado médio,
idade média, % que chegou a runner (via `pr_funil_marcos.etapa='runner'`, marco já persistido pela PARTE
1, nunca recalculado aqui).

## Comandos na VM (tmux separado — nunca a sessão do bot ao vivo)

```
git pull origin signals-mvp
tmux new -s retro
python -m signals_mvp.scripts.avaliar_candidatos_retro --db dados/estado.sqlite
# Ctrl+B D para destacar; execução idempotente/retomável -- rodar de novo so avanca o que falta
python -m signals_mvp.scripts.avaliar_candidatos_retro --db dados/estado.sqlite --max-chamadas-hora 10
```

Não precisa reiniciar o bot ao vivo (só leitura do mesmo `.sqlite`, cache/orçamento em diretório
separado — o bot ao vivo nunca sabe que esta execução existe).
