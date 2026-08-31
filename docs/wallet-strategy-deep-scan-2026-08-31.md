# Wallet Strategy Lab — Deep Scan 2026-08-31

## Status

RESEARCH / READ ONLY. Este checkpoint não altera `wave_v3_volume_integrity`, não cria ordens e não afirma lucratividade de nenhuma wallet.

## Execução

Coorte aprofundada:

- `7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH`
- `Gf9XgdmvNHt8fUTFsWAccNbKeyDXsgJyZN8iFJKg5Pbd`
- `3tc4BVAdzjr1JpeZu6NAjLHyp4kK3iic7TexMBYGJ4Xk`
- `DKgvpfttzmJqZXdavDwTxwSVkajibjzJnN2FA99dyciK`

Comando de backfill:

```powershell
python wallet_strategy_lab.py --file wallets/research-cohort-deep.txt --sync-onchain --pages 10
python wallet_strategy_compare.py --all-local --min-swaps 20
```

Não houve falhas RPC nas páginas observadas.

## Resultados observados

### 7mPti

- 94 swaps, 36 tokens, span local 306,3 dias, grau DEVELOPING;
- primeira saída mediana: 18,5h;
- roundtrip observado: 72,2%;
- scale-in: 7,7%;
- múltiplas vendas: 42,3%;
- reentrada: 19,2%;
- sizing complete-like: 21;
- multi-sell complete-like: 6;
- primeira tranche / runner mediano nos multi-sell complete-like: 50% / 50%;
- PumpSwap: 52,1% dos swaps observados;
- `preexisting_inventory_observed`.

Leitura: o backfill maior manteve a hipótese comportamental principal de posição aproximadamente `one_day`, uso relevante de múltiplas vendas e um modo staged próximo de 50/50 em parte dos ciclos completos. A wallet continua sendo a referência de melhor cobertura local, mas isso ainda não mede edge.

### Gf9X

- 71 swaps, 36 tokens, 21,2 dias, grau DEVELOPING;
- primeira saída mediana: 5,3min;
- roundtrip observado: 36,1%;
- scale-in: 23,1%;
- múltiplas vendas: 15,4%;
- reentrada: 7,7%;
- sizing complete-like: 10;
- multi-sell complete-like: 1;
- PumpSwap: 83,1%.

Leitura: surgiu um candidato de arquétipo `ultra_short` com saída predominantemente única e reentrada rara. É comportamentalmente muito diferente da 7mPti. A cobertura de roundtrips ainda é baixa para promoção de evidência.

### 3tc4

- 93 swaps, 5 tokens, apenas ~0,2 dia observado, grau DEVELOPING;
- primeira saída mediana: 1,2min;
- roundtrip observado: 80%;
- scale-in: 100%;
- múltiplas vendas: 50%;
- reentrada: 50%;
- sizing complete-like: 4;
- multi-sell complete-like: 2;
- primeira tranche / runner mediano: 12,5% / 87,5%;
- PumpSwap: 92,5%;
- alertas: `short_observation_window`, `exit_sizing_sample_too_small`.

Leitura: é um caso forte para estudar comportamento ultra-short/high-frequency, com indícios de múltiplas compras, reentrada e runner grande. Porém a janela é curta demais e há poucos ciclos/tokens para chamar o fingerprint de estável.

### DKgv

- 53 swaps, 3 tokens, ~0,1 dia observado, grau DEVELOPING;
- primeira saída mediana: 21,9min;
- roundtrip observado: 33,3%;
- scale-in: 100%;
- múltiplas vendas: 100%;
- reentrada: 100%;
- sizing complete-like: 1;
- primeira tranche / runner observado: 10% / 90%;
- PumpSwap: 94,3%;
- alertas de janela curta, baixa cobertura de sequência e sizing insuficiente.

Leitura: existe semelhança superficial com o cluster high-frequency/reentry, mas a evidência ainda é fraca. Não deve ser usada como confirmação de arquétipo.

## Correções metodológicas derivadas do scan

### 1. Gate de evidência

A comparação inicial marcou 7mPti e 3tc4 como `evidence_ready`. A 3tc4 não deveria passar porque a amostra tinha apenas ~0,2 dia e poucos ciclos/tokens.

A gate passou a exigir, além de amostra não insuficiente, >=50% de roundtrips e >=3 ciclos complete-like:

- pelo menos 10 tokens observados;
- ausência de `short_observation_window`;
- ausência de `strategy_token_sample_too_small`;
- ausência de `exit_sizing_sample_too_small`;
- ausência de `exit_sizing_quantity_anomalies`;
- ausência de `sequence_coverage_low`.

Na reavaliação do mesmo SQLite, somente a 7mPti permaneceu `evidence_ready`. O corte de 10 tokens é uma gate de generalização cross-token, não um filtro de lucro.

### 2. Frequência: span calendário era frágil

A classificação baseada em `swap_count / observed_span` transformou a 7mPti em `sparse` quando um registro histórico distante expandiu o span para 306,3 dias. A métrica passou então a usar mediana de gaps entre swaps.

### 3. Frequência: extrapolação por gap também era frágil

A reavaliação com mediana de gap revelou o problema oposto:

- 3tc4: `86400 swaps/dia` implícitos;
- DKgv: `24685,7 swaps/dia` implícitos.

Esses números não representam volume diário observado. Eles aparecem porque rajadas com swaps separados por segundos foram extrapoladas para 24 horas.

A metodologia foi corrigida novamente: o bucket de frequência agora usa a **mediana do número de swaps realmente observados por dia UTC ativo**. A média calendário continua separada como diagnóstico.

Isso mantém wallets realmente muito ativas como high-frequency quando dezenas de swaps foram observados no mesmo dia, mas não converte uma distância de 1 segundo entre duas ações em uma taxa fictícia de 86.400 swaps/dia.

## Estado das hipóteses após a revisão

1. **7mPti / one-day mixed-exit** — hipótese comportamental mais madura; 72,2% de roundtrips e 21 ciclos complete-like. Ainda sem edge provado.
2. **Gf9X / ultra-short single-exit** — candidato distinto, porém só 36,1% de roundtrips; precisa de melhor cobertura antes de comparação forte.
3. **3tc4 / ultra-short staged/reentry bursty** — interessante, mas 5 tokens e janela sub-dia impedem promoção; high-frequency deve ser interpretado como atividade observada, não cadência contínua.
4. **DKgv / intraday high-frequency reentry candidate** — ainda mais fraco: 3 tokens, baixa cobertura e sizing insuficiente.

Nenhuma hipótese representa estratégia validada ou recomendação de cópia.

## Validação técnica

Após as correções de frequência e da gate cross-token, GitHub Actions em Ubuntu / Python 3.11 executou compilação e suíte completa:

```text
Ran 244 tests in 2.315s
OK
```

Status da metodologia atual: **TESTADO EM CI LIMPO**.

## Próximo passo recomendado

Recalcular novamente os fingerprints no SQLite existente sem novo RPC com a metodologia final deste checkpoint. Em seguida escolher seletivamente backfill/forward watch. Não ampliar a coorte indiscriminadamente até a frequência e a cobertura estarem estáveis.
