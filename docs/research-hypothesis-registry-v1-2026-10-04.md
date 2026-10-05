# Registro de hipóteses do programa — v1 — 2026-10-04

Modo: PAPER / RESEARCH / READ ONLY.

## Para que serve

O programa vai testar estratégias até uma funcionar. Quanto mais estratégias se testa, maior a chance de alguma passar por sorte: com 20 testes independentes e 5% de chance de PASS falso em cada um, a chance de pelo menos um PASS falso é de ~64% (1 − 0,95²⁰). Este registro existe para que "funcionou" signifique algo:

1. **toda** hipótese econômica testada entra aqui, inclusive as que falharam;
2. um PASS isolado nunca é tratado como edge;
3. dá para saber, a qualquer momento, quantas tentativas o programa já gastou.

## Regras do programa

1. **Entrada antes do teste.** A hipótese ganha uma linha com status `PRE-REGISTRADA` e a referência do pré-registro commitado antes da coleta que vai julgá-la.
2. **Edge validado = três passos, nessa ordem:**
   - PASS no teste pré-registrado;
   - PASS de novo numa replicação com a **mesma regra congelada** e amostra nova;
   - resultado positivo líquido de custos (Gate 2 de `docs/live-readiness-gates-v1.md`).
   Só então o status vira `VALIDADA`. Com essa regra, a chance de um falso positivo chegar a `VALIDADA` cai de ~5% para ~0,25% por hipótese (no exemplo de 5%).
3. **FAIL/KILL fecha a hipótese.** Nada de mexer no corte, trocar horizonte, trocar direção ou olhar só um subgrupo. Uma ideia derivada vira hipótese nova, com linha própria e pré-registro novo.
4. **Discovery não é validação.** Uma varredura que compara muitas features (como a V55: 18 features × 3 horizontes) é registrada com o número de comparações e só gera candidatos. Candidato passa por holdout próprio.
5. **Falha de sistema não gasta tentativa.** Se a coleta falhou antes do gate econômico, não houve teste. A linha registra a tentativa de sistema, mas o contador de veredictos não anda.
6. **Pré-registro em lote é permitido e recomendado.** Várias hipóteses podem ser julgadas na mesma coleta, desde que todas estejam pré-registradas antes dela (modelo: `docs/templates/batch-preregistration-template-v1.md`). O lote registra quantas hipóteses havia (K). Qualquer PASS dentro do lote vai sozinho para replicação.
7. **Revisão periódica (sugestão — decisão do operador):** a cada 10 veredictos econômicos sem nenhuma hipótese `VALIDADA`, uma revisão do programa: famílias de sinal, instrumento de medida, custo por teste. Não é critério de parada, é ponto de checagem.

## Vocabulário de status

`PRE-REGISTRADA` · `EM COLETA` · `SEM VEREDITO (sistema)` · `PASS (aguarda replicação)` · `VALIDADA` · `FAIL` · `KILL` · `INCONCLUSIVE` · `DISCOVERY (gera candidatos)` · `CLOSED/BURNED` · `RASCUNHO`

## Contadores (atualizar a cada linha)

| | Total |
|---|---|
| Veredictos econômicos (PASS, FAIL, KILL, INCONCLUSIVE com dado) | 4 confirmados (V48, PQ-V1, PQ-TR-V0, CD-V0) + LB-V4 a confirmar + as linhas a levantar |
| Comparações em discovery | ≥ 54 (V55) + Concentration Decay discovery + as linhas a levantar |
| PASS aguardando replicação | 1 (Tail-Risk Rejection V0, filtro de rejeição) |
| VALIDADA | 0 |

## Hipóteses com veredito ou status conhecido

| ID | Família | Regra / feature | Tipo | Amostra / data | Status | Fonte |
|---|---|---|---|---|---|---|
| V48 | fluxo inicial | `flow60_event_count`, bins congelados, 900s | entrada (alpha) | holdout prospectivo A/B, 2026-09-07 | **FAIL** (direção inverte entre A e B) | `docs/route-research-v48-prospective-flow60-result-2026-09-07.md` |
| V55 | fluxo inicial | varredura de 18 features × 3 horizontes | discovery | 2026-09-08 | **DISCOVERY** — 1 candidato (`flow60_buy_share_pct`, LOW favorável); amostra queimada | `docs/route-research-v55-causal-early-opportunity-discovery-result-2026-09-08.md` |
| V68 | fluxo inicial | `flow60_buy_share_pct` LOW ≤ 57,1429 vs HIGH > 65,7143, 900s, 9 gates | entrada (alpha) | v68-04 a v68-09: só falhas de sistema | **SEM VEREDITO (sistema)**; v68-10 é o último ciclo do orçamento de infra | protocolo V68 + `docs/v68-09-preregistered-decision-tree-2026-10-04.md` + ledger |
| PQ-V1 | qualidade dos participantes | `native_participant_prior_900_route_quote_return_median_of_wallet_medians_pct`, corte −65,65, HIGH favorável | entrada (alpha) | H1+H2, 2026-09-24 | **KILL** (falhou só o gate de PF: HIGH 0,4437 vs LOW 0,4653) | `docs/native-participant-quality-holdout-v1-result-2026-09-24.md` |
| PQ-TR-V0 | qualidade dos participantes | LOW vs ALL na taxa de perda catastrófica, corte novo outcome-blind | **filtro de rejeição** (não alpha) | 4ª tentativa, RPC pago, 2026-09-29 | **PASS (aguarda replicação)** — LOW 88,89% vs ALL 37,5% (barra de 15pp) | commit `3914c6d`; pré-registro `docs/participant-quality-tail-risk-rejection-v0-preregistration-2026-09-28.md` |
| CD-V0 | concentração | `mf_top_wallet_gross_share_delta_pct_points_late_minus_early <= 0` | entrada (alpha) | discovery + confirmação fresh, 2026-09-25 | **INCONCLUSIVE** (n=9 vs mínimo 10; descritivamente pior que a base); estacionada | branch Post-Transition, `docs/concentration-decay-v0-*` |
| PT-V0 | pós-transição | Post-Transition Fresh Economic Discovery V0 | discovery | 2026-09-25 | **CLOSED/BURNED** (n econômico condicional = 0) | branch Post-Transition, `fresh_economic_discovery_v0.closed.json` |
| LB-V4 | launch burst | hipótese econômica oficial do Launch Burst V4 | entrada (alpha) | — | **INCONCLUSIVE**, congelada até um taker financiado controlado | `docs/launch-burst-sniper-v1-preregistration-2026-09-15.md` (contexto) |

## Pré-registradas sem resultado conhecido nesta branch

| ID | Status declarado no próprio doc | Fonte |
|---|---|---|
| LB-SNIPER-V1 | PREREGISTERED / NO OUTCOME-BEARING RUN YET | `docs/launch-burst-sniper-v1-preregistration-2026-09-15.md` |
| LB-MOMENTUM-CONV-V0 | pré-registro; sem resultado localizado | `docs/launch-burst-momentum-convergence-v0-prereg-2026-09-16.md` |
| LB-DISCOVERY-V0 | PREREGISTERED / NOT YET RUN | `docs/launch-burst-discovery-v0-preregistration-2026-09-10.md` |
| MAD-V0 | PREREGISTERED / NO OUTCOMES INSPECTED | `docs/market-activity-dynamics-discovery-run-v0-2026-09-11.md` |
| BPS-V0 | protocolo de discovery sobre amostra já queimada | `docs/burst-participation-structure-discovery-v0-protocol-2026-09-24.md` |
| V60 | RASCUNHO, aguarda sign-off | `docs/v60-wallet-convergence-discovery-v0-preregistration-DRAFT-2026-10-04.md` |
| BUNDLE-V0 | RASCUNHO, aguarda sign-off; bloqueado por observabilidade (slot/creator) | `docs/bundle-bot-detection-v0-preregistration-DRAFT-2026-10-04.md` |
| PQ-TR-SHADOW-V0 | RASCUNHO, aguarda sign-off | commit `52c9c21` |

## A levantar (obrigatório para os contadores ficarem honestos)

O repositório tem mais de 40 branches `research/*`. Várias têm cara de teste econômico com resultado próprio que não aparece nesta branch nem no ledger da migração, por exemplo: `early-buyer-churn-v0`, `early-buyer-churn-robustness-v0`, `early-buyer-churn-prospective-v1`, `early-buyer-prior-quality-v0`, `early-buyer-prior-quality-replication-v0`, `deployer-prior-quality-v0`, `econ-organicity-concentration-v0`, `buy-event-acceleration-replication-v0`, `curve-capacity-replication-v0`, `holder-ownership-*`, `burst-momentum-convergence-v0`, `burst-opportunity-selection-lab-v0`, `solana-burst-economic-sim-v0`, `exit-hypothesis-bankroll-sim-v0`, `market-first-*-discovery-*`, além de Wallet Forward v2 (`docs/wallet-forward-v2-run1-result-2026-09-02.md`) e Wave v2/v3.

Para cada uma: ler o último commit e os docs de resultado, e registrar aqui uma linha com tipo (discovery / entrada / filtro), número de comparações se for discovery, e status. Sem isso, o contador de tentativas subestima o total e a regra 2 perde força.
