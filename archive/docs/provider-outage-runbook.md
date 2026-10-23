# Provider outage / credits runbook

## Quando usar

Use este procedimento quando o monitor híbrido não consegue executar discovery por erro de configuração do provedor, por exemplo `HTTP 403: Insufficient credits` da Solana Tracker Data API.

## O que não fazer

Não reinicie `start-monitor.ps1` repetidamente esperando que o mesmo erro de créditos desapareça. O monitor híbrido trata código 2 do discovery como erro de configuração e encerra para evitar uma execução aparentemente saudável que não consegue criar novos sinais.

## Fallback oficial: price-only

Para preservar observações e saídas de sinais já matriculados sem chamar discovery:

```powershell
python monitor_existing.py --hours 5 --price-interval-minutes 1
```

Esse modo:

- permanece PAPER / READ ONLY;
- não executa discovery;
- não usa a Solana Tracker Data API;
- não cria sinais novos;
- atualiza preços dos sinais/posições já existentes;
- mantém `exit_engine_v1` observável enquanto houver posições relevantes.

A utilidade cai depois que não restarem posições abertas. Uma janela longa price-only não substitui coleta forward com novos sinais.

## Concorrência de providers

Durante coleta de exit engine, evite executar em paralelo os scripts de entry/holding/exit context que também fazem pesquisa de preço. Competição pelo mesmo provedor pode aumentar rate limit, falhas e gaps e contaminar a interpretação da estabilidade operacional.

## Retorno ao monitor completo

Depois que a Solana Tracker Data API estiver novamente disponível, volte ao launcher padrão somente após confirmar que o discovery isolado funciona. A coorte e os filtros de `wave_v3_volume_integrity` não devem ser alterados apenas para compensar indisponibilidade de provider.
