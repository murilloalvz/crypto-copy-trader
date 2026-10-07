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

1. Saída de todo comando "live" redirecionada para arquivo (`Tee-Object`/`tee`) — nunca só console.
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
  (`docs/live-readiness-gates-v1.md`) — esta replicação por si só não autoriza isso;
- `FAIL`: a linha fecha e **o filtro sai da pilha** — não se tenta outro horizonte, outro contraste,
  ou uma 2ª replicação;
- `INCONCLUSIVE` (suporte insuficiente): mesma disciplina de extensão única já usada em
  CD-PROMO-V0 — no máximo 1 extensão de coleta, run key novo, sem mudar nenhum parâmetro desta
  tabela.

## Execução

Runbook: `docs/participant-quality-tail-risk-replication-v1-collection-runbook-2026-10-07.md`.

## Registro

`docs/research-hypothesis-registry-v1-2026-10-04.md`, linha `PQ-TR-REPL-V1`, status
`PRE-REGISTRADA`, adicionada na mesma revisão deste documento.
