# Runtime v3 long validation — 2026-08-30

Status: **VALIDADO OPERACIONALMENTE PARA SCHEDULER / PROVIDER, COM LIMITAÇÃO DE DISCOVERY POR ENCODING**

Execução PAPER/READ ONLY de ~6h mantendo `wave_v3_volume_integrity`, T0 original do `exit_engine_v1`, polling de 1 minuto, discovery de 15 minutos e as cinco políticas de saída congeladas.

## Integridade

- janela: 12:18:20–18:18:24 BRT
- SQLite `integrity_check = ok`
- SQLite `quick_check = ok`
- 0 violações de foreign key
- monitor terminou com exit code 0

## Scheduler

- 360 ciclos de preço
- 359 intervalos consecutivos
- mediana 60s
- p95 60s
- mínimo 34s / máximo 86s
- apenas 1 intervalo >65s e nenhum >90s; o intervalo seguinte compensou para 34s
- duração de ciclo: mediana 0,6s; p95 50,6s; máximo 52,2s
- pico observado de 6 sinais dinâmicos simultâneos

Conclusão: o scheduler de 1 minuto permaneceu estável por 6h, inclusive quando o provider consumiu quase todo o budget de ciclo.

## GeckoTerminal / adaptive budget

Tentativas HTTP reais durante a janela: 507.

- 482 HTTP 200
- 15 HTTP 429 (2,96% das tentativas)
- 10 falhas de rede/sem status HTTP persistidas na telemetria
- 285 sucessos em `rate_limited`
- 197 sucessos em `normal`
- apenas 2 HTTP 429 ocorreram já em `rate_limited`

Observações dinâmicas/fixas persistidas durante a janela: 555.

- 430 `completed` (77,5% bruto)
- 64 `provider_cycle_budget_exhausted`
- 56 `distant_historical_candle`
- 5 `temporary_provider_error`

Excluindo apenas `distant_historical_candle`, a cobertura observada foi 430/499 = 86,2%. O principal custo operacional restante é o budget deferral sob carga, não uma volta da cauda de polling de ~120s.

Nenhuma posição nova ficou `failed` por `temporary_provider_error` ou por `provider_cycle_budget_exhausted`. As falhas definitivas novas foram associadas a `distant_historical_candle`.

## Discovery e encoding

O monitor planejou 24 rodadas de discovery:

- 18 concluíram normalmente
- 6 lançaram `UnicodeEncodeError` ao imprimir o relatório em Windows PowerShell 5.1/cp1252
- a proteção de exceção funcionou: o monitor continuou vivo e as atualizações de preço seguiram normalmente

Nas 18 rodadas persistidas:

- 900 tokens solicitados no total
- 675 retornados/analisados
- 488 com dados válidos
- 26 candidatos v3
- 8 sinais novos
- 18 candidatos barrados por cooldown/duplicação de sinal
- 0 rejeições de persistência

Sinais novos da execução: IDs 117–124. Todos foram matriculados com cinco políticas.

A falha de encoding ocorreu antes da persistência nas seis rodadas afetadas, portanto a execução é válida para estabilidade do scheduler/provider, mas não representa 100% da cobertura de discovery planejada.

## Pareamento forward

Após a execução:

- 38 sinais forward estruturais desde o T0 (IDs >86)
- 24 sinais fully closed e pareados 5/5
- 11 sinais fully closed e pareados 5/5 pertencentes integralmente ao runtime v3
- na execução longa, 6 dos 8 sinais novos fecharam 5/5; TROLL e AMA tiveram falhas permanentes por `distant_historical_candle`

Portanto, o marco de 30 sinais forward estruturais foi ultrapassado, mas ainda não há 30 comparações econômicas fully closed 5/5. A regra metodológica pré-fixada permanece: não selecionar política vencedora ainda.

## Leitura econômica descritiva do runtime v3 pareado

Apenas 11 sinais fully closed 5/5 do runtime v3; amostra insuficiente para seleção.

- `fixed_15m_v1`: média -0,96%, mediana -1,69%, WR 36,4%, PF 0,71
- `fixed_60m_v1`: média -3,97%, mediana -1,38%, WR 18,2%, PF 0,61
- `stop_loss_10_v1`: média -11,84%, mediana -3,00%, WR 9,1%, PF 0,13
- `take_profit_20_v1`: média +3,78%, mediana -1,31%, WR 36,4%, PF 2,63
- `trailing_stop_10_v1`: média -12,20%, mediana -4,09%, WR 9,1%, PF 0,13

O aparente destaque do TP20 não é decision-grade: n=11, mediana negativa e forte sensibilidade a poucos vencedores. Nenhuma política deve ser declarada vencedora.

## Wave v3 geral após a execução

O relatório final registrou 57 sinais v3 históricos+forward:

- 5m: 56/57 de cobertura, média -0,46%, mediana -1,62%, WR 32,1%, PF 0,84
- 15m: 52/57 de cobertura, média +2,15%, mediana -1,06%, WR 46,2%, PF 1,50; a média cai para -0,13% sem o melhor sinal
- 60m: 45/57 de cobertura, média +5,40%, mediana -0,27%, WR 46,7%, PF 1,54; cobertura de 78,9% mantém alerta de survivorship

Esses números continuam exploratórios e não justificam live trading.

## Correção decorrente

Após a auditoria, `start-monitor.ps1` foi alterado para:

- forçar `PYTHONUTF8=1`
- forçar `PYTHONIOENCODING=utf-8`
- usar `PYTHONUNBUFFERED=1`
- alinhar `Console.OutputEncoding` e `$OutputEncoding` para UTF-8
- chamar `python -u monitor.py`

Objetivo: eliminar `cp1252/charmap` no discovery e restaurar saída ao vivo sem buffering.

## Próximo passo

Validar rapidamente a correção UTF-8 no Windows antes de iniciar outra coleta longa. Depois continuar a mesma coorte forward até pelo menos 30 sinais fully closed e pareados 5/5, sem alterar estratégia ou políticas.