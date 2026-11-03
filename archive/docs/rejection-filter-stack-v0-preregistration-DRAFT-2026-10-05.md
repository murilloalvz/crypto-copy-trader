# Pré-registro em lote — LOTE-REJECTION-FILTER-STACK-V0 — 2026-10-05

Status: **RASCUNHO — aguarda sign-off do operador.** Nada rodado, nenhum corte
congelado tocado, nenhum resultado fechado reaberto. Modelo:
`docs/templates/batch-preregistration-template-v1.md`. Regras do programa:
`docs/research-hypothesis-registry-v1-2026-10-04.md`.

## Resumo executivo (leia isto primeiro)

O registro mostra 13 veredictos, 0 `VALIDADA`, e um padrão claro: nenhum seletor de
entrada se sustentou isolado, mas alguns sinais de rejeição/risco se sustentaram
(PQ-TR-V0 PASS, EBPQ-REPL-V0 PASS/KEEP, BUY-ACCEL como evidência de tail-risk,
CHURN-V0 com replicação temporal retrospectiva). A ideia: empilhar os filtros de
rejeição já existentes, cada um com o corte/direção que já tinha, e perguntar se a
base filtrada supera a base sem filtro.

**Achado deste rascunho, verificado em código, não suposto: hoje a pilha teria
K=0 filtros elegíveis.** Todo candidato examinado cai em uma das quatro barreiras
abaixo. Isso não é uma falha do rascunho — é exatamente o que a tarefa pediu pra
checar antes de gastar uma coleta. O valor entregue aqui é a lista precisa do que
falta pra cada candidato virar elegível, não uma pilha pronta pra rodar.

## 1. Coleta que julgaria este lote (se/quando algum candidato virar elegível)

- Run key(s): nenhuma reservada ainda — nenhum candidato está elegível hoje.
- Caminho de aquisição: população-base seria os episódios `market_first` já
  capturados (mesmo enriquecimento causal de 5s usado por
  `src/opportunity_feature_matrix_v0.py`/V55/V68) — **sem nova aquisição**, se e
  somente se todos os filtros usados forem da família "computável do mesmo
  caminho" (ver tabela). Qualquer filtro da família "pipeline separado" (PQ-TR-V0)
  exige sua própria coleta nova antes, descrita por filtro abaixo.
- Instrumento de medida: o mesmo benchmark route-only já usado pelos achados
  citados (route-shadow Fixed+60/+900, sem capital).
- Gates de sistema: os já congelados dessa família de aquisição (cobertura de
  feature, suporte mínimo, sem lookahead).
- Condições operacionais: leitura read-only sobre dado já persistido; nenhuma
  chamada a provider nesta fase de rascunho.

## 2. Candidatos examinados (K=0 elegíveis hoje)

### Candidato A — Participant Quality Tail-Risk Rejection (PQ-TR-V0)

- Família: qualidade de wallet · Tipo: filtro de rejeição (já validado como tal,
  não é alpha)
- Regra: LOW vs ALL na taxa de perda catastrófica (retorno 900s route-only <=
  -80%), corte outcome-blind
- Status no registro: **PASS (aguarda replicação)** — LOW 88,89% vs ALL 37,5%
- **Barreira: pipeline separado.** O corte não é um número fixo reaproveitável —
  é uma *metodologia* outcome-blind recomputada fresh a cada amostra, a partir de
  memória de wallet construída por `participant_quality_native_memory_v1.py`
  (cohorts M1-M4) → `participant_quality_native_holdout_v1.py`. Confirmado por
  código em `src/signal_plane_route_research_coordinator_v0.py`: zero wiring de
  qualidade de participante no caminho de aquisição do market-first/V68.
- **O que faria virar elegível**: rodar essa memória de wallet fresh (coleta
  nova, run key própria) ANTES de aplicar o filtro — não é algo que ande de
  carona em episódios já capturados. Mesma conclusão já registrada na avaliação
  do lote pré-v68-10 (`c2fe126`).

### Candidato B — Concentration Decay (CD-V0)

- Família: dinâmica de concentração · Tipo: entrada (alpha), hoje teria que virar
  filtro de rejeição (direção descritiva)
- Regra: `mf_top_wallet_gross_share_delta_pct_points_late_minus_early <= 0`
- Status no registro: **INCONCLUSIVE** (n=9 vs mínimo 10), estacionada — não
  fechada como FAIL/KILL, então reaproveitável com amostra nova pela mesma regra
  (regra 3 do registro só proíbe reabrir FAIL/KILL).
- **Barreira: a própria feature não é selector-eligible no catálogo do projeto.**
  `mf_top_wallet_gross_share_delta_pct_points_late_minus_early` está cadastrada em
  `src/opportunity_feature_matrix_v0.py` com `track=market_first`,
  `causal_source=preserved_frozen_5s_trade_event_sequence_before_provider_quotes`
  (ou seja, **é** computável do mesmo episódio market-first já capturado, sem
  aquisição nova) — mas com `diagnostic_only=True`, `selector_eligible=False`,
  `scientific_status=DISCOVERY_DIAGNOSTIC_ONLY_NOT_PREREGISTERED_SELECTOR`.
  `assert_selector_feature_eligible_v0()` (mesmo arquivo, linhas 422-449) falha
  fechado com `ValueError` em qualquer tentativa de usar uma feature
  `diagnostic_only`/não-`selector_eligible` como seletor. Isso bloqueia o uso
  direto, em código, não é só uma questão de corte.
- **O que faria virar elegível**: uma promoção formal dessa feature de
  `DISCOVERY_DIAGNOSTIC_ONLY` para `selector_eligible` — provavelmente a
  confirmação fresh adicional que a própria CD-V0 já pedia (n>=10), desta vez
  registrada como parte do processo de promoção, não só como mais um dado
  solto. Decisão do operador se vale abrir essa promoção agora.

### Candidato C — BUY event-rate acceleration (BUY-ACCEL)

- Família: aceleração de fluxo de compra · Tipo: evidência de tail-risk (não
  promovida como alpha)
- Regra informal observada: aceleração mais negativa/front-loaded -> taxa de
  falha de saída ~3,57%; menos negativa/positiva -> ~23,08%
- **Barreira dupla**: (1) o que existe é uma caracterização qualitativa
  (negativo vs positivo com taxas de falha associadas), não um corte numérico
  absoluto pré-registrado como regra de rejeição — reaproveitar isso exigiria
  decidir agora qual é o corte exato, o que seria tunar depois de ver o
  resultado; (2) mesmo que houvesse um corte, `mf_buy_event_rate_acceleration_per_s2`
  também está cadastrada como `diagnostic_only=True`/`selector_eligible=False`
  no mesmo catálogo — mesmo bloqueio de código do Candidato B.
- **O que faria virar elegível**: um pré-registro novo e explícito do corte
  (ex.: `aceleração < 0`, que é um corte baseado em sinal, não em dado — seria
  o único jeito honesto de reaproveitar isso sem tunar), mais a mesma promoção
  de `selector_eligible` do Candidato B.

### Candidato D — Early-Buyer Prior Quality replication (EBPQ-REPL-V0)

- Status: **PASS/KEEP** — mas a regra é "metade de cima vs metade de baixo" por
  mediana da própria amostra, não um corte numérico absoluto. Recalcular a
  mediana numa amostra nova SERIA tunar o corte com o dado que vai julgá-lo —
  exatamente o que a regra 3 do registro proíbe.
- **Fica de fora**: sem corte congelado utilizável, por desenho (metodologia de
  split relativo, não um valor fixo).

### Candidato E — Early Buyer Churn (CHURN-V0)

- Status: **PASS retrospectivo** (`RETROSPECTIVE_TEMPORAL_REPLICATION_NO_PROMOTION`)
  — mesma barreira do Candidato D: correlação de Spearman e split por mediana,
  sem corte absoluto publicado. `mf_early_buyer_roundtrip_sellback_fraction_t0_5s`
  também não está no catálogo `market_first` padrão — vive só em
  `benchmarks/early_buyer_churn_v0/` e `benchmarks/early_buyer_churn_prospective_v1/`,
  pipeline próprio dessa família, não confirmado como parte do caminho padrão de
  captura do market-first.
- **Fica de fora**: sem corte congelado utilizável, e caminho de aquisição ainda
  não confirmado como "já capturado" de graça.

### Excluídos por estarem fechados (não reabertos, por regra)

- **PQ-V1**: `KILL_NATIVE_PARTICIPANT_QUALITY_SELECTION_EDGE_CANDIDATE`. `CLAUDE.md`
  é explícito: "no integration into live entry score". Fora, sem debate.
- **EARLY-BAL-CONC-V0**: direção pré-registrada (negativa) não replicou — saiu
  com sinal oposto. Usar o sinal oposto agora seria inverter a direção depois de
  ver o dado, proibido pela regra 3. Fora.

## 3. Multiplicidade e próximos passos

- K = 0 hoje. Nenhuma coleta é autorizada ou necessária por este rascunho.
- Se o operador quiser abrir a promoção do Candidato B (CD-V0) e/ou C
  (BUY-ACCEL) de `diagnostic_only` para `selector_eligible`, isso é um trabalho
  de pré-registro separado (decidir o corte exato e o processo de promoção
  ANTES de olhar dado novo) — não cabe neste rascunho.
- Se o operador quiser armar o Candidato A (PQ-TR-V0) como parte de uma pilha
  futura, a pré-condição é rodar a memória de wallet fresh primeiro — mesma
  conclusão já registrada em `c2fe126`.
- Os Candidatos D e E (EBPQ-REPL-V0, CHURN-V0) não têm caminho óbvio pra virar
  elegíveis sem inventar um corte novo pós-hoc — provavelmente ficam fora
  permanentemente como filtros de rejeição, mesmo continuando válidos como os
  achados descritivos que já são.

## 4. Proibido depois de ver dado

Mudar corte, direção, horizonte, suporte, gates ou controles; incluir ou remover
hipóteses do lote; olhar só um subgrupo; combinar hipóteses num score. Nada disso
se aplica ainda, já que K=0, mas vale registrado pra quando algum candidato virar
elegível.

## 5. Atualização do registro

Nenhuma linha nova no registro a partir deste rascunho — nenhum veredito foi
produzido, só uma avaliação de elegibilidade. Se o operador autorizar a promoção
de algum candidato, essa decisão (e seu próprio pré-registro) é que ganha linha
própria depois.
