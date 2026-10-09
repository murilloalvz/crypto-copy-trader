# Wallet Placebo Matching v1

## Status

**IMPLEMENTADO / RESEARCH ONLY / SEM COORTE PROSPECTIVA CONGELADA.**

Arquivos:

- `src/wallet_placebo_matching.py`;
- `wallet_placebo_match.py`;
- `tests/test_wallet_placebo_matching.py`.

Esta camada existe para ajudar a construir controles placebo defensáveis para Wallet Confirmation. Ela **não escolhe wallets para copiar**, não usa PnL futuro, não mede edge e não altera a Wave.

## Problema metodológico

Comparar uma wallet target ativa com wallets aleatórias/inativas cria um placebo fraco. A diferença observada pode vir apenas de:

- frequência de operações;
- quantidade de tokens;
- horizonte de holding;
- DEX usado;
- janela de observação;
- cobertura de roundtrip/saídas.

Antes de avaliar outcomes, precisamos tornar essas diferenças visíveis.

## Dados usados

O matching usa somente `WalletStrategyFingerprint`, que é formado por comportamento observado no período anterior ao estudo:

- active-day swap rate;
- token breadth;
- observed span;
- holding bucket e first-exit mediano;
- exit bucket;
- reentry bucket;
- frequency bucket;
- roundtrip share;
- scale-in;
- multi-sell;
- reentry;
- DEX dominante e participação;
- evidence readiness/flags.

Não existem PnL, ROI, win rate ou outcome do período futuro no objeto de matching.

## Sem score ponderado

O v1 **não cria um Match Score**.

Um único número esconderia decisões arbitrárias de peso, por exemplo se holding deve valer duas vezes mais que DEX ou frequência. Em vez disso o sistema retorna diagnósticos separadamente:

- bucket similarity e dimensões comparáveis;
- razão entre intensidades de dia ativo;
- razão de token breadth;
- razão de janela observada;
- razão de first-exit;
- diferenças absolutas de roundtrip/scale-in/multi-sell/reentry;
- match de DEX dominante;
- diferença de share da DEX;
- warnings de cobertura.

A ordenação é **lexicográfica e auditável**, não uma soma ponderada:

1. evidence readiness da candidata;
2. número de dimensões comportamentais comparáveis;
3. bucket similarity;
4. proximidade de active-day rate;
5. token breadth;
6. first-exit;
7. roundtrip;
8. DEX;
9. observed span.

Isso serve para triagem humana/reprodutível antes do congelamento do estudo.

## Evidence gaps ficam visíveis

Por padrão uma candidata com cobertura ruim ainda pode aparecer no relatório, marcada com warnings como:

- `candidate_evidence_not_ready`;
- `few_comparable_dimensions`;
- `activity_rate_uncomparable`;
- `holding_time_uncomparable`;
- `candidate_token_sample_narrow`;
- `candidate_short_observation_window`;
- `candidate_sequence_coverage_low`.

Use `--require-ready` somente quando existir universo suficiente; não esconda a falta de candidatas fingindo que o matching foi forte.

## CLI

Exemplo sobre todas as wallets locais com pelo menos 20 swaps:

```powershell
python wallet_placebo_match.py <TARGET_ADDRESS> --all-local --min-swaps 20
```

Somente candidatas evidence-ready:

```powershell
python wallet_placebo_match.py <TARGET_ADDRESS> --all-local --min-swaps 20 --require-ready
```

JSON auditável:

```powershell
python wallet_placebo_match.py <TARGET_ADDRESS> --all-local --json
```

## O que significa 1.0x

As razões contínuas são simétricas:

- `1.00x` = valores iguais;
- `2.00x` = um valor é duas vezes o outro, independentemente do lado;
- `n/a` = comparação não defensável com os dados existentes.

Nenhum `n/a` é imputado silenciosamente.

## Congelamento de placebo

O código contém uma função determinística para selecionar endereços de um ranking já revisado, mas o CLI **não congela automaticamente** a coorte. Isso é proposital.

Antes de congelar uma coorte prospectiva:

1. definir a target usando apenas dados pré-período;
2. rodar o ranking diagnóstico;
3. revisar warnings e cobertura;
4. assegurar que nenhuma candidata foi escolhida olhando outcome futuro;
5. escolher múltiplos grupos placebo quando houver universo suficiente;
6. registrar addresses, fingerprints, timestamp/cutoff e regra de matching;
7. só depois iniciar o período de outcome.

## Estado do universo atual

O banco local usado na pesquisa recente possui poucas wallets profundas e apenas 7mPti estava evidence-ready no checkpoint. Portanto, esta infraestrutura **não autoriza congelar agora uma coorte placebo séria**.

Gf9X e 3tc4 continuam cientificamente úteis como arquétipos/observabilidade, mas possuem evidence gaps diferentes. Misturá-las automaticamente em uma única cesta target ou placebo criaria um desenho confuso.

## Relação com Wallet Confirmation

Fluxo futuro:

```text
pre-period wallet data
-> fingerprints
-> placebo matching diagnostics
-> target/placebos congelados
-> período prospectivo
-> causal confirmation events
-> mesmo universo/relógio
-> outcomes + missingness
-> target vs mediana dos placebos
-> latency/Jupiter stress
-> shadow, se sobreviver
```

Mesmo uma target que supere placebos ainda não prova copyability. O efeito precisa sobreviver à nossa latência, rota, liquidez e custos.
