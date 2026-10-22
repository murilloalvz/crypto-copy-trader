# Protocolo de validação — POS-RUNNER-V1 (`279b79ffa3f0`)

Status: **PRE-REGISTRADO** antes da coleta que vai julgá-lo. Regra congelada no momento deste
documento; nenhum parâmetro pode mudar no meio da coleta (mudar parâmetro = versão nova, nunca um
retune desta mesma validação).

Esta é a instrumentação de medição da POS-RUNNER-V1 — não é um detector, stop, tamanho ou filtro
novo. Este protocolo formaliza COMO o resultado acumulado vai ser julgado, usando os campos que a
instrumentação agora grava (`pos_runner_v1_banca.csv`, `pr1_bankroll_trades`).

## Métrica

PnL em **R** por trade fechado: `R = lucro_liquido_% / risco_%` (o mesmo R-multiplo usado em
`signals_mvp/analise/simulacao_bloco.py`) — `lucro_liquido_%` já líquido de slippage/custos reais
(`pos_runner_v1_banca.csv`), `risco_%` é a distância entrada→stop do sinal (`pos_runner_v1.csv`).
Só entram trades **fechados** (a trava de banca executou de fato — "pulado: ..." / "sem dado: ..."
não contam).

## Regras de decisão (fixas, nesta ordem)

1. **Futilidade antecipada**: com **n = 15** trades fechados, se a média de R estiver **< −0,5 R**,
   a hipótese para aqui — `FUTIL`. Não espera os 30 trades completos.
2. **Decisão em n = 30**: com **n = 30** trades fechados (e não tendo parado por futilidade), calcula
   o limite inferior unilateral de 90% da expectativa em R (bootstrap em blocos por dia — mesmo
   método de `simulacao_bloco.expectancia_r_limite_inferior`).
   - limite inferior **> 0** → `PASS` nesta rodada.
   - limite inferior **≤ 0** → `FAIL` nesta rodada (o que o script já imprime como "NÃO AUMENTAR A
     MÃO").
3. Esta validação por si só não promove a hipótese a `VALIDADA` — isso continua exigindo os 3 passos
   do registro de hipóteses (PASS na pré-registrada, PASS na replicação fresca, líquido de custos
   positivo no Gate 2), conforme a disciplina do repositório.

## O que NÃO pode acontecer no meio da coleta

- trocar `pos_runner_v1.yaml`/`params_v1.py` (muda o hash `279b79ffa3f0` → vira outra versão, os
  trades não se somam);
- trocar a métrica (ex.: usar % em vez de R, ou outro período de corte);
- re-rodar a regra de futilidade com um n diferente de 15 depois de já ter visto o resultado em 15;
- misturar trades de versões de config diferentes na mesma contagem.

## Como consultar o estado atual

```
python -m signals_mvp.analise.simulacao_bloco
```

(recusa automaticamente abaixo de 30 trades fechados — para acompanhar a futilidade em n=15 antes
disso, calcule a média de R diretamente de `pos_runner_v1_banca.csv` ∕ `pos_runner_v1.csv`, filtrando
`versao_config_v1 = 279b79ffa3f0`).

## Rastreabilidade

Esta validação consome os trades que a instrumentação de medição (campos `ts_fechamento_candle`,
`ts_alerta`, `ts_envio_telegram`, `liquidez_usd`, `retorno_sol_dia` em `pos_runner_v1.csv`; `preco_real`/
`slippage_entrada_pct`/`slippage_saida_pct` em `pos_runner_v1_feedback.csv`; `/pulei` em
`pos_runner_v1_pulados.csv`) grava desde a mesma revisão que criou este documento — nenhum desses
campos entra na métrica de R acima (são contexto/auditoria, nunca usados para decidir PASS/FAIL).
