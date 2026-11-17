# Wallet Strategy Lab — Deep Scan 2026-08-31

## Status

RESEARCH / READ ONLY. Este checkpoint não altera `wave_v3_volume_integrity`, não cria ordens e não afirma lucratividade de nenhuma wallet.

## Execução

Coorte aprofundada:

- `7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH`
- `Gf9XgdmvNHt8fUTFsWAccNbKeyDXsgJyZN8iFJKg5Pbd`
- `3tc4BVAdzjr1JpeZu6NAjLHyp4kK3iic7TexMBYGJ4Xk`
- `DKgvpfttzmJqZXdavDwTxwSVkajibjzJnN2FA99dyciK`

Backfill executado sem falhas RPC nas páginas observadas:

```powershell
python wallet_strategy_lab.py --file wallets/research-cohort-deep.txt --sync-onchain --pages 10
```

Depois das correções metodológicas, o mesmo SQLite foi recalculado sem novo RPC.

## Resultado final do fingerprint neste checkpoint

### 7mPti

- 94 swaps / 36 tokens / span local 306,3 dias / DEVELOPING;
- `one_day|mixed_exit|occasional_reentry|moderate`;
- intensidade mediana nos dias UTC ativos: 1,0 swap/dia;
- média calendário observada: 0,3 swap/dia;
- primeira saída mediana: 18,5h;
- roundtrip: 72,2%;
- scale-in: 7,7%; multi-sell: 42,3%; reentrada: 19,2%;
- 21 ciclos complete-like e seis multi-sell complete-like;
- primeira tranche / runner mediano nos multi-sell completos: 50% / 50%;
- PumpSwap: 52,1%;
- única wallet deste conjunto classificada como `evidence_ready`.

Leitura: referência comportamental mais madura, consistente com posição de horizonte maior e saída mista. Continua sem edge provado.

### Gf9X

- 71 swaps / 36 tokens / 21,2 dias / DEVELOPING;
- `ultra_short|single_exit_dominant|rare_reentry|moderate`;
- intensidade mediana nos dias ativos: 2,0 swaps/dia;
- média calendário: 3,3 swaps/dia;
- primeira saída mediana: 5,3min;
- roundtrip: 36,1%;
- scale-in: 23,1%; multi-sell: 15,4%; reentrada: 7,7%;
- 10 ciclos complete-like;
- PumpSwap: 83,1%;
- bloqueio principal: baixa cobertura de sequência/roundtrips.

Leitura: melhor candidato atual de arquétipo distinto da 7mPti, mas precisa de cobertura causal melhor.

### 3tc4

- 93 swaps / somente 5 tokens / ~0,2 dia / DEVELOPING;
- `ultra_short|staged_exit_dominant|frequent_reentry|high_frequency`;
- intensidade mediana observada nos dias ativos: 46,5 swaps/dia;
- média calendário do recorte: 428,2 swaps/dia;
- primeira saída mediana: 1,2min;
- roundtrip: 80%;
- scale-in: 100%; multi-sell: 50%; reentrada: 50%;
- quatro ciclos complete-like, dois multi-sell;
- primeira tranche / runner mediano: 12,5% / 87,5%;
- PumpSwap: 92,5%;
- bloqueios: janela curta, apenas 5 tokens e sizing ainda pequeno.

Leitura: candidato de comportamento ultra-rápido/bursty, mas ainda pode ser apenas um episódio concentrado. Não é evidência pronta.

### DKgv

- 53 swaps / 3 tokens / ~0,1 dia / DEVELOPING;
- `intraday|exit_sizing_insufficient|frequent_reentry|high_frequency`;
- intensidade mediana observada nos dias ativos: 53 swaps/dia;
- média calendário do recorte: 623,1 swaps/dia;
- primeira saída mediana: 21,9min;
- roundtrip: 33,3%;
- scale-in/multi-sell/reentrada observados: 100% / 100% / 100%;
- apenas um ciclo complete-like;
- PumpSwap: 94,3%;
- baixa diversidade, baixa cobertura e sizing insuficiente.

Leitura: semelhança superficial com o cluster high-frequency/reentry, porém evidência muito fraca. Não foi priorizada para o primeiro forward watch.

## Correções metodológicas derivadas do scan

### Gate de evidência

A gate cross-wallet passou a exigir:

- amostra diferente de `INSUFFICIENT`;
- >=50% de roundtrips;
- >=3 ciclos complete-like;
- >=10 tokens;
- ausência de `short_observation_window`;
- ausência de `strategy_token_sample_too_small`;
- ausência de `exit_sizing_sample_too_small`;
- ausência de `exit_sizing_quantity_anomalies`;
- ausência de `sequence_coverage_low`.

Somente a 7mPti passa hoje. A gate mede cobertura/generalização descritiva, não lucro.

### Frequência

Duas metodologias foram rejeitadas durante o scan:

1. `swap_count / observed_span`, sensível demais a um registro histórico distante;
2. `86400 / median_swap_gap`, que transformava bursts separados por segundos em taxas fictícias de dezenas de milhares de swaps/dia.

A métrica final usa:

```text
mediana da quantidade de swaps realmente observados em cada dia UTC ativo
```

A média calendário permanece separada como diagnóstico. Isso evita extrapolar bursts de segundos para 24 horas.

## Estado das hipóteses

1. **7mPti / one-day mixed-exit** — mais madura, ainda sem edge provado.
2. **Gf9X / ultra-short single-exit** — distinta e diversificada em tokens, porém baixa cobertura de roundtrips.
3. **3tc4 / ultra-short staged/reentry bursty** — forte contraste comportamental, mas amostra concentrada em 5 tokens e janela sub-dia.
4. **DKgv / high-frequency reentry candidate** — evidência insuficiente para prioridade atual.

Nenhuma assinatura apareceu ainda em duas wallets `evidence_ready`; portanto não existe arquétipo multi-wallet confirmado neste checkpoint.

As hipóteses e seus critérios de enfraquecimento foram congelados antes de dados forward adicionais em `docs/wallet-strategy-hypotheses-2026-08-31.md`.

## Validação técnica

A metodologia de fingerprint/gate anterior a Wallet Strategy Readiness foi validada em GitHub Actions com:

```text
Ran 244 tests in 2.315s
OK
```

O módulo posterior `wallet_strategy_readiness.py` adiciona diagnóstico explícito de bloqueios e próximos passos; seu status deve acompanhar o CI do head correspondente.

## Próximo passo

Aprofundamento histórico deixa de ser o passo padrão. O próximo experimento prioritário é o Forward Wallet Watch de 7mPti, Gf9X e 3tc4 com polling de 30s, em conexão estável, para medir `chain_time -> observed_at` e descobrir se os arquétipos rápidos são sequer observáveis a tempo.

Durante períodos sem conectividade externa, `wallet_strategy_readiness.py` pode ser executado só sobre o SQLite para auditar os gargalos de cada wallet sem consumir RPC.
