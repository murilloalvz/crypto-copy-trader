"""Parte A do POS-RUNNER-V0 — backtest historico SEM VIES (pronto para rodar; NAO roda antes do OK do operador
no Passo 0 e do pre-registro congelado).

Ordem obrigatoria (cada passo grava checkpoint e pode ser retomado):
  1. `plano`         — periodos (discovery / embargo / holdout) e o sorteio das janelas, com hash;
  2. `selar-holdout` — enumera as janelas do holdout (sem preco) e grava a lista selada + hash (commitar!);
  3. `discovery`     — enumeracao -> estagio 1 (1h, quem virou runner) -> estagio 2 (5m/4h) -> detector ->
                       trades A/B -> linha de base pareada; para pela contagem de setups, nunca pelo retorno;
  4. `escolher`      — variante (tf x saida) pelo EV liquido; criterio de candidato;
  5. `holdout`       — so a variante escolhida, nas janelas seladas;
  6. `relatorio`     — em portugues simples, com graficos de 5 trades sorteados.
O codigo de discovery recusa qualquer pool do holdout selado.
"""
