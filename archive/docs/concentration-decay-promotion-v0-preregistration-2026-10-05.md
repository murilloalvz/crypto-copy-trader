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
- **Correção desta revisão, confirmada em código:** a seção 3 original deste
  documento assumia o pipeline de aquisição A/B do V55/V68
  (`route_research_forward_cohort_v46`/`v43`). Isso está errado para esta
  feature específica. Lendo `src/market_first_feature_discovery_v1.py` e
  `benchmarks/market_first_feature_discovery_v1/run.py`, o único lugar nesta
  checkout que computa `mf_top_wallet_gross_share_delta_pct_points_late_minus_early`
  de fato é o benchmark de discovery retrospectivo do Market-First, que
  reconstrói a feature a partir de um run-dir já produzido pelo pipeline
  **Launch Burst Sniper V1** (`benchmarks.launch_burst_control_taker_sim_v0.run_v4_sniper_v1`)
  — uma terceira linha de aquisição, distinta tanto do V55/V68 quanto do
  Post-Transition. Corrigido abaixo (seção 3).

## 2. Regra congelada (sem mudança, idêntica à CD-V0)

- Feature: `mf_top_wallet_gross_share_delta_pct_points_late_minus_early`
  (late-half menos early-half da fatia de fluxo bruto do top wallet, em pontos
  percentuais, dentro da janela causal congelada de 5s; indisponível quando a
  identidade de wallet está incompleta — missingness explícito, nunca 0).
- Corte: `<= 0` é favorável (concentração do top wallet caindo da metade
  inicial pra metade final da janela).
- Track: `market_first`.
- Instrumento de medida: route-paper fixo **+60s** (`fixed_return_pct`), sem
  capital — único horizonte que este pipeline produz; **não há diagnóstico em
  +900s disponível aqui** (corrigido nesta revisão — a seção original citava
  Fixed+900 por analogia com V48/V55/V68, que não se aplica a este pipeline).
  Trocar de instrumento exige pré-registro novo.

## 3. Amostra e suporte mínimo (decidido agora, antes de qualquer coleta)

- **Pipeline de aquisição real (corrigido nesta revisão, confirmado em
  código/doc operacional — `docs/launch-burst-sniper-v1-operator-runbook-2026-09-16.md`):**
  cohort `baseline_admitted` de uma screening única e congelada de **900
  segundos** do Launch Burst Sniper V1 (`run_v4_sniper_v1`), replayada pelo
  benchmark `market_first_feature_discovery_v1` para computar
  `mf_top_wallet_gross_share_delta_pct_points_late_minus_early` por episódio.
  Não existem subcohorts A/B aqui — é uma única janela, e a duração de 900s é
  congelada pelo próprio runner (recusa mudança in-place).
  Usar o cohort `baseline` (admitido pela política Launch Burst base), não o
  `sniper_selected` (subconjunto filtrado pelo seletor Sniper V1) — CD-PROMO-V0
  pergunta sobre a feature em geral, não sobre a população já filtrada pelo
  Sniper.
- Amostra: fresca — um run-dir novo do Launch Burst Sniper V1, nunca antes
  analisado por esta ou por nenhuma outra hipótese deste registro.
- Suporte mínimo: **n >= 10 pares route-usable** (`baseline_admitted=True`
  com `fixed_return_pct` e a feature ambos disponíveis), igual ao mínimo
  congelado já usado pela própria CD-V0. **Consistente com a convenção já
  documentada deste MESMO pipeline** (`docs/launch-burst-sniper-v1-operator-runbook-2026-09-16.md`,
  "Frozen sample interpretation": <10 = `INSUFFICIENT_PRIMARY_SAMPLE`; 10–29 =
  leitura direcional descritiva; >=30 = elegível para replicação independente).
  **Decisão do operador (2026-10-05), substituindo a escolha original deste
  documento (n>=30).** Esta troca é feita ANTES de qualquer coleta — nenhum
  dado foi visto, então não viola a seção 6 (que só proíbe mudar depois de
  ver dado). Registrado para transparência: a primeira versão deste
  pré-registro propunha n>=30 (padrão de replicação fresca usado por
  EBPQ-REPL-V0/DEPLOYER-V0/CHURN-PROSP-V1), justamente porque o 10 da CD-V0
  ficou na borda (INCONCLUSIVE em n=9). O operador optou por manter
  consistência com o corte já congelado da própria CD-V0 em vez de endurecer
  o suporte. A partir deste commit, **n>=10 é o número congelado** para
  CD-PROMO-V0 — depois de iniciar a coleta, não pode mais mudar.
- Cobertura mínima da feature: **>= 80%** dos episódios `baseline_admitted`
  com `fixed_return_pct` disponível (não há subcohorts aqui — correção desta
  revisão; o número 80% em si segue o mesmo padrão de elegibilidade já usado
  pela V55, `docs/route-research-v55-causal-early-opportunity-discovery-result-2026-09-08.md`).

## 4. Critério de decisão (decidido agora)

**PASS** exige todos:
1. cobertura da feature >= 80% dos episódios `baseline_admitted` com outcome
   disponível;
2. n >= 10 pares route-usable total, com suporte não-trivial nos dois grupos
   (`<= 0` vs `> 0`);
3. grupo favorável (`<= 0`) com retorno mediano Fixed+60 maior que o grupo
   `> 0`, mesma direção já observada descritivamente na CD-V0 (sem flip);
4. grupo favorável com profit factor > 1 sob o mesmo instrumento route-paper
   fixo +60s.

**FAIL**: suporte e cobertura atingidos, mas o critério 3 e/ou 4 não se
sustenta. Fecha CD-PROMO-V0 como FAIL — feature permanece `diagnostic_only`,
sem segunda tentativa, sem retune.

**INCONCLUSIVE**: n < 10 route-usable e/ou cobertura < 80%. Permite **no
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

Mudar corte, direção, horizonte, suporte mínimo (10) ou gate de cobertura
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

## 9. Ferramentas prontas para a coleta (adicionadas nesta revisão)

- Runbook com os comandos exatos, em ordem, para rodar a coleta e o veredito:
  `docs/concentration-decay-promotion-v0-collection-runbook-2026-10-05.md`.
- Calculadora de veredito (aplica os critérios da seção 4 sem reinterpretação
  manual): `benchmarks/market_first_feature_discovery_v1/cd_promo_v0_verdict.py`,
  reusando `return_metrics_v47` já existente (`src/route_research_feature_review_v47.py`)
  em vez de recalcular mediana/profit factor à mão.
