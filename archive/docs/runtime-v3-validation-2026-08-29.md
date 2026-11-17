# Runtime v3 provider validation — 2026-08-29

Status: **VALIDADO OPERACIONALMENTE EM JANELA CURTA / PAPER-READ ONLY**

Esta validação manteve `wave_v3_volume_integrity`, o T0 original do `exit_engine_v1` e as cinco políticas de saída congeladas. Nenhum filtro de entrada ou parâmetro econômico foi ajustado.

## Execução

- Janela observada: 21:18:37–22:48:43 BRT (~90 min)
- Banco auditado: `copytrader(9).db`
- Runtime: `exit_runtime_v3_adaptive_provider_budget`
- `integrity_check = ok`
- `quick_check = ok`
- 0 violações de foreign key

## Scheduler e polling

- 91 ciclos dinâmicos registrados
- intervalo mediano: 60s
- p95: 61s
- mínimo/máximo: 59s/61s
- nenhum intervalo >65s
- pico observado: 6 sinais simultâneos

Conclusão: o polling de 1 minuto voltou a ficar estável na janela curta, inclusive sob pico de 6 sinais.

## GeckoTerminal e rate limit

- 268 tentativas HTTP reais
- 264 HTTP 200
- 4 HTTP 429
- taxa de 429 por tentativa: 1,49%
- runtime v2 comparável: 161/466 = 34,55%
- redução relativa da taxa de 429: ~95,7%
- as 4 ocorrências de 429 surgiram em modo normal e recuperaram na segunda tentativa
- 72 requests foram executados em `rate_limited`; 72/72 retornaram HTTP 200

Conclusão: o controle adaptativo reduziu drasticamente o rate limit sem reintroduzir a cauda de ~120s observada no runtime v2.

## Cobertura dinâmica

- 266 observações dinâmicas
- 249 concluídas
- 13 `distant_historical_candle`
- 4 `provider_cycle_budget_exhausted`
- cobertura dinâmica bruta: 93,6%
- cobertura entre observações serviceáveis, excluindo candle permanentemente distante: 249/253 = 98,4%
- 0 `temporary_provider_error` final
- 0 posições perdidas por erro temporário

Os 4 budget deferrals ocorreram apenas em 3 ciclos com 6 sinais simultâneos e foram distribuídos entre sinais diferentes. O scheduler permaneceu em 59–61s, indicando que o orçamento cumpriu a função de preservar o relógio em vez de bloquear o ciclo.

## Funnel e pareamento

- 6 discovery rounds
- 219 tokens analisados
- 161 válidos
- 10 candidatos v3
- 6 sinais novos
- 4 cooldown/duplicados
- 0 rejeições de persistência
- sinais 110–115 receberam exatamente cinco políticas cada
- 18 posições v3 fecharam e 12 ficaram abertas ao fim da janela
- 0 posições v3 em estado `failed`

## Decisão

- runtime v3: **APROVADO para retomar coleta forward mais longa**
- manter PAPER/READ ONLY
- manter mesmo T0, estratégia e políticas
- não misturar runtimes v1/v2/v3 sem os marcadores persistidos
- continuar monitorando 429, budget deferrals, cobertura por simultaneidade e `distant_historical_candle`
- capacidade acima de 6 sinais simultâneos ainda não foi validada
- resultados econômicos ainda não são decision-grade e não justificam seleção de política

## Regra metodológica para o marco n=30

O banco já está próximo de 30 sinais forward estruturais, mas parte da coorte anterior foi contaminada por falhas operacionais dos runtimes v1/v2. Portanto, atingir 30 sinais registrados não deve ser confundido com ter 30 comparações econômicas pareadas utilizáveis.

No marco de 30 sinais forward, produzir apenas uma leitura descritiva da coorte completa e das falhas. Não escolher política vencedora até existir pelo menos uma amostra suficiente de sinais **fully closed e pareados 5/5**, analisada separadamente por regime operacional quando necessário. O histórico não deve ser apagado nem reconstruído para aumentar artificialmente a cobertura.
