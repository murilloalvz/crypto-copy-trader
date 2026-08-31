# Wallet Strategy Readiness v1

## Status

IMPLEMENTADO como ferramenta de pesquisa operacional. Não calcula PnL, não mede copyability, não executa ordens e não altera `wave_v3_volume_integrity`.

## Objetivo

Transformar a gate de evidência do Wallet Strategy Lab em um diagnóstico explícito: para cada wallet, mostrar por que o fingerprint ainda não está pronto e qual coleta adicional tende a reduzir a incerteza.

O comando principal é:

```powershell
python wallet_strategy_readiness.py --all-local --min-swaps 20
```

Também aceita endereços explícitos e `--file`.

## Estágios

- `DESCRIPTIVE_READY`: passou na gate descritiva cross-wallet. Isso não significa edge.
- `EVIDENCE_GAPS`: há amostra útil, mas faltam cobertura/diversidade/saídas suficientes.
- `INSUFFICIENT_SAMPLE`: amostra ainda pequena demais para diagnóstico forte.

## Bloqueios auditados

A ferramenta expõe explicitamente, entre outros:

- amostra geral insuficiente;
- menos de 20 swaps no diagnóstico operacional;
- menos de 10 tokens;
- menos de 50% de roundtrips observados;
- menos de três ciclos complete-like;
- janela observacional curta;
- baixa cobertura de sequência;
- sizing de saída insuficiente;
- anomalias de quantidade no sizing.

## Ações de pesquisa

As ações não são sinais de trading:

- `SELECTIVE_BACKFILL_SEQUENCE`: tentar completar buys/sells faltantes e melhorar roundtrip coverage;
- `SELECTIVE_BACKFILL_BREADTH`: buscar mais tokens e/ou uma janela maior;
- `SELECTIVE_BACKFILL_EXITS`: aumentar ciclos de saída observáveis;
- `DATA_QUALITY_AUDIT`: revisar anomalias antes de interpretar sizing;
- `FORWARD_WATCH_OBSERVABILITY`: acompanhar causalmente uma wallet ainda não pronta para medir nossa capacidade de observá-la e a latência real;
- `FORWARD_WATCH`: acompanhar forward uma wallet já descritivamente madura;
- `CAUSAL_CONTEXT_REVIEW`: preparar contexto/replay causal sem transformar fingerprint em regra automática.

`FORWARD_WATCH_OBSERVABILITY` é proposital: uma wallet como candidato ultra-short pode ser útil para medir se o nosso polling consegue enxergar sua atividade a tempo mesmo antes de a estratégia histórica estar reconstruída com qualidade suficiente.

## Guardrails

1. Menos bloqueios não significa maior lucratividade.
2. `DESCRIPTIVE_READY` não significa que a wallet deve ser copiada.
3. Forward observability mede o nosso atraso, não o edge da wallet.
4. Backfill deve ser seletivo e orientado ao bloqueio, evitando aumentar amostra sem aumentar informação.
5. A estratégia Wave permanece congelada enquanto Wallet Intelligence segue como trilha paralela de pesquisa.
