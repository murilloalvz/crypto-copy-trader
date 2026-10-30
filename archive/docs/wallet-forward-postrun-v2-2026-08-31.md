# Wallet Forward Post-Run v2 — 2026-08-31

Status: **IMPLEMENTADO / TESTADO** em `feat/exit-engine-v1`.

Este checkpoint congela a metodologia de auditoria criada enquanto a primeira coleta Wallet + Jupiter de 6h estava em execução no PC do usuário.

A coleta em andamento **não deve ser reiniciada**. Ela pertence ao runtime anterior e, após atualização do código, será identificada como `wallet_forward_runtime_v1_unversioned`.

## Princípio

O pós-run não começa perguntando se uma wallet foi lucrativa.

A ordem é:

```text
run scope
-> causal integrity
-> observation exposure / right-censoring
-> quote completeness
-> source latency
-> event-scoped route quotes
-> causal replay readiness
-> per-wallet technical profile
-> convergence / quote drift
-> somente então interpretação econômica
```

## 1. Run scope

Toda interpretação principal é limitada ao manifest:

- `(baseline_observation_id, end_observation_id]`;
- coorte exata;
- runtime version;
- polling interval;
- quote delays;
- quote mode;
- copy notional;
- quote intake grace.

Runs diferentes não são pooled automaticamente.

`wallet_forward_run_compare.py` compara os manifests e retorna:

- `NO_RUNS`;
- `SINGLE_RUN`;
- `SAME_TECHNICAL_REGIME_COMPARE_SEPARATELY`;
- `MIXED_TECHNICAL_REGIME_DO_NOT_POOL`.

Mesmo `SAME_TECHNICAL_REGIME` não autoriza pooling automático.

## 2. Causal integrity

`wallet_forward_integrity.py` audita:

- observação pré-start;
- chain time pré-start;
- lag negativo;
- source lag >5m;
- source lag >1h;
- p50/p95/max source lag.

Runtime v1 pode ter risco de late-hydrated backfill. Runtime v2 bloqueia prospectivamente transações anteriores à causal boundary.

## 3. Observation exposure / right-censoring

`wallet_forward_exposure.py` mede quanto tempo de observação restava depois de cada BUY causal.

Padrão:

- 15m;
- 1h;
- 6h;
- 24h.

**Right-censoring** = a coleta acaba antes de termos tempo suficiente para observar o comportamento posterior.

Consequências:

- BUY sem SELL perto do fim da run não prova hold longo;
- uma run de ~6h não testa honestamente a hipótese `7mPti first exit >6h` para a maioria dos BUYs, porque quase nenhum BUY terá >=6h completos de follow-up;
- H2/H3 com fronteira de first exit <15m precisam ao menos 15m completos de follow-up;
- multi-sell/reentry ainda exigem uma política de follow-up/censoring própria antes de pass/fail formal.

Nenhuma hipótese congelada deve ser retunada para caber na duração da coleta.

## 4. Quote completeness

`wallet_quote_completeness.py` reconstrói:

```text
BUY causal × delays congelados = attempts esperados
```

A auditoria separa:

- expected;
- attempted expected;
- successful expected;
- failed expected;
- missing;
- unexpected.

Attempts extras nunca melhoram nem pioram a run. Probes nunca iniciados continuam no denominador.

## 5. Causal replay readiness

`wallet_forward_readiness.py` é gate de **dados**, não de performance.

Labels:

- `NO_CAUSAL_SAMPLE`;
- `DATA_QUALITY_BLOCKED`;
- `QUOTE_PATH_BLOCKED`;
- `PARTIAL_CAUSAL_REPLAY_SAMPLE`;
- `CAUSAL_REPLAY_SAMPLE_READY`.

`economic_promotion_allowed=False` sempre nesta camada.

READY significa apenas que existe caminho estrutural suficiente para replay descritivo.

## 6. Per-wallet technical profiles

`wallet_forward_wallet_profiles.py` compara cada wallet da coorte separadamente:

- ações/tokens;
- BUY/SELL;
- source lag p50/p95/max;
- causal integrity;
- BUYs com quote;
- quote completeness;
- success/failure/missing expected;
- quote drift pareado.

Não existe score ponderado novo.

Objetivo: distinguir **copyability técnica / observabilidade** de lucratividade histórica.

## 7. Quote drift

O baseline é a quote +0 do mesmo BUY.

Cada delay posterior é pareado somente com esse evento.

`adverse_execution_drift > 0` em BUY significa entrada mais cara para o copiador atrasado.

Isto mede custo temporal de rota/preço, não PnL futuro.

## 8. Multi-wallet convergence

Convergência é feature descritiva:

- mesmo token;
- janela exploratória 300s;
- >=2 BUY wallets únicas;
- causal `observed_at`;
- trigger ligado à quote do evento que cruzou o threshold.

Convergência não prova smart-money edge. O teste econômico posterior continua exigindo placebo pré-período.

## 9. Proteção contra runs sobrepostas

Novas versões de `wallet_forward_experiment.py` recusam iniciar se já existir manifest `ACTIVE` no mesmo banco.

Motivo: dois collectors escrevendo ações no mesmo SQLite poderiam tornar impossível atribuir causalmente uma observação a uma run específica.

Uma run ACTIVE órfã após crash deve ser reconciliada explicitamente; nunca ignorada silenciosamente.

## 10. Auditor único

Depois de uma run concluída:

```powershell
python wallet_forward_postrun.py
```

O auditor executa:

1. Forward Integrity;
2. Forward Observation Exposure;
3. Quote Completeness;
4. Unified Forward Checkpoint;
5. Run-scoped Wallet Latency;
6. Run-scoped Quote Attempts;
7. Causal Replay Readiness;
8. Per-wallet Technical Profiles.

Todos os steps são locais/read-only em relação ao mercado.

Zero ação/zero BUY é um resultado válido `NO_CAUSAL_SAMPLE`, não erro de pipeline.

## O que ainda NÃO temos

Mesmo com um pós-run perfeito, ainda não temos automaticamente:

- PnL causal completo de uma estratégia de wallet;
- prova de que a wallet mantém edge depois do nosso atraso;
- prova de fill real;
- shadow aprovado;
- live aprovado.

O próximo avanço econômico depende dos BUYs realmente observados e das quotes capturadas nessa amostra.
