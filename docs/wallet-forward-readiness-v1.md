# Wallet Forward Replay Readiness v1

Status: **IMPLEMENTADO / TESTADO** em `feat/exit-engine-v1`.

Objetivo: decidir se uma `wallet_forward_run` congelada possui dados tecnicamente utilizáveis para **causal replay descritivo** sem transformar completude de infraestrutura em alegação de edge.

## O que este gate NÃO faz

Ele não usa retorno, PnL, win rate, profit factor ou qualquer ranking econômico. Portanto ele não pode:

- aprovar uma wallet para cópia;
- declarar edge;
- promover uma hipótese para shadow;
- liberar live;
- escolher uma estratégia vencedora.

`economic_promotion_allowed` permanece sempre `False` nesta camada.

## Fontes usadas

Para uma única run manifest:

1. actions dentro de `(baseline_observation_id, end_observation_id]` e da coorte congelada;
2. causal integrity de `chain_time -> observed_at`;
3. BUYs forward da mesma run;
4. expectativa congelada `BUYs × quote_delays_seconds`;
5. attempts Jupiter ligados ao evento exato;
6. quantidade de BUYs com pelo menos uma quote de sucesso.

Success/failure de probes é contado somente para as chaves **esperadas** da run. Um probe extra ou antigo nunca melhora nem piora o gate.

## Labels

### `NO_CAUSAL_SAMPLE`

A run não produziu ações forward ou não produziu BUYs.

Interpretação: não é falha econômica. A amostra simplesmente não existe ainda.

### `DATA_QUALITY_BLOCKED`

A causalidade está comprometida, por exemplo:

- `CAUSAL_BOUNDARY_FAILED`;
- `STALE_SOURCE_CRITICAL`.

Interpretação: não usar a run para inferência econômica até entender a contaminação.

### `QUOTE_PATH_BLOCKED`

Existe BUY, mas o caminho causal de quote não foi observado de forma utilizável, por exemplo Jupiter desabilitado ou nenhum BUY com quote de sucesso.

### `PARTIAL_CAUSAL_REPLAY_SAMPLE`

Existe material causal utilizável, mas há missing probe, falha de provider, BUY sem quote ou attempt inesperado.

Replay descritivo é permitido **com missingness explícita**. Promoção econômica continua bloqueada.

### `CAUSAL_REPLAY_SAMPLE_READY`

Requisitos estruturais:

- run `COMPLETED`;
- causal integrity sem blocker;
- >=1 BUY forward;
- Jupiter habilitado;
- todos os probes esperados foram tentados;
- todo BUY possui >=1 quote de sucesso ligada ao evento;
- nenhum attempt inesperado dentro do escopo.

Isto significa apenas: **a run está estruturalmente pronta para causal replay descritivo**.

Não significa que a amostra é estatisticamente suficiente ou lucrativa.

## Runtime legacy

Runs anteriores a `wallet_forward_runtime_v2_causal_boundary` permanecem auditáveis como:

`wallet_forward_runtime_v1_unversioned`

Elas recebem caution explícita e dependem da auditoria de causalidade. Não são reescritas para fingir que usaram as proteções novas.

## Quote modes

- `proxy`: quote causal/rota; não é execução.
- `assembled_candidate`: transação candidata montada; ainda não prova landing/fill.

Nenhum dos dois equivale a execução real.

## CLI

```powershell
python wallet_forward_readiness.py
```

Run específica:

```powershell
python wallet_forward_readiness.py --run-key <run-key>
```

JSON:

```powershell
python wallet_forward_readiness.py --run-key <run-key> --json
```

## Perfil técnico por wallet

Para comparar a coorte sem inventar score ponderado:

```powershell
python wallet_forward_wallet_profiles.py --run-key <run-key>
```

O relatório mostra separadamente por wallet:

- ações BUY/SELL;
- source lag p50/p95/max;
- causal integrity;
- BUYs com quote;
- completude de probes;
- sucesso/falha esperados;
- quote drift pareado por delay.

A intenção é distinguir, por exemplo, uma wallet historicamente interessante porém rápida demais para nossa observabilidade de outra cujo comportamento parece temporalmente mais copiável.

Ainda assim, **observabilidade/copyability técnica != edge econômico**.

## Pós-run recomendado

O auditor consolidado inclui este gate e os perfis por wallet:

```powershell
python wallet_forward_postrun.py
```

A ordem metodológica permanece:

```text
integrity
-> completeness
-> observability
-> event-scoped quote/replay
-> readiness
-> per-wallet technical profile
-> somente então interpretação econômica
```
