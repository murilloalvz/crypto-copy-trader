# Pré-registro — CD-PROMO-V0 — Promoção de `mf_top_wallet_gross_share_delta_pct_points_late_minus_early` para `selector_eligible` — 2026-10-05

Status: **PRE-REGISTRADO.** Aberto por instrução direta do operador em 2026-10-05
("abre a promoção do CD-V0 pra selector_eligible"), em resposta ao Candidato B do
rascunho `docs/rejection-filter-stack-v0-preregistration-DRAFT-2026-10-05.md`.
Commitado **antes** de qualquer coleta nova — nenhuma coleta foi iniciada.

Regras do programa: `docs/research-hypothesis-registry-v1-2026-10-04.md`.

## 0. O que isto NÃO é

- **Não reabre CD-V0.** CD-V0 permanece exatamente como está no registro e no
  `RESEARCH_STATE_LEDGER_2026-09-27.md`: discovery `ITERATE`, confirmação fresh
  `INCONCLUSIVE_CONCENTRATION_DECAY_CONFIRMATION_SUPPORT` (n=9 vs mínimo
  congelado 10), estacionada. A disposição congelada dessa hipótese — no second
  ITERATE, no threshold movement, no direction flip, no subgroup rescue,
  independent replication not armed, no positive edge claim — não é tocada por
  este documento.
- **Não é uma segunda ITERATE do protocolo de discovery da CD-V0.** É uma
  hipótese nova e separada (regra 3 do registro: "uma ideia derivada vira
  hipótese nova, com linha própria e pré-registro novo"), permitida porque CD-V0
  não foi fechada como FAIL/KILL — só estacionada como INCONCLUSIVE.
- **A pergunta aqui é diferente da pergunta da CD-V0.** CD-V0 perguntava "há
  edge econômico?". CD-PROMO-V0 pergunta "há suporte suficiente, numa amostra
  fresca, pra remover a barreira de catálogo que impede essa feature de ser
  usada como seletor?" Um PASS aqui promove a feature; não equivale a `VALIDADA`
  (regra 2 do registro ainda exige replicação independente + Gate 2 depois
  disso).
- **Não muda corte, direção ou horizonte.** Regra idêntica à já congelada.

## 1. Por que este pré-registro é necessário (barreira confirmada em código)

- Hoje `mf_top_wallet_gross_share_delta_pct_points_late_minus_early` está
  cadastrada em `src/opportunity_feature_matrix_v0.py` (via `_discovery(...)` /
  `_DISCOVERY_COMMON`, linhas ~51-63 e ~241-246) com `selector_eligible=False`,
  `diagnostic_only=True`,
  `scientific_status="DISCOVERY_DIAGNOSTIC_ONLY_NOT_PREREGISTERED_SELECTOR"`.
- `assert_selector_feature_eligible_v0()` (linhas 422-449, mesmo arquivo) falha
  fechado com `ValueError` em qualquer tentativa de uso como seletor enquanto
  `diagnostic_only=True` — bloqueio de código, não só de corte.
- `src/opportunity_edge_hypotheses_v0.py` já registra essa mesma feature dentro
  de `H_ACCELERATION_V0`, com `threshold_contract="NO_THRESHOLD_DEFINED_DO_NOT_SWEEP"`
  e `next_experiment_role="retrospective_discovery_then_preregister_fresh_hypothesis"`
  — o próprio catálogo já previa este caminho exato: qualquer regra precisa ser
  "separately frozen before a fresh prospective capture". Este documento é esse
  congelamento.
- O protocolo/critério econômico numérico exato usado no fluxo original da
  CD-V0 vive na branch divergente `research/post-transition-pullback-reacceleration-v0`
  (não mergeada aqui) — nenhum arquivo `docs/concentration-decay-v0-*` foi
  encontrado nesta checkout. Por isso os critérios abaixo são definidos aqui,
  agora, de forma autocontida — não são cópia de um protocolo inacessível.

## 2. Regra congelada (sem mudança, idêntica à CD-V0)

- Feature: `mf_top_wallet_gross_share_delta_pct_points_late_minus_early`
  (late-half menos early-half da fatia de fluxo bruto do top wallet, em pontos
  percentuais, dentro da janela causal congelada de 5s; indisponível quando a
  identidade de wallet está incompleta — missingness explícito, nunca 0).
- Corte: `<= 0` é favorável (concentração do top wallet caindo da metade
  inicial pra metade final da janela).
- Track: `market_first`.
- Instrumento de medida: route-shadow Jupiter, sem capital — Fixed+60 como
  horizonte primário, Fixed+900 como diagnóstico (padrão já usado por
  V48/V55/V68/PQ-V1 neste repositório; trocar de instrumento exige pré-registro
  novo).

## 3. Amostra e suporte mínimo (decidido agora, antes de qualquer coleta)

- Amostra: fresca, nunca usada em CD-V0 nem em nenhuma outra hipótese deste
  registro. População-base: episódios `market_first` com o mesmo enriquecimento
  causal de 5s do V55/V68 (`src/opportunity_feature_matrix_v0.py` /
  `src/route_research_early_opportunity_v55.py`) — sem depender do pipeline
  separado do Post-Transition branch.
- Suporte mínimo: **n >= 30 pares route-usable** (não 10).
  **Justificativa explícita da escolha:** a CD-V0 original usou mínimo
  congelado de 10 e ficou INCONCLUSIVE na borda (n=9) — um suporte pequeno o
  bastante pra não resolver nem a própria pergunta que tentou responder.
  Herdar esse mesmo 10 para decidir uma promoção de catálogo (consequência
  maior: a feature passa a estar disponível a qualquer seletor futuro, não só
  mais um dado solto) repetiria o problema. n>=30 iguala o padrão já usado
  neste mesmo registro para confirmação/replicação fresca de hipóteses
  irmãs (EBPQ-REPL-V0, DEPLOYER-V0, CHURN-PROSP-V1).
  **Esta é a escolha metodológica mais discutível deste documento — fica
  explícita aqui justamente para o operador poder vetá-la ou ajustá-la agora;
  depois de iniciar a coleta, a seção 6 proíbe mudar.**
- Cobertura mínima da feature: **>= 80% por subcohort**, mesmo padrão de
  elegibilidade já usado pela V55 (`docs/route-research-v55-causal-early-opportunity-discovery-result-2026-09-08.md`,
  "pre-registered >=80% per-subcohort coverage requirement").

## 4. Critério de decisão (decidido agora)

**PASS** exige todos:
1. cobertura da feature >= 80% por subcohort;
2. n >= 30 pares route-usable total, com suporte não-trivial nos dois grupos
   (`<= 0` vs `> 0`);
3. grupo favorável (`<= 0`) com retorno mediano Fixed+60 maior que o grupo
   `> 0`, mesma direção já observada descritivamente na CD-V0 (sem flip);
4. grupo favorável com profit factor > 1 sob o instrumento route-only padrão.

**FAIL**: suporte e cobertura atingidos, mas o critério 3 e/ou 4 não se
sustenta. Fecha CD-PROMO-V0 como FAIL — feature permanece `diagnostic_only`,
sem segunda tentativa, sem retune.

**INCONCLUSIVE**: n < 30 route-usable e/ou cobertura < 80%. Permite **no
máximo uma** extensão de coleta sob a mesma regra (mesmo limite que a própria
CD-V0 já ensinou ser necessário vigiar). Se a extensão também não atingir o
suporte mínimo, CD-PROMO-V0 fecha como INCONCLUSIVE permanente — mesmo
desfecho da CD-V0 original, sem terceira tentativa.

## 5. O que um PASS aqui NÃO prova

- Não prova edge validado. Promoção só remove a barreira de catálogo
  (`diagnostic_only=True` → `False`, `selector_eligible=False` → `True`).
- A hipótese entra no registro como `PASS (aguarda replicação)`, não
  `VALIDADA` — regra 2 do registro ainda exige replicação independente sob a
  mesma regra congelada + Gate 2 líquido de custos antes de `VALIDADA`.
- Não autoriza integração em score de entrada ao vivo, shadow execution ou
  dinheiro real (invariantes de sistema #1, #2, #13 do `CLAUDE.md`).
- Não reabre nem reinterpreta o resultado fechado da CD-V0 original.

## 6. Proibido depois de ver dado

Mudar corte, direção, horizonte, suporte mínimo (30) ou gate de cobertura
(80%); trocar instrumento de medida; olhar só um subgrupo; combinar com outras
features num score; usar qualquer amostra já queimada por outra hipótese deste
registro.

## 7. Efeito de um PASS (a ser executado no mesmo commit do resultado)

1. Nova linha `PASS (aguarda replicação)` para `CD-PROMO-V0` em
   `docs/research-hypothesis-registry-v1-2026-10-04.md`.
2. Em `src/opportunity_feature_matrix_v0.py`: a entrada de
   `mf_top_wallet_gross_share_delta_pct_points_late_minus_early` deixa de usar
   `_discovery(...)`/`_DISCOVERY_COMMON` e passa a declarar explicitamente
   `selector_eligible=True`, `diagnostic_only=False`, com `scientific_status`
   referenciando `CD-PROMO-V0` como autoridade da promoção (não mais
   `DISCOVERY_DIAGNOSTIC_ONLY_NOT_PREREGISTERED_SELECTOR`).
3. Teste direcionado cobrindo a nova elegibilidade (ex.:
   `assert_selector_feature_eligible_v0` passando a aceitar essa feature em
   `track=market_first`).

Um FAIL ou INCONCLUSIVE permanente não toca o código — a feature permanece
`diagnostic_only` exatamente como está hoje.

## 8. Atualização do registro (agora)

Linha `PRE-REGISTRADA` adicionada em
`docs/research-hypothesis-registry-v1-2026-10-04.md` referenciando este
arquivo, no mesmo commit deste pré-registro. Nenhum veredito ainda — nenhuma
coleta foi iniciada.
