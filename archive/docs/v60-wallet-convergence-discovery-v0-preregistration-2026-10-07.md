# v60 Opportunity Wallet Convergence — Discovery V0 — pré-registro — 2026-10-07

Status: **PRE-REGISTRADA.** Autoriza a coleta descritiva (convergência de wallets + auditoria de cobertura causal) definida abaixo. **NÃO autoriza** nenhum teste econômico, nenhuma leitura de outcome/retorno de episódio, nem qualquer promoção automática de hipótese.

## Proveniência deste pré-registro

Este documento promove `docs/v60-wallet-convergence-discovery-v0-preregistration-DRAFT-2026-10-04.md`
(escrito na branch `research/v68-09-fase-a-prereg`, Fase A6, sem olhar nenhum
dado de episódio/wallet/outcome) de RASCUNHO para PRE-REGISTRADA nesta
branch (`research/rust-signal-plane-live-shadow-v0`).

- Gatilho: V68 fechado permanentemente em `FAIL_V68_PROSPECTIVE_FLOW60_BUY_SHARE_ROUTE_ONLY_HYPOTHESIS`
  (`docs/route-research-v68-prospective-flow60-buy-share-result-2026-10-05.md`).
  A própria árvore de decisão pré-registrada do V68
  (`docs/v68-09-preregistered-decision-tree-2026-10-04.md`, branch 3) nomeia
  v60 (Wallet Convergence) como um dos dois próximos caminhos legítimos rumo
  a um edge — o outro, Bundle Bot Detection V0, permanece bloqueado por uma
  decisão de engenharia separada (falta persistir `slot`/`creator`, fora do
  escopo desta etapa).
- Autorização do operador: "pode meter marcha vc esta no max" — autorização
  explícita para avançar de forma autônoma no próximo passo legítimo rumo a
  um edge, dado que não há bloqueio de código/plumbing para v60 (há para
  Bundle Bot Detection V0).
- **Nenhum parâmetro abaixo foi derivado de dado.** São exatamente as
  propostas já escritas no RASCUNHO de 2026-10-04, congeladas agora sem
  alteração. Nenhum episódio, wallet ou outcome foi lido antes deste commit.
- Esta etapa não testa nenhuma hipótese econômica (ver seção 1). Ela decide
  apenas se existe amostra suficiente para que uma hipótese econômica futura
  seja proposta — é um gate de viabilidade, não um teste de alpha.

Protocolo-pai: `docs/opportunity-wallet-convergence-v60-protocol-2026-09-08.md`
(causal clock, cohort freeze rule, controles obrigatórios, interpretações
proibidas). Manifesto: `docs/wallet-cohort-v65-pre-registration-protocol-2026-09-08.md`,
`src/wallet_cohort_manifest_v65.py`.

Este pré-registro cobre só os dois primeiros passos da promoção do v60:
`descriptive convergence -> causal coverage audit`.

## 1. Pergunta desta etapa

Nos episódios market-first já capturados (e nos futuros, estritamente
prospectivos — ver seção 2), wallets de uma coorte congelada antes do
episódio aparecem com frequência suficiente, e com identidade de wallet
coberta o bastante, para que um teste econômico futuro seja possível?

## 2. Coorte

- Sementes: as 8 wallets públicas listadas no protocolo v60 (Cented, Theo,
  Cupsey, Decu, Pain, Kadenox, Trunoest, Kev — endereços Solana completos em
  `docs/opportunity-wallet-convergence-v60-protocol-2026-09-08.md`). Não são
  recomendação de cópia.
- Fingerprint: `wallet_strategy_lab.py --sync-onchain` para cada semente,
  usando só transações com `chain_time` anterior ao `pre_period_end`
  (abaixo).
- Elegibilidade, sem olhar retorno de episódio: a wallet entra se tiver pelo
  menos `MIN_PRE_PERIOD_SWAPS` swaps de memecoin no pré-período. Nenhum
  critério de PnL futuro.
- Manifesto: `build_wallet_cohort_manifest_v65(cohort_key="v60-discovery-v0",
  registered_at=<horário do commit>, members=...)`, com cada
  `WalletCohortEvidenceMemberV65` usando `evidence_as_of = pre_period_end` e
  o `strategy_signature` do fingerprint. O hash do manifesto é commitado
  **antes** de qualquer leitura de `StoredMarketTrade` para esta etapa.
- Implementação: `benchmarks/v60_opportunity_wallet_convergence_v0/freeze_cohort.py`
  (CLI standalone; `--self-check` validado nesta branch antes do commit deste
  arquivo). O operador roda este script e **commita o JSON de saída** — esse
  commit É o ato de freeze/sign-off dos parâmetros abaixo.

Parâmetros congelados neste pré-registro (propostas do RASCUNHO de
2026-10-04, adotadas sem alteração; não derivadas de dado):

| Parâmetro | Valor congelado |
|---|---|
| `pre_period_end` | o horário do commit de freeze (saída de `freeze_cohort.py`, `--pre-period-end` padrão = agora) |
| janela do pré-período | 30 dias antes de `pre_period_end` (`--pre-period-days 30`) |
| `MIN_PRE_PERIOD_SWAPS` | 20 (`--min-pre-period-swaps 20`) |
| episódios elegíveis | só episódios com `as_of` depois de `registered_at` (estritamente prospectivo) |

Com a regra da última linha, nenhum episódio já capturado antes do freeze
entra. A coleta de episódios começa do zero depois do freeze, o que custa
calendário mas evita qualquer dúvida de retroatividade. Usar episódios
antigos exigiria provar que a coorte foi congelada antes deles, e isso é
impossível para episódios anteriores ao freeze.

## 3. Saídas descritivas (sem economia)

Por episódio, nas janelas naturais de 30s, 60s e 300s (do protocolo; nenhuma
janela escolhida por retorno):

- tamanho da coorte elegível e número de wallets da coorte que
  participaram;
- contagens de eventos de compra e venda da coorte;
- fração dos eventos de mercado com wallet conhecida que vem da coorte;
- cobertura de identidade de wallet do episódio
  (`wallet_identity_coverage_pct`);
- diversidade de `strategy_signature` entre as wallets participantes.

Agregado: fração dos episódios com pelo menos 1 e com pelo menos 2 wallets
da coorte, e distribuição da cobertura de identidade.

## 4. Auditoria de cobertura causal (passo 2 do protocolo)

Para cada evento da coorte usado: `chain_time <= as_of`, `observed_at <=
as_of`, wallet com freeze anterior ao `as_of`, mesmo run de aquisição e
mesmo token. Violação conta e é reportada; não é corrigida nem descartada em
silêncio.

## 5. Critério para ir ao próximo passo (definido agora, congelado)

O próximo passo (matched discovery com os quatro controles do protocolo) só
é proposto se, depois de `N_EPISODES_MIN = 200` episódios elegíveis:

- pelo menos `MIN_EPISODES_WITH_COHORT = 30` episódios tiverem participação
  de pelo menos uma wallet da coorte;
- a cobertura de identidade mediana dos episódios for de pelo menos 80%;
- violações de causal clock = 0.

Se o critério falhar, o resultado é `INSUFFICIENT_COHORT_PARTICIPATION` ou
`INSUFFICIENT_IDENTITY_COVERAGE`, e o v60 com estas sementes fecha nesta
forma. Não se troca a coorte depois de ver a participação.

## 6. O que fica proibido nesta etapa

- ler qualquer outcome (retorno, preço futuro) dos episódios;
- trocar sementes, janela de pré-período, elegibilidade, ou qualquer valor
  da tabela da seção 2 depois do freeze;
- tratar participação de wallet como sinal de compra;
- pular para o passo de matched discovery sem passar pelo critério da
  seção 5.

## 7. Dependências e riscos

- `wallet_strategy_lab.py --sync-onchain` faz chamadas de RPC: roda depois
  do V68 já classificado (está, `FAIL` em 2026-10-05), então não compete por
  rate limit com aquela coleta.
- Risco principal: as 8 sementes podem quase não aparecer nos episódios
  capturados pelo detector market-first. É exatamente isso que esta etapa
  mede antes de gastar qualquer esforço econômico.

## 8. Execução

Runbook completo para o operador:
`docs/v60-opportunity-wallet-convergence-discovery-v0-collection-runbook-2026-10-07.md`.

## 9. Registro

Linha correspondente em `docs/research-hypothesis-registry-v1-2026-10-04.md`,
tabela "Pré-registradas sem resultado conhecido nesta branch", ID `V60`,
atualizada de `RASCUNHO, aguarda sign-off` para `PRE-REGISTRADA` nesta
mesma revisão.
