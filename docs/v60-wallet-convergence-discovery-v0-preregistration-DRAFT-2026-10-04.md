# v60 Opportunity Wallet Convergence — Discovery V0 — pré-registro (RASCUNHO) — 2026-10-04

Status: **DRAFT. Não autoriza nada.** Escrito sem olhar nenhum dado de episódio, de wallet ou de outcome (Fase A / A6). Precisa de sign-off explícito do operador e de um commit de "freeze" antes de qualquer coleta ou leitura de dado.

Protocolo-pai: `docs/opportunity-wallet-convergence-v60-protocol-2026-09-08.md` (causal clock, cohort freeze rule, controles obrigatórios, interpretações proibidas). Manifesto: `docs/wallet-cohort-v65-pre-registration-protocol-2026-09-08.md`, `src/wallet_cohort_manifest_v65.py`.

Este rascunho cobre só os dois primeiros passos da promoção do v60: `descriptive convergence -> causal coverage audit`. Ele não testa nenhuma hipótese econômica.

## 1. Pergunta desta etapa

Nos episódios market-first já capturados, wallets de uma coorte congelada antes do episódio aparecem com frequência suficiente, e com identidade de wallet coberta o bastante, para que um teste econômico futuro seja possível?

## 2. Coorte

- Sementes: as 8 wallets públicas listadas no protocolo v60 (Cented, Theo, Cupsey, Decu, Pain, Kadenox, Trunoest, Kev). Não são recomendação de cópia.
- Fingerprint: `wallet_strategy_lab.py --sync-onchain` para cada semente, usando só transações com `chain_time` anterior ao `pre_period_end` (abaixo).
- Elegibilidade, sem olhar retorno de episódio: a wallet entra se tiver pelo menos `MIN_PRE_PERIOD_SWAPS` swaps de memecoin no pré-período. Nenhum critério de PnL futuro.
- Manifesto: `build_wallet_cohort_manifest_v65(cohort_key="v60-discovery-v0", registered_at=<horário do commit>, members=...)`, com cada `WalletCohortEvidenceMemberV65` usando `evidence_as_of = pre_period_end` e o `strategy_signature` do fingerprint. O hash do manifesto é commitado **antes** de qualquer leitura de `StoredMarketTrade` para esta etapa.

Parâmetros que o operador precisa congelar no sign-off (propostas, não derivadas de dado):

| Parâmetro | Proposta |
|---|---|
| `pre_period_end` | o horário do commit de freeze |
| janela do pré-período | 30 dias antes de `pre_period_end` |
| `MIN_PRE_PERIOD_SWAPS` | 20 |
| episódios elegíveis | só episódios com `as_of` depois de `registered_at` (estritamente prospectivo) |

Com a regra da última linha, nenhum episódio já capturado entra. A coleta começa do zero depois do freeze, o que custa calendário mas evita qualquer dúvida de retroatividade. Usar episódios antigos exigiria provar que a coorte foi congelada antes deles, e isso é impossível para episódios anteriores ao freeze.

## 3. Saídas descritivas (sem economia)

Por episódio, nas janelas naturais de 30s, 60s e 300s (do protocolo; nenhuma janela escolhida por retorno):

- tamanho da coorte elegível e número de wallets da coorte que participaram;
- contagens de eventos de compra e venda da coorte;
- fração dos eventos de mercado com wallet conhecida que vem da coorte;
- cobertura de identidade de wallet do episódio (`wallet_identity_coverage_pct`);
- diversidade de `strategy_signature` entre as wallets participantes.

Agregado: fração dos episódios com pelo menos 1 e com pelo menos 2 wallets da coorte, e distribuição da cobertura de identidade.

## 4. Auditoria de cobertura causal (passo 2 do protocolo)

Para cada evento da coorte usado: `chain_time <= as_of`, `observed_at <= as_of`, wallet com freeze anterior ao `as_of`, mesmo run de aquisição e mesmo token. Violação conta e é reportada; não é corrigida nem descartada em silêncio.

## 5. Critério para ir ao próximo passo (definido agora)

O próximo passo (matched discovery com os quatro controles do protocolo) só é proposto se, depois de `N_EPISODES_MIN` episódios elegíveis:

- pelo menos `MIN_EPISODES_WITH_COHORT` episódios tiverem participação de pelo menos uma wallet da coorte;
- a cobertura de identidade mediana dos episódios for de pelo menos 80%;
- violações de causal clock = 0.

Propostas para o sign-off: `N_EPISODES_MIN = 200`, `MIN_EPISODES_WITH_COHORT = 30`.

Se o critério falhar, o resultado é `INSUFFICIENT_COHORT_PARTICIPATION` ou `INSUFFICIENT_IDENTITY_COVERAGE`, e o v60 com estas sementes fecha nesta forma. Não se troca a coorte depois de ver a participação.

## 6. O que fica proibido nesta etapa

- ler qualquer outcome (retorno, preço futuro) dos episódios;
- trocar sementes, janela de pré-período ou elegibilidade depois do freeze;
- tratar participação de wallet como sinal de compra.

## 7. Dependências e riscos

- `wallet_strategy_lab.py --sync-onchain` faz chamadas de RPC: só depois do v68-09 classificado, para não competir por rate limit.
- Risco principal: as 8 sementes podem quase não aparecer nos episódios capturados pelo detector market-first. É exatamente isso que esta etapa mede antes de gastar qualquer esforço econômico.
