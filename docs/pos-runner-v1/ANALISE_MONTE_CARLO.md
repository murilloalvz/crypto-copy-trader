# Monte Carlo em blocos — POS-RUNNER-V1 (`simulacao_bloco.py`)

Status: ferramenta de analise, PAPER / somente leitura. Nao e uma hipotese economica nova e nao
entra no `docs/research-hypothesis-registry-v1-2026-10-04.md` — e estatistica descritiva/preditiva
sobre uma hipotese que ja esta rodando ao vivo (POS-RUNNER-V1, config congelada `279b79ffa3f0`),
nao um teste de uma regra nova.

## O que faz

`python -m signals_mvp.analise.simulacao_bloco` le os trades que **já fecharam** na banca real da
V1 e projeta, por simulacao Monte Carlo, como a banca pode se comportar daqui pra frente — **sem
inventar nenhuma regra nova**: tamanho de posicao, limite de posicoes, stop diario e stop semanal
sao importados direto de `signals_mvp/pos_runner/bankroll_v1.py` e `params_v1.py` (nunca
duplicados). So roda com a versao congelada da V1 (`279b79ffa3f0`) e se recusa a rodar com menos
de 30 trades fechados dessa versao.

## Fontes de dado

| fonte | o que da |
|---|---|
| `dados/pos_runner_v1.csv` | 1 linha por sinal (inclusive em aberto) — usada so pelo `risco_pct` |
| `dados/pos_runner_v1_banca.csv` | 1 linha por sinal **fechado** da banca real (inclusive os que a trava recusou: `pulado: ...`/`sem dado: ...`) — da o resultado liquido, ja com slippage/custos reais |
| tabela `pr1_feedback` (SQLite, `dados/estado.sqlite`) | so contexto para o relatorio (votos/notas do operador); nunca entra na conta estatistica |

Os dois CSVs nao compartilham uma coluna-chave literal (isso so existe no SQLite, via
`pr1_signal_id`). A juncao usada aqui explora uma garantia do codigo: `BankrollLedgerV1.step` roda
exatamente 1 vez por sinal fechado, na mesma ordem cronologica em que esse sinal aparece em
`pos_runner_v1.csv`. Agrupando os dois arquivos por `(contrato, tf)` e casando posicao a posicao
dentro de cada grupo, a juncao fica exata — e se as contagens de algum grupo nao baterem, a
ferramenta se recusa a casar no chute (`ValueError` explicito, nunca um trade errado).

## O algoritmo, por rodada da simulacao

1. **Incerteza do edge**: sorteia uma taxa de acerto `p_win ~ Beta(n_ganhos+1, n_perdas+1)` — uma
   vez por rodada, nao por trade.
2. **Frequencia semanal**: para cada semana simulada, sorteia quantos sinais ela tem — Poisson
   calibrado pela taxa semanal observada (incluindo semanas sem nenhum trade, pra nao superestimar
   a taxa); se a frequencia semanal observada for superdispersa (variancia > media), troca
   automaticamente para binomial negativa. Nunca uma frequencia fixa.
3. **Bloco por dia**: a semana e preenchida sorteando (com reposicao) **dias historicos inteiros**
   até atingir a meta de sinais daquela semana. Isso preserva o agrupamento real: um dia que
   historicamente teve varios sinais entra como bloco, nao espalhado 1 por dia — o que importa pra
   valer porque e exatamente essa concentracao que aciona o limite de posicoes abertas e o stop
   diario por perdas seguidas. No **cenario de estresse**, dias cujo somatorio de R foi negativo
   ("dias ruins") tem peso 2x no sorteio.
4. **Payoff bootstrap**: cada sinal dentro do bloco tem seu resultado resorteado — ganhou/perdeu
   por `Bernoulli(p_win)`, e o tamanho vem de bootstrap do pool historico de ganhos ou de perdas
   (o par R-multiplo/risco sempre vem do MESMO trade real, nunca se mistura R de um trade com o
   risco de outro).
5. **Travas reais**: cada sinal passa pelo ledger simulado, que replica EXATAMENTE a logica de
   `BankrollLedgerV1.step` — mao fixa (US$10) abaixo de US$200, fracao de 10% da banca acima disso,
   maximo 3 posicoes abertas, stop diario (−10% no dia OU 3 perdas seguidas), stop semanal (−20%).

A seed e fixa (`SEED_PADRAO`): a mesma entrada sempre produz a mesma saida.

## Saida

Para os cenarios **normal** e **estresse**: mediana/p5/p95 da banca final, distribuicao do
drawdown maximo (mediana/p5/p95), probabilidade (com intervalo de confianca ~95%) de a banca tocar
50% da banca inicial, e a expectativa por trade em R com o limite inferior de 90% (bootstrap da
media em blocos por dia). Se esse limite inferior for ≤ 0, imprime **"NAO AUMENTAR A MAO"**.

## Como rodar

```
python -m signals_mvp.analise.simulacao_bloco
python -m signals_mvp.analise.simulacao_bloco --simulacoes 20000 --semanas 52
```

Tempo de execucao: no tamanho padrao (5.000 simulacoes x 26 semanas x 2 cenarios) fica em torno de
1 minuto num notebook comum; `--simulacoes`/`--semanas` ajustam o custo.

## Como interpretar (e como NAO interpretar)

- Isto e uma projecao estatistica sob as premissas acima, condicionada à amostra historica
  disponivel — **nao e uma previsao garantida nem uma promessa de retorno**. Com poucos trades
  (o minimo de 30 e um piso absoluto, nao uma amostra confortavel), o intervalo p5-p95 tende a ser
  largo e a taxa de acerto/payoff historicos podem nao se repetir.
- "NAO AUMENTAR A MAO" significa que, com 90% de confianca, a expectativa por trade observada nao
  esta comprovadamente acima de zero — operar exatamente como esta, sem aumentar o tamanho das
  posicoes, ate que a amostra cresca e a leitura mude.
- Os numeros aqui sao proprios desta rodada/amostra: nunca devem ser copiados para o `README.md`
  ou qualquer material de portfolio como se fossem retorno comprovado do sistema.
