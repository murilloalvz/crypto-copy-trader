# Wallet Strategy Lab v1

## Status

IMPLEMENTADO como camada de pesquisa descritiva. Não altera `wave_v3_volume_integrity`, não cria ordens e não usa a Solana Tracker Data API.

## Objetivo

Comparar várias wallets pelo comportamento observável em RPC/SQLite antes de transformar qualquer padrão em regra de trading.

A pergunta desta etapa não é "qual wallet copiar?". A pergunta é:

> Quais padrões de execução aparecem de forma repetida em wallets diferentes e merecem virar hipóteses causais?

## Entradas

O laboratório aceita endereços explícitos na linha de comando ou um arquivo UTF-8 com uma wallet por linha. Por padrão, usa apenas o SQLite local. `--sync-onchain` é opcional e usa Solana RPC; não consome créditos da Solana Tracker Data API.

Exemplos:

```powershell
python wallet_strategy_lab.py 7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH
```

```powershell
python wallet_strategy_lab.py --file wallets.txt --sync-onchain --pages 3
```

```powershell
python wallet_strategy_lab.py --file wallets.txt --json > wallet-strategy-lab.json
```

## Fingerprint v1

Cada wallet recebe dimensões descritivas:

- holding observado: `ultra_short`, `intraday`, `one_day`, `swing`, `long_hold` ou desconhecido;
- formato de saída: `single_exit_dominant`, `staged_exit_dominant`, `mixed_exit` ou amostra insuficiente;
- reentrada: rara, ocasional ou frequente;
- intensidade/frequência observada: sparse, moderate, active ou high_frequency;
- cobertura de roundtrips;
- scale-in;
- múltiplas vendas;
- sizing complete-like;
- primeira tranche e runner em ciclos multi-sell complete-like;
- DEX dominante e concentração observada.

### Frequência: dias ativos vs média calendário

A média calendário `swap_count / observed_span` continua sendo exibida, mas não define sozinha o bucket de frequência porque um backfill parcial pode conter uma observação histórica distante e expandir artificialmente o span.

A primeira tentativa de robustez usava:

```text
86400 / median_swap_gap_seconds
```

Ela foi descartada após o deep scan de 31/08/2026 porque wallets bursty produziram extrapolações absurdas, como `86400 swaps/dia`, quando vários swaps ocorreram com diferença de aproximadamente um segundo.

O bucket agora usa a **mediana da quantidade realmente observada de swaps por dia UTC ativo**:

```text
frequency_rate_per_day = median(swaps_observados_em_cada_dia_UTC_com_atividade)
```

Isso preserva a distinção entre uma wallet que faz dezenas de swaps num dia ativo e outra que faz poucos, sem assumir que uma rajada de segundos se manteria por 24 horas.

A média calendário permanece separada como diagnóstico. Se ela e a intensidade dos dias ativos divergirem por pelo menos 3x, o fingerprint recebe:

```text
calendar_frequency_differs_from_active_intensity
```

A métrica continua descritiva e sujeita ao recorte do backfill: dias não sincronizados não são reconstruídos e um único dia ativo ainda não prova frequência estrutural.

A assinatura combina quatro dimensões:

```text
holding | exit | reentry | frequency
```

Ela é um agrupamento determinístico de pesquisa, não uma classe econômica definitiva e não um score de qualidade.

## Comparação cross-wallet

`src/wallet_strategy_compare.py` e `wallet_strategy_compare.py` separam duas perguntas diferentes:

1. **as fingerprints se parecem?**
2. **a evidência local de cada wallet é suficiente para levar essa semelhança a sério?**

A similaridade compara apenas dimensões informativas entre holding, exit, reentry e frequency. Amostras vazias ou dimensões desconhecidas não são tratadas como coincidência.

A gate `fingerprint_evidence_ready` é somente de cobertura. Ela exige:

- amostra on-chain diferente de `INSUFFICIENT`;
- pelo menos 50% de roundtrips observados;
- pelo menos três ciclos de sizing complete-like;
- ausência de `sequence_coverage_low`;
- ausência de `short_observation_window`;
- ausência de `exit_sizing_sample_too_small`;
- ausência de `exit_sizing_quantity_anomalies`.

A gate **não** mede PnL, não mede copyability e não diz que a wallet deve ser copiada. Ela apenas evita promover fingerprints ainda muito sensíveis a poucos tokens/ciclos ou a uma janela sub-dia.

Padrões de assinatura recebem graus de recorrência:

- `SINGLE_WALLET`: visto em uma wallet;
- `REPEATED_LOW_COVERAGE`: repetiu, mas menos de duas wallets têm cobertura mínima;
- `MULTI_WALLET_PRELIMINARY`: pelo menos duas wallets com cobertura mínima compartilham a assinatura;
- `MULTI_WALLET_BROADER_SUPPORT`: pelo menos cinco wallets com cobertura mínima compartilham a assinatura.

Esses nomes descrevem **recorrência comportamental**, não performance.

### Comparar wallets já presentes no SQLite

```powershell
python wallet_strategy_compare.py --all-local --min-swaps 20
```

Ou explicitamente:

```powershell
python wallet_strategy_compare.py WALLET_A WALLET_B WALLET_C
```

Também é possível usar `--file` e `--json`.

## Guardrails

1. O laboratório não calcula PnL a partir do RPC puro.
2. Um fingerprint não significa que a wallet é lucrativa ou copiável.
3. A amostra local pode começar depois de uma posição já existir.
4. Transferências, token mechanics e backfill incompleto podem distorcer sizing.
5. `staged_exit_dominant` exige pelo menos três ciclos de sizing complete-like e evidência repetida de múltiplas vendas; ainda assim descreve a amostra, não intenção.
6. Similaridade de fingerprint não é evidência de edge.
7. Intensidade por dia ativo mede somente dias realmente observados; não é uma taxa econômica garantida em calendário completo.
8. Nenhum fingerprint modifica automaticamente o bot.

## Próxima sequência de validação

Para um padrão que apareça em várias wallets:

1. formular uma hipótese objetiva e pré-declarada;
2. ligar o fingerprint ao contexto de entrada/holding/saída já coletado;
3. fazer replay causal sem usar informação posterior à decisão;
4. aplicar taxas, slippage, latência e restrições de liquidez;
5. comparar contra controles simples;
6. promover apenas sobreviventes para shadow concorrente;
7. manter `wave_v3` congelada até existir evidência incremental suficiente.

## Limitação atual de sourcing

O scanner amplo da Solana Tracker Data API está temporariamente limitado pela cota de créditos. Por isso o v1 recebe wallets explicitamente e consegue operar com RPC/SQLite. Descoberta de wallets e análise de estratégia permanecem responsabilidades separadas.
