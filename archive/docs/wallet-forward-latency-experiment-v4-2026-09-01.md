# Wallet Forward Latency Experiment v4 — 2026-09-01

Status: **PLANEJADO / IMPLEMENTADO, aguardando smoke/forward sample**.

## Por que este experimento existe

A primeira run real Wallet + Jupiter (`wallet-forward-1788217626-543a9b6b`) foi operacionalmente limpa e revelou um gargalo importante de timing:

- 13 BUYs reais, 65/65 probes Jupiter tentados e bem-sucedidos;
- chain -> detecção mediana: 37s;
- no grid +0 após detecção, chain -> quote mediana/p95: 47s/49s;
- 0% das entradas proxy +0 chegaram em <=30s desde o swap original;
- 3tc4 dominou a amostra: 12/13 BUYs e apenas 2 tokens;
- 76,9% dos BUYs eram repetições no mesmo wallet x token.

A leitura do código mostrou que o watcher histórico não enviava `commitment` explicitamente para `getSignaturesForAddress`/`getTransaction`. O RPC Solana usa `finalized` como padrão quando commitment é omitido. Portanto, reduzir apenas o polling de 30s para 10s poderia atacar somente uma parte do atraso.

## Mudança metodológica

O runtime v4 torna commitment explícito e separa regimes pelo nome do runtime:

- `wallet_forward_runtime_v4_rotating_poll_confirmed_commitment`
- `wallet_forward_runtime_v4_rotating_poll_finalized_commitment`

O experimento orquestrado passa a usar `confirmed` por padrão para pesquisa de latência. `wallet_watch_forward.py` isolado continua conservador e usa `finalized` por padrão.

`confirmed` não é tratado como evidência definitiva de permanência no ledger. Após a run, `wallet_forward_finality.py` consulta `getSignatureStatuses` e mantém `confirmed`, `processed`, `missing` e `finalized com erro` visíveis.

## Próxima coleta recomendada

Objetivo: descobrir se o gargalo de ~37s era predominantemente finality ou polling/processamento.

Coorte: a mesma usada na baseline para maximizar comparabilidade:

- 7mPti
- Gf9X
- 3tc4

Primeiro teste recomendado: **2h, polling 10s, commitment confirmed, Jupiter proxy**.

```powershell
python wallet_forward_experiment.py `
  --file wallets/forward-watch-archetypes-2026-08-31.txt `
  --hours 2 `
  --interval-seconds 10 `
  --rpc-commitment confirmed `
  --with-jupiter-quotes
```

Este teste muda duas dimensões frente à baseline (commitment e intervalo) porque o objetivo operacional é medir o melhor timing alcançável pelo watcher HTTP atual, não estimar causalmente a contribuição isolada de cada parâmetro. Se precisarmos decompor a melhora, uma run posterior `confirmed + 30s` pode servir de controle.

## Critérios técnicos de leitura

Não existe gate de edge aqui. Os critérios são de observabilidade:

1. causal integrity limpa;
2. zero ou missingness explicitamente pequeno e explicado;
3. sem explosão de falhas RPC/Jupiter com polling 10s;
4. redução material de chain -> detecção e chain -> quote +0 frente à baseline;
5. finality audit posterior sem assinaturas desaparecidas;
6. concentração por token/wallet continua reportada e impede pseudo-n.

Uma meta exploratória útil para o runtime HTTP atual é aproximar chain -> quote +0 mediano de <=20s. Isso **não é um gate econômico** e pode ser revisado se o RPC público impuser um piso maior.

## Próxima arquitetura se o piso continuar alto

Se `confirmed + 10s` ainda produzir atraso alto, não apertar polling indefinidamente. O próximo candidato técnico é um watcher orientado a evento/WebSocket ou provider de stream dedicado, com reconexão, deduplicação e verificação posterior de finality.

## Limites

- quote Jupiter continua proxy; não prova landing/fill;
- `confirmed` tem menor latência e menor certeza que `finalized`;
- finality limpa não prova copyability;
- mesmo timing melhor não resolve a dependência de 3tc4 em poucos tokens;
- nenhuma mudança desta etapa altera Wave v3, Wallet Strategy hypotheses ou libera shadow/live.
