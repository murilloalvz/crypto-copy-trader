# V68-09 — árvore de decisão pré-registrada (Fase A / A1) — 2026-10-04

Modo: PAPER / RESEARCH / READ ONLY. Nenhuma chamada a provider, nenhum run, nenhum threshold alterado.

## Por que este documento existe

O operador (Murillo) está rodando a tentativa `v68-09` (chaves `v68-09-A` / `v68-09-B`) na máquina dele, com o backoff de 429 = 1.5s (`f865745`). Este documento fixa, **antes de o resultado do v68-09 existir**, o que cada classificação possível significa e qual é a próxima ação permitida. O objetivo é impedir que a interpretação seja escolhida depois de ver o número.

- Escrito e commitado em 2026-10-04 ~22:05 UTC, a partir de `57275d1` (tip de `origin/research/rust-signal-plane-live-shadow-v0`), num branch separado (`research/v68-09-fase-a-prereg`) para não tocar no working tree onde o v68-09 roda.
- Quem escreveu não viu nenhum dado do v68-09 (nem de sistema, nem econômico). O horário do push no GitHub é a evidência de anterioridade.
- Fonte do conteúdo: Fase C da ordem de trabalho do operador, reproduzida em `docs/HANDOFF_COPILOT_2026-10-04.md` (commit `57275d1`).

## Contrato congelado que esta árvore NÃO altera

`docs/route-research-v68-prospective-flow60-buy-share-holdout-protocol-2026-09-08.md` continua sendo a autoridade: feature `flow60_buy_share_pct`, LOW ≤ `57.1429`, HIGH > `65.7143`, horizonte primário 900s, suporte mínimo LOW ≥ 5 e HIGH ≥ 5 por subcohort, os 9 gates de PASS, a auditoria causal (≥30 linhas causais por subcohort etc.) e os gates de sistema da subcohort (`SUBCOHORT_MIN_DECISIONS=30`, `target_lateness_p95_max_seconds=2`, `lineage_violations=0`, `ready_horizons=3`). Nada abaixo muda nenhum desses valores.

## Árvore de decisão

### 1. Falha de aquisição / sistema / auditoria causal (não é veredito econômico)

Inclui `FAIL_V68_SIGNAL_PLANE_SUBCOHORT` e qualquer falha da auditoria causal antes do gate econômico primário.

- Loga o resultado, queima as chaves `v68-09-A`/`v68-09-B`, faz a análise de causa raiz.
- **Não roda `v68-10` por conta própria.**
- Orçamento de infra do V68 (regra adotada pelo operador nesta rodada): **no máximo mais 1 ciclo, e só se o fix vier de medição** (timestamp por tentativa — item A4, branch separado). Se o próximo fix não puder ser derivado de medição, vira um sprint de hardening dedicado antes de qualquer nova tentativa.
- Se a falha for de novo `lateness_p95 > 2` em alguma cohort: o próximo fix não pode ser outro valor de constante de backoff escolhido sem medição.

### 2. `INCONCLUSIVE_V68_PRIMARY_SUPPORT`

- Amostra queimada.
- **Não roda chave nova automaticamente.** Rodar de novo depois de ter visto dado econômico é parada opcional. Só é permitido com uma regra de parada escrita e aprovada pelo operador **antes** da nova tentativa.

### 3. `FAIL_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS` ou `FAIL_V68_FEATURE_OBSERVABILITY`

- V68 fechado de vez, pela disciplina de falha do protocolo: sem MID, sem outro horizonte (300s/3600s), sem outra feature v55, sem combinar features, sem olhar só uma subcohort, sem reusar a amostra.
- O caminho para um edge passa a ser v60 (Opportunity Wallet Convergence) e Bundle Bot Detection V0 com placebo pareado por atividade (rascunhos da A6).

### 4. `PASS_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS`

Primeiro sinal prospectivo do programa, mas **não é edge**. O próprio protocolo diz que um PASS não prova montagem executável de transação, probabilidade de landing/fill, slippage/priority fee líquidos, lucro da política de saída, lucro em shadow, nem edge com dinheiro real.

Próximos passos obrigatórios, nessa ordem, sem pular nenhum:

1. **Relatório de robustez descritivo** (não muda o veredito): n por bin por subcohort, média e mediana, profit factor, resultado sem o maior vencedor e sem o top-3, participação do maior vencedor no lucro bruto, cobertura e missingness — a lista do Gate 3 de `docs/live-readiness-gates-v1.md`.
2. **Gate 2 na mesma amostra** (descritivo, barato): replay causal com custos reais sobre o subconjunto LOW (priority fee, fee de transação, delay de decisão, stale quote). Se o resultado líquido de custos não for positivo, para e reporta ao operador antes de gastar uma replicação.
3. **Replicação confirmatória pré-registrada**: mesmas regras congeladas, chave nova, meta de n maior (o mínimo de 5 por bin é frágil). A pré-registração é escrita e commitada antes da replicação rodar.
4. Só depois disso o LOW vira candidato a sinal TAKE/SKIP humano (caminho do produto) e depois Gate 4 (shadow). **Nada de dinheiro real em nenhuma etapa.**

## Leva para o operador (ninguém decide sozinho)

- O draft "Participant Quality Tail-Risk Shadow Annotation V0" (`52c9c21`), que espera sign-off explícito.
- Qualquer conflito encontrado nas notas A2 / A3.
- A decisão de orçamento de infra caso o v68-09 falhe (regra acima vale até o operador dizer o contrário).

## Guardrails

- Nenhum resultado FAIL/KILL/INCONCLUSIVE fechado é reaberto.
- Nenhum threshold econômico congelado é tocado (`V68_LOW_MAX`, `V68_MID_MAX`, os 9 gates do PASS, `SUBCOHORT_MIN_DECISIONS`, `target_lateness_p95_max_seconds`).
- Nada vai para o signal plane ao vivo ou shadow sem veredito econômico escrito.
