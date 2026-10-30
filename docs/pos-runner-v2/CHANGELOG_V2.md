# POS-RUNNER-V2 — CHANGELOG

PAPER / READ ONLY. V2 = **a mesma estratégia da V1** ("regras do professor"), rodando em paralelo
sobre os **mesmos candles** (`pr_bars`), com **2 parâmetros diferentes** e **nenhum código novo de
detecção** (`detector_v1.py`, `simulate_v1.py` e `bankroll_v1.py` são reaproveitados tal como estão —
ver `signals_mvp/pos_runner/params_v2.py`, que só troca o arquivo de config, nunca a classe).

## Diferença em relação à V1 (congelada em `pos_runner_v1.yaml`, hash `279b79ffa3f0`)

| Parâmetro | V1 | V2 |
|---|---|---|
| `drop_max` (queda máxima aceita antes de invalidar a onda) | 0.90 (90%) | **0.96 (96%)** |
| `age_window_days` (janela de idade, filtro real) | `[2.0, 7.0]` | **`[2.0, 36500.0]`** (sem teto — 36500 dias ≈ 100 anos, equivalente a "sem teto" dentro da vida útil de qualquer token real) |

Tudo o mais — gatilhos, stop, TP1, exaustão, `dado_invalido`, gestão de banca, janela de ouro — é
**idêntico** à V1.

## Hash congelado ANTES do primeiro alerta

```
versao_config_v2 = d57b4331d51d
```

Calculado por `ParamsV1.version` (a MESMA função de hash da V1 — `short_hash({"pos_runner": "V1",
"params": ...})`) sobre o conteúdo de `pos_runner_v2.yaml`. Qualquer mudança nesse arquivo a partir de
agora é uma versão nova, nunca um retune da congelada — mesma disciplina da V1.

## Por que tabelas/CSV/banca próprias (`pr2_*`, nunca `pr1_*`)

A chave `UNIQUE` de `pr1_signals` é `(chain, pool, tf, evento, ts_fechamento)` — **sem** a versão. Se a
V2 escrevesse ali, uma ENTRADA da V2 no MESMO candle de uma ENTRADA da V1 colidiria com a linha da V1
(o `INSERT OR IGNORE` devolveria a linha da V1 já existente, com gatilho/risco/tags **da V1**, não da
V2). Por isso a V2 tem sua própria família de tabelas (`pr2_signals`, `pr2_filtrados`,
`pr2_bankroll_state`, `pr2_bankroll_trades`) com o MESMO schema, e seus próprios CSVs
(`pos_runner_v2.csv`, `pos_runner_v2_filtrados.csv`, `pos_runner_v2_banca.csv`). Estatísticas, banca
paper e `/relatorio` nunca se misturam entre as duas versões — máximo de posições abertas e os stops
diário/semanal valem **por versão** (cada uma tem seu próprio `BankrollLedgerV1`, mesma classe da V1,
estado separado por `versao_config_v2`).

## Alertas sem duplicar

A V2 roda **depois** da V1 sobre os mesmos candles do ciclo (nunca antes — garante que, se a V1
também decidiu no mesmo candle, a linha dela já está gravada quando a V2 checa). Quando a V2 fecha uma
ENTRADA:

- **Se a V1 TAMBÉM tem uma ENTRADA no MESMO `(pool, tf, ts_fechamento)`** (mesmo candle, mesmo
  gatilho — já que os únicos 2 parâmetros diferentes não afetam o cálculo de suporte/resistência/stop,
  os valores numéricos saem idênticos nesse caso): a V2 **nunca manda um alerta cheio novo** (seria
  texto repetido do que a V1 já mandou). Em vez disso, manda uma nota curta **em resposta** à mensagem
  da V1: `🔁 V2 CONFIRMA este sinal (tag: V1+V2) | config V2 <hash>`. `so_v2=False` nessa linha.
  TP1/EXIT FULL desse mesmo sinal na V2 também ficam **silenciosos no Telegram** a partir daí (as
  estatísticas/banca continuam sendo gravadas normalmente — só o envio de alerta repetido é que é
  suprimido, pela mesma razão).
- **Se a V1 NÃO tem uma ENTRADA no mesmo candle** (ex.: token com mais de 7 dias, que a V1 descarta por
  idade mas a V2 aceita): a V2 manda o alerta cheio normal, com a linha extra
  `⚠️ SOMENTE V2 (experimental)`. `so_v2=True` nessa linha — TP1/EXIT FULL desse sinal continuam
  alertando normalmente (não há alerta da V1 para evitar duplicar).

**Escopo desta regra:** só ENTRADA (o "sinal" que abre um trade paper, conforme o pedido). WATCHLIST e
ONDA_INVALIDA da V2 são eventos diagnósticos (nunca abrem trade) e continuam independentes por versão
— exatamente como V0 e V1 já mandam WATCHLIST independentes um do outro nesta base de código; podem
aparecer com texto parecido ao da V1 quando a zona de suporte/resistência calculada é a mesma (não é
um bug: é esperado, já que só `drop_max`/`age_window_days` diferem, e nenhum dos dois entra no cálculo
de zona).

## `/relatorio v1` / `/relatorio v2`

`/relatorio` sem argumento continua mostrando a V1 (compatibilidade com o comando que já existia).
`/relatorio v2` mostra o mesmo formato (por gatilho, por janela de ouro, por tag, por token, risco
fora da faixa por gatilho, histograma do % de stop) a partir das tabelas `pr2_*` — a V2 não tem botões
de feedback (👍/👎/📝, FASE 3) ainda, então a seção de votos sempre aparece vazia nesse relatório; isso
é esperado, não um defeito.

## Impacto no orçamento do GeckoTerminal / RPC

- **Candles: ZERO chamadas extras.** A V2 lê os MESMOS candles já buscados para a V1/V0
  (`pr_bars`, compartilhado) — ela nunca pede OHLCV de novo.
- **RPC/GT por ENTRADA da V2** (`holders`, `authorities`, busca VAMP): `authorities()` é cacheada por
  mint (`SolanaAdapter._authority_cache`) — se a V1 já consultou o mesmo mint, a V2 reaproveita o
  cache, zero chamada nova. `holders()` (contagem de concentração) e a busca VAMP (`/search/pools` do
  GT) **não são cacheadas** — cada ENTRADA da V2 (rara: só quando o detector da V2 realmente decide)
  gasta as mesmas poucas chamadas que uma ENTRADA da V1 já gastaria. Como ENTRADA é um evento raro
  (não por candle), o impacto é pequeno e proporcional a quantos sinais a V2 gera por dia — nunca ao
  volume de candles monitorados.
- `SEM_V2=1` desliga a V2 por completo: nenhum `DetectorV1` da V2 é criado, zero chamada adicional de
  qualquer tipo.

## Teste de equivalência

`signals_mvp/tests/test_pos_runner_v1_instrumentacao_equivalencia.py` roda o MESMO cenário (textbook +
TP1 + stop) com e sem `sem_v2=True` e confere que os campos NUCLEARES do sinal da V1 saem bit-a-bit
idênticos ao golden capturado antes desta fase, nos dois casos — a V2 nunca influencia a V1.
`signals_mvp/tests/test_pos_runner_v2_live.py` cobre: hash congelado e diferença de só 2 parâmetros,
alerta mesclado ("V1+V2") sem duplicar texto, alerta "SOMENTE V2" quando só a V2 decide, banca/CSV/
`/relatorio` nunca se misturando entre as versões, e `SEM_V2=1` não produzindo nenhuma linha da V2.

## O que o operador roda na VM

```bash
git pull
tmux attach -t bot
# Ctrl+C para parar
./scripts/linux/iniciar.sh   # ou o comando que ja usa para subir de novo
```

Para desligar a V2 (ex.: economizar orçamento, ou só querer a V1 por enquanto):

```bash
echo "SEM_V2=1" >> signals_mvp/.env
```
