# Wallet Forward Runtime v2 — causal boundary and quote completeness

## Status

**IMPLEMENTADO / TESTADO EM SUÍTE / AGUARDANDO PRÓXIMA VALIDAÇÃO OPERACIONAL.**

Runtime novo:

`wallet_forward_runtime_v2_causal_boundary`

Esta revisão não altera nenhuma estratégia, não cria ordens e não muda a coorte econômica. Ela corrige riscos metodológicos/operacionais na formação da evidência Wallet Forward.

## Por que houve uma v2

Durante a auditoria do coletor foram encontrados dois riscos que não deveriam permanecer implícitos:

1. uma transação histórica cuja hidratação RPC falhou no bootstrap poderia se tornar legível em um ciclo posterior e parecer uma ação forward nova;
2. o Quote Watch persistia apenas probes realmente iniciados, então um probe que nunca chegou a ser tentado por corrida de fim de janela/backlog não aparecia na tabela de attempts e poderia desaparecer do denominador.

Também faltava registrar qual versão operacional havia produzido cada `wallet_forward_run`.

## Causal boundary de chain time

O `wallet_watch_forward.py` v2 congela uma fronteira causal **depois do bootstrap e antes do primeiro ciclo forward**.

`capture_new_wallet_actions(...)` agora recebe `not_before_chain_time`.

Uma transação que:

- não estava na lista local conhecida porque a hidratação falhou no bootstrap;
- reaparece posteriormente;
- mas possui `chain_time` anterior ao início forward;

é mantida como assinatura conhecida, porém **não recebe `wallet_forward_observation`**.

Ela também incrementa `prestart_new_transaction_count`, preservando a razão da exclusão.

Isso prefere perder uma possível borda temporal próxima ao início a inventar uma ação forward a partir de backfill histórico.

## Auditoria de runs antigas

Runs antigas não são reescritas.

`wallet_forward_integrity.py` mede:

- observações com `observed_at` anterior ao manifest;
- `chain_time` anterior ao manifest;
- lag negativo;
- source lag >5min;
- source lag >1h;
- p50/p95/max source lag.

Labels:

- `CAUSAL_BOUNDARY_CLEAN`;
- `PRESTART_CHAIN_CAUTION`;
- `STALE_SOURCE_CAUTION`;
- `STALE_SOURCE_CRITICAL`;
- `CAUSAL_BOUNDARY_FAILED`.

`chain_time` poucos segundos antes do manifest é mantido visível e não é automaticamente tratado como fraude metodológica; lag grande é o sinal mais preocupante de backfill stale.

## Runtime version no manifest

`wallet_forward_runs` ganhou:

- `runtime_version`;
- `quote_intake_grace_seconds`.

Migração é deliberadamente conservadora:

- manifests existentes recebem `wallet_forward_runtime_v1_unversioned`;
- novas runs recebem `wallet_forward_runtime_v2_causal_boundary`.

Assim, abrir um banco antigo com código novo **não falsifica a versão que realmente gerou aqueles dados**.

## Limite da janela de observações

Na v1, `end_observation_id` era capturado somente depois que o Quote Watch terminava o drain.

Na v2:

1. Wallet Watch termina;
2. `ended_at` e `end_observation_id` são congelados imediatamente;
3. Quote Watch pode terminar grace/drain;
4. o manifest é fechado usando o limite de observações já congelado.

Isso separa corretamente:

- período de coleta de ações wallet;
- período posterior necessário apenas para completar quotes atrasadas.

## Quote intake grace

O Quote Watch é iniciado antes do Wallet Watch. A v2 mantém o intake de quotes aberto por pelo menos um ciclo adicional:

`max(5s, interval_seconds + 5s)`

Para polling de 30s, isso resulta em 35s de grace.

A razão é operacional: o último ciclo RPC não deve ficar sem quote apenas porque o relógio do processo de quotes começou alguns segundos antes.

O valor fica salvo no manifest.

## Cursor de intake bounded

`load_forward_buys_after(...)` ganhou `through_id`.

O watcher agora faz:

```text
freeze MAX(id)=N
-> lê exatamente (cursor, N]
-> só então avança cursor=N
```

Isso remove uma race em que uma row inserida durante o SELECT poderia ser retornada em um ciclo e reaparecer/ser pulada no seguinte por uma fronteira não atômica.

## Final intake sweep

Quando a janela de intake termina, o Quote Watch executa uma varredura bounded final antes de entrar somente em drain.

Isso cobre BUYs já persistidos perto do deadline mesmo se o processo esteve ocupado atendendo quotes.

## Missing probes no denominador

Mesmo com grace/final sweep, qualquer coleta real pode ter overload/interrupção.

`src/wallet_quote_completeness.py` + `wallet_quote_completeness.py` reconstruem o conjunto **esperado**:

```text
cada BUY causal da run
×
cada delay congelado no manifest
```

E comparam contra `causal_quote_attempts`.

Relatório:

- attempts esperados;
- attempts realmente iniciados;
- probes ausentes;
- attempts inesperados;
- cobertura por delay;
- quantos BUYs tiveram todos os delays tentados.

Isso corrige o viés de observar somente requests que chegaram a acontecer.

Sucesso HTTP/quote continua uma métrica separada. Primeiro perguntamos se o probe foi tentado; depois se foi bem-sucedido.

## Quote price drift

A v2 de análise também acrescentou `wallet_quote_drift.py`.

Cada quote atrasada é pareada **somente com o +0 do mesmo wallet BUY**.

Para BUY:

- preço maior depois = drift adverso positivo.

Para SELL, quando essa coleta existir:

- preço menor depois = drift adverso positivo.

O relatório mantém cobertura pareada, p50/p95, melhor/pior drift, atraso do request e mudança de route id.

Isso mede penalidade temporal de rota; não mede retorno do token e não prova edge.

## Multi-wallet convergence

`wallet_forward_convergence.py` usa as mesmas ações forward e detecta quando uma nova wallet única faz o mesmo token cruzar o threshold de convergência.

Padrão exploratório:

- 300s;
- >=2 BUY wallets únicas;
- cooldown 1800s por token;
- causalidade por `observed_at`.

O BUY que fecha a convergência é ligado às próprias attempts Jupiter, permitindo auditar se havia route quote disponível naquele instante/delay.

Convergência é variável de pesquisa, não sinal e não prova que as wallets possuem informação especial. Target x placebo pré-período continua obrigatório para inferência econômica.

## Compatibilidade com a coleta de 6h iniciada em 2026-08-31

A coleta que já estava rodando quando a v2 foi implementada **não deve ser reiniciada**.

Ela foi iniciada com o runtime anterior. Ao abrir o banco posteriormente com código v2, o manifest existente será marcado como:

`wallet_forward_runtime_v1_unversioned`

sem reescrever suas observações.

Depois da execução, devemos auditar explicitamente:

```powershell
python wallet_forward_integrity.py
python wallet_quote_completeness.py
python wallet_forward_checkpoint.py
python wallet_forward_convergence.py
python wallet_quote_drift.py
```

Se a run v1 estiver limpa, seus dados continuam úteis. Se aparecer prestart/stale source ou probes não tentados, essa missingness/contaminação entra no diagnóstico em vez de ser escondida.

## Guardrails

- nenhum dado antigo é reclassificado como v2;
- nenhum missing probe é inventado como provider failure;
- nenhum quote é tratado como fill;
- nenhum convergence event é tratado como edge;
- nenhum filtro Wave foi alterado;
- nenhuma chave privada, assinatura ou `/execute` foi adicionada.
