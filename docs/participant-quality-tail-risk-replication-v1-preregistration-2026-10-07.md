# Participant Quality Tail-Risk Rejection — Replication V1 — Preregistration — 2026-10-07

Status: **PRE-REGISTRADA.** Autoriza a coleta descrita abaixo. Commitado antes de qualquer memory
build ou acquisition desta replicação começar.

## Por que esta replicação, e por que agora

`docs/research-hypothesis-registry-v1-2026-10-04.md` registra `PQ-TR-V0` como o único **PASS**
econômico real deste programa até agora (LOW catastrophic-loss 88,89% vs ALL 37,5%, gap 51,4pp,
bar 15pp — `artifacts/participant_quality_tail_risk_rejection_v0/participant-quality-tail-risk-v0-20260929-04-report.json`).
A própria regra 2 do registro exige, antes de qualquer outra coisa: "PASS de novo numa replicação
com a mesma regra congelada e amostra nova" — isso tem prioridade sobre abrir qualquer hipótese de
sinal de entrada nova, porque é o único caminho restante para `VALIDADA` neste programa.

## O que NÃO é

- não é uma nova descoberta (não se recalcula nada a partir desta amostra nova);
- não reabre, retuna ou reinterpreta `PASS_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0`
  (`docs/participant-quality-tail-risk-rejection-v0-preregistration-2026-09-28.md`), que permanece
  fechado exatamente como está;
- não autoriza score de entrada ao vivo, nem execução funded.

## Regra congelada (idêntica ao V0, sem excecões)

| Elemento | Valor |
|---|---|
| Feature | `native_participant_prior_900_route_quote_return_median_of_wallet_medians_pct` |
| Cutoff | **`-86.0484432047999`** — fixo, o número realizado do V0 (não recalculado pelo procedimento nesta amostra nova) |
| Grupo favorável | `HIGH` |
| Contraste primário | LOW vs ALL (não LOW vs HIGH) |
| Horizonte primário | 900s |
| Suporte mínimo | LOW >= 15 pares; ALL >= 40 pares |
| Gate PASS 1 | LOW catastrophic-loss rate (retorno 900s <= -80%) > ALL |
| Gate PASS 2 | gap LOW − ALL >= 15 pontos percentuais |
| Gate PASS 3 | excluir LOW não piora a mediana do grupo mantido (HIGH-only median >= ALL median) |
| Classificações | `PASS_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0` / `FAIL_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0` / `INCONCLUSIVE_PARTICIPANT_QUALITY_TAIL_RISK_REJECTION_V0_SUPPORT` |

O avaliador é reusado **sem nenhuma alteração**: `participant_quality_tail_risk_rejection_v0.py`
(lê só `rows[].group`/`rows[].outcome_900_return_pct` de um holdout report — não importa qual
script produziu esse report, desde que o schema bata). As 3 classificações acima são sobre a
*regra* (tail-risk rejection), não sobre a amostra V0 especificamente — reaplicá-las a uma amostra
nova é exatamente o que "replicação" significa aqui.

### O que muda em relação ao V0 — e por quê (única diferença metodológica desta replicação)

A memória de wallets (histórico causal usado para computar a feature de cada episódio novo) é
**reconstruída do zero para o período novo**, via um memory build fresh próprio (M1-M4 novos, run
key novo — seção "Chaves de run" abaixo). Isso é causal por construção: só usa dados anteriores a
cada episódio, do jeito que o pipeline `participant_quality_native_memory_v1.py` já faz.

O número do cutoff, porém, **não é recalculado** a partir desse memory build novo. Ele fica fixo em
`-86.0484432047999` — o valor que o V0 realizou. Deixar o procedimento recalcular um cutoff novo a
cada amostra reaplicaria o *método*, não a *regra*: o limiar mudaria amostra a amostra, o que é uma
réplica mais fraca (o teste se adapta ao dado em vez de ser falseável pelo dado). Congelar o número
é o que torna isto uma replicação de verdade da mesma regra, não uma descoberta paralela que por
coincidência reusa o método.

Implementação: `participant_quality_tail_risk_replication_v1.py` (novo arquivo, raiz do repo,
mesmo padrão de `participant_quality_tail_risk_holdout_v0.py` — importa e sobrescreve em runtime os
atributos de módulo de `participant_quality_native_holdout_v1.py`, que fica intocado). A única
diferença de comportamento em relação ao wrapper do V0: `_validate_memory_report` é substituída por
uma versão que não exige que o cutoff *próprio* desta amostra nova bata com o cutoff congelado — essa
discordância é esperada e correta aqui, não um erro. Tudo o resto (agendamento de aquisição, bridge,
`evaluate_rows`, montagem do report) é reusado sem mudança. `--self-check` já validado nesta branch
antes deste commit.

## Chaves de run (novas, nunca usadas)

- Memory build (M1-M4): `participant-quality-tail-risk-replication-v1-20261007-01`
- Primeira tentativa de holdout (H1/H2): mesma base,
  `participant-quality-tail-risk-replication-v1-20261007-01` (mesma convenção do V0: a tentativa 01
  de holdout reusa o número da memória; uma retentativa por falha de sistema sobe para `-02`, `-03`,
  mantendo a memória fixa em `-01`)

`_strict_run_keys_fresh` (já existente, reusado sem mudança) impede reuso de qualquer chave —
nenhuma chance de colidir com o V0 ou com qualquer outra hipótese.

## Regras operacionais (congeladas agora, não depois de ver problema)

1. Saída de todo comando "live" redirecionada só para arquivo (`*> arquivo.log`) — nunca só
   console, e nunca `Tee-Object`/`tee` (ver seção "Correções de sistema" abaixo: `Tee-Object`
   continua ecoando no console e pode travar o processo junto com ele).
2. Sem suspensão de energia durante qualquer passo live.
3. RPC dedicado Helius (pago) — o free tier já falhou 3x nesta linha de pesquisa (CD-PROMO-V0,
   2026-10-06/07: HTTP 429/timeout). Nenhuma outra chave além da do Helius dedicado.
4. Nenhum outro uso das chaves (`HELIUS_API_KEY`/`SOLANA_RPC_URL`/`JUPITER_API_KEY`) durante a
   janela de coleta desta replicação — nenhum outro script rodando contra o mesmo RPC ao mesmo
   tempo.
5. **Nunca rodar ao mesmo tempo que uma coleta V68** (mesmo bridge/coordinator compartilhado —
   `route_research_signal_plane_bridge_v0` + `SignalPlaneRouteResearchCoordinatorV0` — rodar os dois
   juntos arrisca contenção de RPC/Signal-Plane e confunde qual run_key está sob qual carga). **V68
   está fechado permanentemente desde 2026-10-05 (`FAIL_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS`,
   `docs/route-research-v68-prospective-flow60-buy-share-result-2026-10-05.md`) — não há coleta V68
   ativa ou planejada. Esta regra fica registrada para o caso de uma reabertura futura do V68 ser
   decidida (o que exigiria sua própria justificativa, separada desta replicação), não porque há
   algo pendente nele hoje.** Ver nota separada no handoff desta sessão sobre esse ponto.

## Disciplina de falha (idêntica a todo outro protocolo congelado deste repo)

- falha de sistema (bridge/memory/900s-maturity não `PASS`) não conta como tentativa — registrar e
  não contar;
- `PASS`: feature vira candidata oficial a `VALIDADA`, mas só depois do Gate 2 de custo
  (`docs/live-readiness-gates-v1.md`) — esta replicação por si só não autoriza isso. O Gate 2
  específico deste filtro já está rascunhado e aguardando seu sign-off, escrito antes deste
  veredito existir:
  `docs/participant-quality-tail-risk-gate2-cost-preregistration-DRAFT-2026-10-07.md`. Só se aplica
  se este veredito for `PASS`;
- `FAIL`: a linha fecha e **o filtro sai da pilha** — não se tenta outro horizonte, outro contraste,
  ou uma 2ª replicação;
- `INCONCLUSIVE` (suporte insuficiente): mesma disciplina de extensão única já usada em
  CD-PROMO-V0 — no máximo 1 extensão de coleta, run key novo, sem mudar nenhum parâmetro desta
  tabela.

## Correções de sistema aplicadas antes da coleta (2026-10-07, mesmo dia, antes de qualquer run)

Nenhuma delas toca a regra congelada (feature, cutoff, contraste, horizonte, suporte mínimo, gates
de PASS). Registradas aqui porque o CLAUDE.md exige que toda mudança de código seja relatada junto
do contrato que ela protege.

1. **Runbook: `Tee-Object` → redirecionamento só para arquivo.** `Tee-Object` continua escrevendo no
   console além do arquivo; se o console travar (modo QuickEdit do PowerShell, o mesmo mecanismo que
   causou a falha de sistema do v68-09 — ver `RESEARCH_STATE_LEDGER_2026-09-27.md`), o `Tee-Object`
   trava esperando o console, o pipe enche, e o processo Python trava junto, sem erro. Todo comando
   "live" do runbook agora usa `*> arquivo.log` (todos os streams só pro arquivo, sem eco). Acompanhar
   progresso passou a ser uma segunda janela com `Get-Content -Wait -Tail`, que só lê o arquivo e não
   pode travar quem escreve nele. `powercfg /change standby-timeout-ac 0` também virou comando
   explícito na seção 0 do runbook, não só uma instrução em prosa.

2. **Stall guard portado de `src/route_research_forward_collection_v43.py` (commit `e4e95e8`,
   2026-10-05) para `src/route_research_forward_collection_900_v0.py`** — o coletor usado por
   `participant_quality_native_holdout_v1.py` e `participant_quality_native_memory_v1.py`, e portanto
   por esta replicação. Mesmo padrão exato do v43: `deadline`/`last_tick` monotônico calculado antes
   do loop (antes linha 101), e o loop (antes linha 154) agora mede o intervalo desde a última volta
   a cada iteração; se passar de `FORWARD_COLLECTION_900_STALL_GAP_SECONDS = 30.0`, falha explícito
   como `FAIL_MEMORY_FORWARD_900_STALL_DETECTED` em vez de cair silenciosamente em
   `INCONCLUSIVE_MEMORY_NO_AVAILABLE_300_900_OUTCOME` (que pareceria uma falta de disponibilidade de
   provider, não um travamento externo). Dois campos novos em `ForwardCollection900Summary`
   (`stall_detected`, `stall_gap_seconds`), ambos com default que preserva o comportamento anterior —
   nenhum ponto de construção existente foi afetado. Detector apenas; não evita o travamento, só
   recusa aceitar o resultado como se fosse um dado real. Testes:
   `python -m unittest tests.test_route_research_forward_collection_900_v0
   tests.test_participant_quality_native_holdout_v1 tests.test_participant_quality_native_memory_v1
   tests.test_participant_quality_native_memory_resume_v0
   tests.test_route_research_forward_cohort_v43 -v` → 23/23 OK, sem regressão.

3. **Auditoria pedida: `participant_quality_native_memory_v1.py` tem algum outro loop longo com o
   mesmo risco?** Não — `grep` por `while `/`time.monotonic()`/`time.sleep(`/`deadline` nesse arquivo
   não retornou nenhuma ocorrência própria; o único loop de risco que ele aciona é dentro do coletor
   900 corrigido no item 2. `route_research_signal_plane_bridge_v0.py` (o outro módulo que tanto o
   memory build quanto o holdout chamam) também não tem loop de poll próprio — usa `time.monotonic()`
   só para medir `elapsed_seconds` depois do fato. O polling de duração ao vivo em si acontece dentro
   de `benchmarks/integrated_market_signal_plane_v1/live_shadow.py` (`run_live_shadow_v0`), que é
   território do Signal Plane promovido — fora do escopo desta correção pela regra do CLAUDE.md sobre
   o hot path Rust ("prove que o problema está no Signal Plane antes de tocar"); não foi auditado nem
   alterado aqui. Se um travamento acontecer exatamente nessa camada durante esta replicação, isso é
   evidência nova e separada, não algo que esta correção já cobre.

## Execução

Runbook: `docs/participant-quality-tail-risk-replication-v1-collection-runbook-2026-10-07.md`.

## Registro

`docs/research-hypothesis-registry-v1-2026-10-04.md`, linha `PQ-TR-REPL-V1`, status
`PRE-REGISTRADA`, adicionada na mesma revisão deste documento.
