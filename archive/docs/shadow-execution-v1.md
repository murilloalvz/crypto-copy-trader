# Shadow Execution v1 — Audit Layer

## Status

IMPLEMENTADO COMO INFRAESTRUTURA DE AUDITORIA / NÃO ATIVADO COMO ESTRATÉGIA.

Esta camada não envia transações, não possui chave privada e não altera `wave_v3_volume_integrity`.

## Objetivo

Deixar pronta a persistência que uma estratégia candidata usará quando chegar ao Gate de Shadow Execution. O foco inicial é impedir duas classes de erro:

1. modificar silenciosamente a configuração durante a mesma coorte;
2. registrar uma decisão como se ela tivesse usado um quote que ainda não estava disponível.

## Shadow run congelado

`start_shadow_run(...)` registra:

- `run_key` único;
- `strategy_version`;
- `activated_at`;
- configuração canônica em JSON;
- status e notas.

Reabrir o mesmo `run_key` com exatamente a mesma configuração é idempotente. Tentar reutilizá-lo com outra configuração, versão ou T0 é rejeitado.

Isso permite comparar uma coorte shadow sem mover os critérios depois que os resultados aparecem.

## Decisão shadow

Cada `ShadowDecision` persiste:

- token;
- lado buy/sell;
- `decided_at`;
- `quote_observed_at`;
- fonte do quote;
- market price observado;
- preço de execução esperado;
- notional pretendido;
- motivo;
- contexto causal em JSON.

A store rejeita:

- quote observado depois da decisão;
- decisão anterior ao T0 da coorte;
- preços/notional inválidos;
- run inexistente ou fechado;
- reconfiguração silenciosa.

`decision_key` é idempotente dentro do run para evitar duplicidade de decisão no log.

## Limite intencional

Esta implementação é apenas o **audit trail** de shadow. Ela não decide quando comprar/vender e ainda não mantém posição/PnL. Essa separação é intencional: primeiro precisamos de uma estratégia candidata e quotes causais/executáveis para então conectar um runner sem acoplar lógica prematura ao banco.

## Próximas extensões quando um candidato passar o replay

1. shadow runner usa regras congeladas da estratégia;
2. cada intenção é persistida antes de qualquer avaliação posterior;
3. ledger shadow calcula posição, fills e PnL usando quotes causais;
4. relatório compara replay esperado x shadow observado;
5. somente depois é implementado/adaptado o Execution Engine real.

Nenhuma dessas etapas autoriza live automaticamente.
