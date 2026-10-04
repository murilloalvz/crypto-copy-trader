# V68 — certificação de não-espiada, tentativas v68-04 a v68-08 (Fase A / A3) — 2026-10-04

Modo: PAPER / RESEARCH / READ ONLY. Análise estática de código e de docs commitados; nenhuma chamada a provider, nenhum acesso ao SQLite de produção.

Escrito antes do resultado do `v68-09` existir.

## Pergunta

Em alguma tentativa abortada (v68-04 a v68-08, em especial a cohort A do v68-08, que passou nos gates de sistema) foi calculado ou exibido algum número econômico do contraste LOW/HIGH?

## Resposta curta

- **Contraste LOW/HIGH: certificado que não**, pelo fluxo de controle do harness. Ele só pode ser calculado se as duas subcohorts passarem nos gates de sistema e a auditoria causal passar. Nenhuma das tentativas v68-04 a v68-08 chegou lá.
- **Retorno agregado da subcohort (todos os episódios juntos, sem divisão LOW/HIGH): é calculado em memória e descartado** pelo harness em toda subcohort que chega na checagem de prontidão. O harness não exibe esses números. Não é possível certificar, só com o repositório, que um diagnóstico manual (por exemplo `evaluate_route_research_run` rodado à mão no v68-08) não os exibiu.
- **Mesmo no pior caso, o contrato econômico não pode ter sido influenciado**: todo o código que define e avalia o gate primário está inalterado desde o freeze de 2026-09-08 (verificado pelo histórico do git abaixo).

## Evidência 1 — o gate LOW/HIGH só é alcançável se A e B passarem

Arquivo: `route_research_prospective_flow60_buy_share_holdout_v68_signal_plane_v0.py`, função `run_signal_plane_v68_v0` (commit de referência `57275d1`).

1. As subcohorts rodam em sequência (`for run_key in run_keys`, linhas ~103-129). Se `result.passed` for falso em qualquer uma, a função retorna imediatamente `FAIL_V68_SIGNAL_PLANE_SUBCOHORT` (linhas ~118-129). O retorno contém só os campos de sistema de cada subcohort (`item.__dict__` do `SignalPlaneForwardCohortResultV0`), sem nenhum campo econômico.
2. `build_early_opportunity_dataset_v55`, que é onde a feature `flow60_buy_share_pct` é calculada e cada linha ganha seu bin LOW/MID/HIGH, só é chamado depois do loop (linha ~131).
3. Se a auditoria causal falhar, retorna `FAIL_V68_SIGNAL_PLANE_CAUSAL_HOLDOUT_AUDIT` com contagens de linhas e booleanos (linhas ~155-168), ainda sem números econômicos.
4. `primary_gate_v68` só é chamado na linha ~169, depois de tudo acima. Mesmo nesse caso, o relatório e o `main()` exibem apenas os booleanos dos 9 gates (`support_ok`, `same_direction_ok` etc.) e a classificação, não medianas nem profit factor.

Todas as tentativas v68-04 a v68-08 terminaram em `FAIL_V68_SIGNAL_PLANE_SUBCOHORT` (registro em `docs/migration/RESEARCH_STATE_LEDGER_2026-09-27.md`, commits `6c29774`, `c1de787`, `6c8c225`, `f865745`). No v68-08, a cohort A passou e a cohort B falhou em `lateness_p95`, então o retorno aconteceu na iteração de B, antes da linha ~131. Logo, nenhuma linha de nenhuma dessas tentativas recebeu bin LOW/HIGH, e o gate primário nunca rodou.

## Evidência 2 — métricas agregadas em memória (achado desta certificação)

Arquivo: `src/signal_plane_forward_cohort_v0.py`, função `_descriptive_readiness` (linhas ~59-66). Ela chama `evaluate_route_research_run(acquisition_run_key=...)` (`src/route_research_evaluation.py`), que calcula para cada horizonte 300/900/3600 a média, mediana, profit factor, melhor/pior retorno e `mean_without_best` **de todos os episódios da subcohort juntos** (`RouteResearchHorizonMetrics`, linhas ~16-32). O harness usa apenas a `classification` de prontidão de cada horizonte e `lineage_violations`. Os números econômicos ficam em memória e são descartados, sem print e sem persistência.

O que o harness imprime durante a coleta (`src/route_research_forward_collection_v43.py`, linhas ~85-127): episódio, horizonte, `target`, status do provider e do outcome, `observed_at`. Nenhum preço ou retorno.

Os docs que registraram v68-04 a v68-08 (o ledger acima) foram varridos por "median", "profit factor", "return", "retorno", "mean_without": nenhum número econômico aparece neles.

**Diagnósticos manuais registrados no ledger:** `evaluate_route_research_run` foi rodado à mão em `v68-05-A` e `v68-06-A`, mas as duas tinham `available=0` em todos os horizontes (a coleta nunca começou), então não havia retorno nenhum para ver. Em `v68-07-A` o ledger registra o uso de `load_route_research_outcomes` para ler `error_type`/`error_message`; 38 outcomes de 300s foram capturados nessa subcohort.

**Limite desta certificação:** o ledger não diz se o objeto completo de `v68-07-A` ou de `v68-08-A/B` foi impresso. O diagnóstico manual do v68-08 (reconstrução dos retries a partir de `observed_at - target_at`, citado no `f865745` e no handoff) e os logs de execução na máquina do operador não estão no repositório. Se algum desses passos rodou `evaluate_route_research_run` e imprimiu o objeto inteiro, o retorno agregado (não o LOW/HIGH) de alguma subcohort pode ter sido visto. Quem rodou esses diagnósticos deve confirmar ou negar isso por escrito.

## Evidência 3 — o contrato econômico está intacto desde o freeze

`git log` desde 2026-09-08 nos arquivos que definem ou calculam o gate primário:

| Arquivo | Último commit |
|---|---|
| `src/route_research_prospective_flow60_buy_share_v68.py` (cutpoints, suporte, `primary_gate_v68`) | `d401141`, 2026-09-08 (o próprio commit de freeze; nenhum depois) |
| `src/route_research_feature_robustness_v47.py` (`robust_return_metrics_v47`, usado no gate) | nenhum commit desde 2026-09-08 |
| `src/route_research_feature_review_v47.py` (`CausalFeatureRowV47`) | nenhum commit desde 2026-09-08 |
| `src/route_research_early_opportunity_v55.py` (dataset e feature) | nenhum commit desde 2026-09-08 |
| `src/route_research_evaluation.py` | nenhum commit desde 2026-09-08 |

Ou seja: mesmo que algum número agregado tenha sido visto num diagnóstico manual, nada no gate, nos cutpoints, no horizonte ou na feature mudou depois disso. A única coisa que mudou entre tentativas foram parâmetros de sistema (retry/backoff — ver a nota de conformidade A2).

## Risco residual e recomendação

O único canal que ainda existe é a parada opcional: ver retornos agregados bons ou ruins pode influenciar a decisão de continuar tentando. Como o protocolo permite repetir tentativas que falham por sistema e a regra de orçamento de infra agora está escrita (A1), esse risco fica limitado.

Recomendação daqui em diante: em relatórios de tentativas que não chegaram ao gate primário (Fase B incluída), exibir só os campos de sistema de `RouteResearchHorizonMetrics` (`scheduled`, `available`, `pending`, `unavailable_or_error`, `coverage_pct`, `classification`) e os de lateness/lineage, nunca os campos de retorno (`*_return_pct`, `profit_factor`, `positive_share_pct`, `largest_winner_share_of_gross_profit_pct`).
