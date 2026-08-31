# Wallet Strategy Lab — Deep Scan 2026-08-31

## Status

RESEARCH / READ ONLY. Este checkpoint não altera `wave_v3_volume_integrity`, não cria ordens e não afirma lucratividade de nenhuma wallet.

## Execução

Coorte aprofundada:

- `7mPtiLMhn9SsconVw8LZtrF7vL7LvLEwJv75yMLcsxTH`
- `Gf9XgdmvNHt8fUTFsWAccNbKeyDXsgJyZN8iFJKg5Pbd`
- `3tc4BVAdzjr1JpeZu6NAjLHyp4kK3iic7TexMBYGJ4Xk`
- `DKgvpfttzmJqZXdavDwTxwSVkajibjzJnN2FA99dyciK`

Comando executado antes do ajuste de robustez de frequência:

```powershell
python wallet_strategy_lab.py --file wallets/research-cohort-deep.txt --sync-onchain --pages 10
python wallet_strategy_compare.py --all-local --min-swaps 20
```

Não houve falhas RPC nas páginas observadas.

## Resultados observados

### 7mPti

- 94 swaps, 36 tokens, span local 306,3 dias, grau DEVELOPING.
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

A classificação antiga de frequência caiu para `sparse` porque `94 / 306,3 dias` é muito sensível a observações históricas distantes e backfill parcial. Esse problema motivou o ajuste descrito abaixo.

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

## Comparação cross-wallet antes do ajuste

A comparação antiga retornou cinco wallets locais com >=20 swaps e marcou duas como `evidence_ready`: 7mPti e 3tc4.

Isso revelou dois problemas metodológicos:

1. `3tc4` passava na gate apesar de `short_observation_window` e `exit_sizing_sample_too_small`;
2. a dimensão de frequência usava `swap_count / observed_span`, ficando instável quando um único registro histórico distante expandia o span local.

## Correção metodológica implementada

Após este scan:

- a gate `fingerprint_evidence_ready` passou a bloquear:
  - `short_observation_window`;
  - `exit_sizing_sample_too_small`;
  - `exit_sizing_quantity_anomalies`;
  - `sequence_coverage_low`;
- a média calendário `swap_count / observed_span` continua registrada separadamente;
- o **bucket de intensidade/frequência** agora usa a mediana do gap entre swaps quando disponível, reduzindo sensibilidade a um registro histórico distante ou backfill parcial;
- quando a intensidade mediana e a média calendário divergem por >=3x, o fingerprint recebe `calendar_frequency_differs_from_active_intensity`.

Essas mudanças são de metodologia descritiva; não ajustam resultado financeiro e não selecionam uma wallet vencedora.

## Validação técnica

Head de código após as correções: `144769a497bf4cd2d8816a7b19b04f65216fa518`.

GitHub Actions em Ubuntu / Python 3.11:

```text
Ran 242 tests in 3.331s
OK
```

`compileall` também passou.

Status: **TESTADO EM CI LIMPO**.

## Hipóteses que permanecem abertas

1. **7mPti / one-day path-sensitive** — entrada relativamente rara, holding mais longo, múltiplas vendas frequentes e subset de ciclos próximos de 50/50.
2. **Gf9X / ultra-short single-exit** — saída rápida, menor reentrada e menor dependência de staged exit; cobertura insuficiente ainda.
3. **3tc4 / ultra-short high-frequency staged/reentry** — intensidade muito alta, scale-in/reentrada e runner grande, mas a janela atual é curta e não permite generalização.
4. **DKgv / high-frequency reentry candidate** — possível vizinho do terceiro arquétipo, mas ainda sem cobertura mínima.

Nenhuma dessas hipóteses representa edge validado.

## Próximo passo recomendado

Primeiro recalcular os fingerprints no SQLite existente com a metodologia corrigida, sem novo RPC. Depois escolher seletivamente quais wallets merecem mais backfill/forward watch. Não ampliar a coorte indiscriminadamente antes dessa revisão.
